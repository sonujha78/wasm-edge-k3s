#!/usr/bin/env python3
"""Edge density (Part 6b): pods per unit of RAM, measured on the real host.
Phase 1 (sweep): N replicas -> host MemAvailable delta vs pod-cgroup view (kubectl top).
Phase 2 (quota): 512Mi ResourceQuota -> how many pods become Ready, and what that costs the host.
Aborts a step if host MemAvailable drops below GUARD_MIB. Usage: python3 bench/density.py"""
import csv, json, os, statistics, subprocess, time

GUARD_MIB = 1500
NS1, NS2 = "edge-density", "edge-quota"
CFG = {
    "wasm":      {"image": "localhost:5000/wasm-echo:v1",        "port": 80,   "runtime": "wasmtime-spin-v2", "cmd": ["/"], "mib": 8,  "sweep": [1, 5, 10, 20, 40]},
    "container": {"image": "localhost:5000/container-echo:v2",   "port": 8080, "runtime": None, "cmd": None, "mib": 4,  "sweep": [1, 5, 10, 20, 40]},
    "python":    {"image": "localhost:5000/container-python:v1", "port": 8080, "runtime": None, "cmd": None, "mib": 48, "sweep": [1, 5, 10]},
}
COLS = ["phase", "workload", "target", "ready", "host_delta_mib", "per_pod_host_mib",
        "cgroup_top_mib", "per_pod_cgroup_mib", "note"]


def kubectl(*args, stdin=None):
    return subprocess.run(["kubectl", *args], input=stdin, capture_output=True, text=True)


def manifest(ns, app, w, replicas):
    mem = f"{w['mib']}Mi"
    c = {"name": app, "image": w["image"], "imagePullPolicy": "IfNotPresent",
         "ports": [{"containerPort": w["port"]}],
         "resources": {"requests": {"memory": mem}, "limits": {"memory": mem}},
         "readinessProbe": {"httpGet": {"path": "/healthz", "port": w["port"]}, "periodSeconds": 2}}
    if w["cmd"]:
        c["command"] = w["cmd"]
    spec = {"terminationGracePeriodSeconds": 2, "containers": [c]}
    if w["runtime"]:
        spec["runtimeClassName"] = w["runtime"]
    return {"apiVersion": "apps/v1", "kind": "Deployment",
            "metadata": {"name": app, "namespace": ns},
            "spec": {"replicas": replicas, "selector": {"matchLabels": {"app": app}},
                     "template": {"metadata": {"labels": {"app": app}}, "spec": spec}}}


def mem_available_mib():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024.0
    return 0.0


def settled_mem(settle=30):
    time.sleep(settle)
    vals = []
    for _ in range(3):
        vals.append(mem_available_mib())
        time.sleep(4)
    return statistics.median(vals)


def to_mib(s):
    for suf, f in (("Ki", 1 / 1024), ("Mi", 1), ("Gi", 1024)):
        if s.endswith(suf):
            return float(s[:-2]) * f
    try:
        return float(s) / (1024 * 1024)
    except ValueError:
        return 0.0


def top_sum_mib(ns):
    out = kubectl("top", "pods", "-n", ns, "--no-headers").stdout
    total = 0.0
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 3:
            total += to_mib(p[2])
    return total


def ready_count(ns, app):
    out = kubectl("-n", ns, "get", "deploy", app, "-o", "jsonpath={.status.readyReplicas}").stdout.strip()
    return int(out) if out.isdigit() else 0


def wait_ready(ns, app, n, timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        if mem_available_mib() < GUARD_MIB:
            return ready_count(ns, app), True
        r = ready_count(ns, app)
        if r >= n:
            return r, False
        time.sleep(1)
    return ready_count(ns, app), False


def wait_stable(ns, app, timeout=300, quiet=25):
    end = time.time() + timeout
    last, since = -1, time.time()
    while time.time() < end:
        if mem_available_mib() < GUARD_MIB:
            return ready_count(ns, app), True
        r = ready_count(ns, app)
        if r != last:
            last, since = r, time.time()
        elif r > 0 and time.time() - since >= quiet:
            break
        time.sleep(1)
    return ready_count(ns, app), False


def teardown(ns, app):
    kubectl("-n", ns, "scale", f"deploy/{app}", "--replicas=0")
    kubectl("-n", ns, "delete", "deploy", app, "--cascade=foreground", "--wait=true", "--timeout=180s")
    time.sleep(20)


def dump(rows):
    os.makedirs("bench/results", exist_ok=True)
    with open("bench/results/density.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=COLS)
        wr.writeheader()
        wr.writerows(rows)


def add_row(rows, phase, name, target, ready, base, ns, note):
    avail = settled_mem()
    delta = base - avail
    top = top_sum_mib(ns)
    row = {"phase": phase, "workload": name, "target": target, "ready": ready,
           "host_delta_mib": round(delta, 1),
           "per_pod_host_mib": round(delta / ready, 2) if ready else 0,
           "cgroup_top_mib": round(top, 1),
           "per_pod_cgroup_mib": round(top / ready, 2) if ready else 0,
           "note": note}
    rows.append(row)
    dump(rows)
    print(row, flush=True)


def main():
    rows = []
    for ns in (NS1, NS2):
        kubectl("delete", "namespace", ns, "--ignore-not-found", "--wait=true", "--timeout=180s")
        kubectl("create", "namespace", ns)

    print("== phase 1: replica sweep", flush=True)
    for name, w in CFG.items():
        app = f"d-{name}"
        kubectl("apply", "-f", "-", stdin=json.dumps(manifest(NS1, app, w, 0)))
        time.sleep(5)
        base = settled_mem()
        for n in w["sweep"]:
            kubectl("-n", NS1, "scale", f"deploy/{app}", f"--replicas={n}")
            ready, aborted = wait_ready(NS1, app, n)
            note = "aborted: host MemAvailable below guard" if aborted else ("timeout" if ready < n else "")
            add_row(rows, "sweep", name, n, ready, base, NS1, note)
            if aborted or ready < n:
                break
        teardown(NS1, app)

    print("== phase 2: 512Mi ResourceQuota", flush=True)
    quota = {"apiVersion": "v1", "kind": "ResourceQuota",
             "metadata": {"name": "edge-512mi", "namespace": NS2},
             "spec": {"hard": {"requests.memory": "512Mi", "limits.memory": "512Mi", "pods": "200"}}}
    kubectl("apply", "-f", "-", stdin=json.dumps(quota))
    for name, w in CFG.items():
        app = f"q-{name}"
        kubectl("apply", "-f", "-", stdin=json.dumps(manifest(NS2, app, w, 0)))
        time.sleep(5)
        base = settled_mem()
        kubectl("-n", NS2, "scale", f"deploy/{app}", "--replicas=200")
        ready, aborted = wait_stable(NS2, app)
        note = f"quota math fits {512 // w['mib']}"
        if aborted:
            note += "; aborted: host MemAvailable below guard"
        add_row(rows, "quota", name, 200, ready, base, NS2, note)
        teardown(NS2, app)

    kubectl("delete", "namespace", NS1, NS2, "--wait=false")

    print(f"\n{'phase':<7}{'workload':<11}{'target':>7}{'ready':>7}{'host MiB':>10}{'/pod':>8}{'cgroup MiB':>12}{'/pod':>8}")
    for r in rows:
        print(f"{r['phase']:<7}{r['workload']:<11}{r['target']:>7}{r['ready']:>7}{r['host_delta_mib']:>10}"
              f"{r['per_pod_host_mib']:>8}{r['cgroup_top_mib']:>12}{r['per_pod_cgroup_mib']:>8}   {r['note']}")
    print("\nmarginal host cost per extra pod (sweep):")
    for name in CFG:
        s = [r for r in rows if r["phase"] == "sweep" and r["workload"] == name and r["ready"] >= 1]
        if len(s) >= 2 and s[-1]["ready"] > s[0]["ready"]:
            a, b = s[0], s[-1]
            print(f"  {name:<10}{(b['host_delta_mib'] - a['host_delta_mib']) / (b['ready'] - a['ready']):.1f} MiB/pod"
                  f"  (N={a['ready']}..{b['ready']})")


if __name__ == "__main__":
    main()
