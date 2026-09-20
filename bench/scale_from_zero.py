#!/usr/bin/env python3
"""Scale-from-zero through the KEDA HTTP add-on interceptor.
Per workload: wait until scaled to 0, send ONE request via the interceptor, record
client-perceived latency plus when KEDA scaled / pod created / Running / Ready.
Usage: python3 bench/scale_from_zero.py [iterations]"""
import csv, http.client, json, os, statistics, subprocess, sys, threading, time

NS = "default"
API = ("127.0.0.1", 8001)
WORKLOADS = {
    "wasm":      {"deploy": "wasm-echo",        "selector": "app=wasm-echo",        "host": "wasm-echo.example.com"},
    "container": {"deploy": "container-echo",   "selector": "app=container-echo",   "host": "container-echo.example.com"},
    "python":    {"deploy": "container-python", "selector": "app=container-python", "host": "container-python.example.com"},
}
KEYS = ("keda_scaled", "pod_created", "running", "ready")


def api_get(path):
    c = http.client.HTTPConnection(*API, timeout=10)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    c.close()
    return json.loads(data)


def deploy_replicas(name):
    d = api_get(f"/apis/apps/v1/namespaces/{NS}/deployments/{name}")
    return d["spec"].get("replicas") or 0


def pods_of(selector):
    return api_get(f"/api/v1/namespaces/{NS}/pods?labelSelector={selector}").get("items", [])


def wait_zero(w, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        if deploy_replicas(w["deploy"]) == 0 and not pods_of(w["selector"]):
            return
        time.sleep(0.5)
    sys.exit(f"{w['deploy']} did not scale to zero within {timeout}s (ScaledObject applied?)")


class Watcher(threading.Thread):
    def __init__(self, w, t0):
        super().__init__(daemon=True)
        self.w, self.t0, self.m, self.halt = w, t0, {}, False

    def run(self):
        while not self.halt:
            try:
                reps = deploy_replicas(self.w["deploy"])
                items = pods_of(self.w["selector"])
            except Exception:
                continue
            now = (time.perf_counter() - self.t0) * 1000
            if reps >= 1:
                self.m.setdefault("keda_scaled", now)
            if items:
                self.m.setdefault("pod_created", now)
                st = items[0].get("status", {})
                cs = st.get("containerStatuses") or []
                if cs and "running" in (cs[0].get("state") or {}):
                    self.m.setdefault("running", now)
                for c in st.get("conditions", []):
                    if c["type"] == "Ready" and c["status"] == "True":
                        self.m.setdefault("ready", now)
            time.sleep(0.01)


def get(addr, host, path="/healthz"):
    c = http.client.HTTPConnection(addr, 8080, timeout=60)
    t = time.perf_counter()
    c.request("GET", path, headers={"Host": host})
    r = c.getresponse()
    r.read()
    ms = (time.perf_counter() - t) * 1000
    c.close()
    return r.status, ms


def interceptor_ip():
    out = subprocess.run(["kubectl", "-n", "keda", "get", "svc", "keda-add-ons-http-interceptor-proxy",
                          "-o", "jsonpath={.spec.clusterIP}"], capture_output=True, text=True).stdout.strip()
    if not out:
        sys.exit("interceptor proxy service not found in namespace keda")
    return out


COLS = ["workload", "iter", "status", "total_ms", *KEYS, "warm_ms"]


def dump(rows):
    with open("bench/results/scale_from_zero.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(rows)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    os.makedirs("bench/results", exist_ok=True)
    proxy = subprocess.Popen(["kubectl", "proxy", "--port=8001"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    addr = interceptor_ip()
    rows = []
    try:
        for name, w in WORKLOADS.items():
            print(f"== {name}: iteration 0 is a warm-up (discarded)")
            for i in range(0, n + 1):
                wait_zero(w)
                time.sleep(2)
                t0 = time.perf_counter()
                watcher = Watcher(w, t0)
                watcher.start()
                status, ms = get(addr, w["host"])
                end = time.time() + 3
                while "ready" not in watcher.m and time.time() < end:
                    time.sleep(0.02)
                watcher.halt = True
                watcher.join(1)
                warm = statistics.median(get(addr, w["host"])[1] for _ in range(30))
                row = {"workload": name, "iter": i, "status": status, "total_ms": round(ms, 1),
                       "warm_ms": round(warm, 2)}
                for k in KEYS:
                    row[k] = round(watcher.m.get(k, float("nan")), 1)
                print(name, i, row)
                if i > 0:
                    rows.append(row)
                    dump(rows)
    finally:
        proxy.terminate()

    cols = ["workload", "iter", "status", "total_ms", *KEYS, "warm_ms"]
    with open("bench/results/scale_from_zero.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)

    print(f"\n{'workload':<10}{'metric':<13}{'median':>9}{'min':>9}{'max':>9}   (ms)")
    for name in WORKLOADS:
        for k in ("total_ms", *KEYS, "warm_ms"):
            v = [r[k] for r in rows if r["workload"] == name and r[k] == r[k]]
            if v:
                print(f"{name:<10}{k:<13}{statistics.median(v):>9.1f}{min(v):>9.1f}{max(v):>9.1f}")
        bad = [r for r in rows if r["workload"] == name and r["status"] != 200]
        if bad:
            print(f"  !! {len(bad)} non-200 responses for {name}")


if __name__ == "__main__":
    main()
