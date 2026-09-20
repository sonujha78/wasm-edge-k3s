#!/usr/bin/env python3
"""Memory footprint at idle and under light load.
Run with: sudo env "KUBECONFIG=$HOME/.kube/config" "PATH=$PATH" python3 bench/memory.py"""
import csv, glob, json, os, subprocess, sys, time

WORKLOADS = {
    "wasm":      {"app": "wasm-echo",      "port": 80},
    "container": {"app": "container-echo", "port": 8080},
}
MIB = 1024 * 1024


def run(args):
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def pod_of(app):
    d = json.loads(run(["kubectl", "get", "pod", "-l", f"app={app}", "-o", "json"]))
    p = d["items"][0]
    return p["metadata"]["name"], p["metadata"]["uid"], p["status"]["podIP"]


def pod_cgroup(uid):
    cands = []
    for key in (uid.replace("-", "_"), uid):
        cands += [p for p in glob.glob(f"/sys/fs/cgroup/**/*pod{key}*", recursive=True) if os.path.isdir(p)]
    if not cands:
        sys.exit(f"cgroup for pod uid {uid} not found")
    return min(cands, key=len)


def cg_mem(cg):
    cur = int(open(f"{cg}/memory.current").read())
    stat = {}
    for line in open(f"{cg}/memory.stat"):
        k, v = line.split()
        stat[k] = int(v)
    peak_f = f"{cg}/memory.peak"
    peak = int(open(peak_f).read()) if os.path.exists(peak_f) else 0
    return {
        "cg_working_set": cur - stat.get("inactive_file", 0),
        "cg_anon": stat.get("anon", 0),
        "cg_peak": peak,
    }


def descendants(pid):
    out = [pid]
    for child in run(["pgrep", "-P", str(pid)]).split():
        out += descendants(int(child))
    return out


def pss_bytes(pid):
    try:
        for line in open(f"/proc/{pid}/smaps_rollup"):
            if line.startswith("Pss:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        pass
    return 0


def pod_pids(name, cg):
    """Shim process tree + every pid inside the pod cgroup."""
    sid = run(["k3s", "crictl", "pods", "--name", name, "-q"]).split()[0]
    pids = set()
    for p in run(["pgrep", "-f", f"containerd-shim.* -id {sid}"]).split():
        pids.update(descendants(int(p)))
    for f in glob.glob(f"{cg}/**/cgroup.procs", recursive=True):
        pids.update(int(x) for x in open(f).read().split())
    return pids


def snapshot(name, uid):
    cg = pod_cgroup(uid)
    m = cg_mem(cg)
    pids = pod_pids(name, cg)
    m["proc_pss"] = sum(pss_bytes(p) for p in pids)
    m["nprocs"] = len(pids)
    return m


def main():
    os.makedirs("bench/results", exist_ok=True)
    rows = []
    for wl, cfg in WORKLOADS.items():
        name, uid, ip = pod_of(cfg["app"])
        print(f"[{wl}] pod={name} ip={ip} -> settling 30s for idle reading")
        time.sleep(30)
        rows.append({"workload": wl, "phase": "idle", **snapshot(name, uid)})
        print(f"[{wl}] light load: wrk -t2 -c20 -d30s")
        out = run(["wrk", "-t2", "-c20", "-d30s", "--latency", f"http://{ip}:{cfg['port']}/healthz"])
        open(f"bench/results/wrk-{wl}.txt", "w").write(out + "\n")
        for line in out.splitlines():
            if "Requests/sec" in line or "Latency" in line or "99%" in line or "50%" in line:
                print("   ", line.strip())
        rows.append({"workload": wl, "phase": "load", **snapshot(name, uid)})

    cols = ["workload", "phase", "cg_working_set", "cg_anon", "cg_peak", "proc_pss", "nprocs"]
    with open("bench/results/memory.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerows(rows)

    print(f"\n{'workload':<10}{'phase':<6}{'cg_workset':>12}{'cg_anon':>10}{'cg_peak':>10}{'proc_pss':>10}{'#procs':>8}   (MiB)")
    for r in rows:
        print(f"{r['workload']:<10}{r['phase']:<6}{r['cg_working_set']/MIB:>12.2f}{r['cg_anon']/MIB:>10.2f}"
              f"{r['cg_peak']/MIB:>10.2f}{r['proc_pss']/MIB:>10.2f}{r['nprocs']:>8}")


if __name__ == "__main__":
    main()
