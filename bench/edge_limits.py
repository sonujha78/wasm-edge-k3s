#!/usr/bin/env python3
"""Minimum viable memory limit under light load (Part 6a).
For each workload x memory limit: deploy alone in namespace edge-sim, wait until it serves
/healthz, run wrk (c=20, 15s) against the pod IP, then check restarts / OOMKilled.
Stops a workload after 2 consecutive PASS results. Usage: python3 bench/edge_limits.py"""
import csv, http.client, json, os, subprocess, sys, time

NS = "edge-sim"
LIMITS = [4, 8, 16, 24, 32, 48, 64]  # MiB
WORKLOADS = {
    "wasm":      {"image": "localhost:5000/wasm-echo:v1",       "port": 80,   "runtime": "wasmtime-spin-v2", "cmd": ["/"]},
    "container": {"image": "localhost:5000/container-echo:v2",  "port": 8080, "runtime": None, "cmd": None},
    "python":    {"image": "localhost:5000/container-python:v1", "port": 8080, "runtime": None, "cmd": None},
}
COLS = ["workload", "limit_mib", "verdict", "rps", "non2xx", "socket_errors", "restarts", "reason"]


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)


def manifest(app, w, mib):
    c = {"name": app, "image": w["image"], "imagePullPolicy": "IfNotPresent",
         "ports": [{"containerPort": w["port"]}],
         "resources": {"requests": {"memory": f"{mib}Mi"}, "limits": {"memory": f"{mib}Mi"}}}
    if w["cmd"]:
        c["command"] = w["cmd"]
    spec = {"terminationGracePeriodSeconds": 2, "containers": [c]}
    if w["runtime"]:
        spec["runtimeClassName"] = w["runtime"]
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": app, "namespace": NS},
            "spec": {"replicas": 1, "selector": {"matchLabels": {"app": app}},
                     "template": {"metadata": {"labels": {"app": app}}, "spec": spec}}}


def get_pod(app):
    out = kubectl("-n", NS, "get", "pod", "-l", f"app={app}", "-o", "json").stdout
    items = json.loads(out).get("items", []) if out else []
    items = [p for p in items if not p["metadata"].get("deletionTimestamp")]
    return items[0] if items else None


def cstatus(p):
    cs = ((p or {}).get("status", {}).get("containerStatuses") or [{}])[0]
    reasons = []
    for st in (cs.get("state", {}), cs.get("lastState", {})):
        for k in ("terminated", "waiting"):
            r = (st.get(k) or {}).get("reason")
            if r and r not in ("ContainerCreating", "Completed"):
                reasons.append(r)
    reason = "OOMKilled" if "OOMKilled" in reasons else (reasons[0] if reasons else "")
    return cs.get("restartCount", 0), reason


def healthy(ip, port):
    try:
        c = http.client.HTTPConnection(ip, port, timeout=0.5)
        c.request("GET", "/healthz")
        r = c.getresponse()
        r.read()
        c.close()
        return r.status == 200
    except Exception:
        return False


def wait_started(app, port, timeout=45):
    end = time.time() + timeout
    while time.time() < end:
        p = get_pod(app)
        ip = (p or {}).get("status", {}).get("podIP")
        if ip and healthy(ip, port):
            return ip
        time.sleep(0.3)
    return None


def run_wrk(ip, port):
    out = subprocess.run(["wrk", "-t2", "-c20", "-d15s", "--latency", f"http://{ip}:{port}/healthz"],
                         capture_output=True, text=True).stdout
    rps, non2xx, sockerr = 0.0, 0, 0
    for line in out.splitlines():
        s = line.strip()
        if s.startswith("Requests/sec:"):
            rps = float(s.split()[1])
        elif s.startswith("Non-2xx"):
            non2xx = int(s.split()[-1])
        elif s.startswith("Socket errors:"):
            sockerr = 1
    return rps, non2xx, sockerr


def dump(rows):
    os.makedirs("bench/results", exist_ok=True)
    with open("bench/results/edge_limits.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(rows)


def main():
    kubectl("create", "namespace", NS)
    rows = []
    for name, w in WORKLOADS.items():
        app = f"probe-{name}"
        streak = 0
        for mib in LIMITS:
            kubectl("apply", "-f", "-", stdin=json.dumps(manifest(app, w, mib)))
            ip = wait_started(app, w["port"])
            rps, non2xx, sockerr = 0.0, 0, 0
            if ip:
                rps, non2xx, sockerr = run_wrk(ip, w["port"])
                time.sleep(1)
            restarts, reason = cstatus(get_pod(app))
            ok = bool(ip) and restarts == 0 and non2xx == 0 and not sockerr and rps > 0
            verdict = "PASS" if ok else "FAIL"
            if not ip and not reason:
                reason = "no-start"
            row = {"workload": name, "limit_mib": mib, "verdict": verdict, "rps": round(rps),
                   "non2xx": non2xx, "socket_errors": sockerr, "restarts": restarts, "reason": reason}
            rows.append(row)
            dump(rows)
            print(row, flush=True)
            kubectl("-n", NS, "delete", "deploy", app, "--cascade=foreground", "--wait=true", "--timeout=60s")
            streak = streak + 1 if ok else 0
            if streak >= 2:
                break

    print("\nminimum viable memory limit under light load (2 consecutive PASS):")
    for name in WORKLOADS:
        passes = [r["limit_mib"] for r in rows if r["workload"] == name and r["verdict"] == "PASS"]
        print(f"  {name:<10}{min(passes) if passes else 'none of the tested limits'} MiB")


if __name__ == "__main__":
    main()
