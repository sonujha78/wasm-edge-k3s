#!/usr/bin/env python3
"""Cold-start benchmark: scale a Deployment 0 -> 1 and time each stage in ms.
Usage: python3 bench/coldstart.py [iterations]"""
import csv, http.client, json, os, statistics, subprocess, sys, time

WORKLOADS = {
    "wasm":      {"deploy": "wasm-echo",      "selector": "app=wasm-echo",      "port": 80},
    "container": {"deploy": "container-echo", "selector": "app=container-echo", "port": 8080},
    "python": {"deploy": "container-python", "selector": "app=container-python", "port": 8080},
}
API = ("127.0.0.1", 8001)
NS = "default"
KEYS = ("pod_ip", "running", "first_200", "ready")


def api(method, path, body=None, ctype="application/json"):
    conn = http.client.HTTPConnection(*API, timeout=10)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, body=payload, headers={"Content-Type": ctype} if payload else {})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return json.loads(data) if data else {}


def scale(deploy, n):
    api("PATCH", f"/apis/apps/v1/namespaces/{NS}/deployments/{deploy}/scale",
        {"spec": {"replicas": n}}, ctype="application/merge-patch+json")


def pods(selector):
    return api("GET", f"/api/v1/namespaces/{NS}/pods?labelSelector={selector}").get("items", [])


def wait_gone(selector, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        if not pods(selector):
            return
        time.sleep(0.2)
    sys.exit(f"pods for {selector} did not terminate within {timeout}s")


def http_ok(ip, port, path="/healthz"):
    try:
        c = http.client.HTTPConnection(ip, port, timeout=0.25)
        c.request("GET", path)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status == 200
    except Exception:
        return False


def one_run(w):
    scale(w["deploy"], 0)
    wait_gone(w["selector"])
    time.sleep(1)  # let CNI / containerd settle
    t0 = time.perf_counter()
    scale(w["deploy"], 1)
    m = {}
    while len(m) < len(KEYS) and time.perf_counter() - t0 < 60:
        items = pods(w["selector"])
        now = (time.perf_counter() - t0) * 1000
        if not items:
            continue
        st = items[0].get("status", {})
        ip = st.get("podIP")
        if ip and "pod_ip" not in m:
            m["pod_ip"] = now
        cs = st.get("containerStatuses") or []
        if cs and "running" in (cs[0].get("state") or {}) and "running" not in m:
            m["running"] = now
        for c in st.get("conditions", []):
            if c["type"] == "Ready" and c["status"] == "True" and "ready" not in m:
                m["ready"] = now
        if ip and "first_200" not in m and http_ok(ip, w["port"]):
            m["first_200"] = (time.perf_counter() - t0) * 1000
    return m


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    proxy = subprocess.Popen(["kubectl", "proxy", "--port=8001"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    os.makedirs("bench/results", exist_ok=True)
    rows = []
    try:
        for name, w in WORKLOADS.items():
            print(f"== {name}: warm-up run (discarded)")
            one_run(w)
            for i in range(1, n + 1):
                m = one_run(w)
                row = {"workload": name, "iter": i}
                for k in KEYS:
                    row[k] = round(m.get(k, float("nan")), 1)
                rows.append(row)
                print(name, i, {k: row[k] for k in KEYS})
            scale(w["deploy"], 1)
    finally:
        proxy.terminate()

    with open("bench/results/coldstart.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["workload", "iter", *KEYS])
        wr.writeheader()
        wr.writerows(rows)

    print(f"\n{'workload':<10}{'metric':<11}{'median':>9}{'min':>9}{'max':>9}   (ms)")
    for wl in WORKLOADS:
        for k in KEYS:
            vals = [r[k] for r in rows if r["workload"] == wl and r[k] == r[k]]
            if vals:
                print(f"{wl:<10}{k:<11}{statistics.median(vals):>9.1f}{min(vals):>9.1f}{max(vals):>9.1f}")


if __name__ == "__main__":
    main()
