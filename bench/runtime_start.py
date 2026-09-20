#!/usr/bin/env python3
"""Runtime-level cold start WITHOUT Kubernetes: process launch -> first HTTP 200 (ms).
  wasm      : `spin up` (Wasmtime in-process)
  container : `docker run --network host`, static Rust binary in scratch image
  python    : `docker run --network host`, Flask + gunicorn image
Run from the repo root: python3 bench/runtime_start.py [iterations]"""
import csv, http.client, os, signal, statistics, subprocess, sys, time

DEVNULL = subprocess.DEVNULL
NAME = "bench-runtime-start"
CASES = {
    "wasm": {"port": 18081, "cwd": "apps/wasm-echo",
             "cmd": ["spin", "up", "--listen", "127.0.0.1:18081"]},
    "container": {"port": 18080, "cwd": None,
                  "cmd": ["docker", "run", "--rm", "--name", NAME, "--network", "host",
                          "-e", "LISTEN_ADDR=127.0.0.1:18080", "localhost:5000/container-echo:v2"]},
    "python": {"port": 18082, "cwd": None,
               "cmd": ["docker", "run", "--rm", "--name", NAME, "--network", "host",
                       "localhost:5000/container-python:v1", "gunicorn", "-b", "127.0.0.1:18082",
                       "-w", "1", "--threads", "2", "app:app"]},
}


def healthy(port):
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
        c.request("GET", "/healthz")
        r = c.getresponse()
        r.read()
        c.close()
        return r.status == 200
    except Exception:
        return False


def docker_cleanup():
    subprocess.run(["docker", "rm", "-f", NAME], stdout=DEVNULL, stderr=DEVNULL)


def stop(proc):
    docker_cleanup()
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)


def once(case):
    docker_cleanup()
    t0 = time.perf_counter()
    proc = subprocess.Popen(case["cmd"], cwd=case["cwd"], stdout=DEVNULL, stderr=DEVNULL,
                            start_new_session=True)
    ms = None
    while time.perf_counter() - t0 < 30:
        if healthy(case["port"]):
            ms = (time.perf_counter() - t0) * 1000
            break
        time.sleep(0.001)
    stop(proc)
    time.sleep(0.5)
    return ms


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    os.makedirs("bench/results", exist_ok=True)
    rows = []
    for name, case in CASES.items():
        print(f"== {name}: warm-up (discarded)")
        once(case)
        for i in range(1, n + 1):
            ms = once(case)
            print(name, i, None if ms is None else round(ms, 1))
            rows.append({"workload": name, "iter": i, "first_200_ms": None if ms is None else round(ms, 1)})
    with open("bench/results/runtime_start.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["workload", "iter", "first_200_ms"])
        wr.writeheader()
        wr.writerows(rows)
    print(f"\n{'workload':<11}{'median':>9}{'min':>9}{'max':>9}   (ms, launch -> first 200)")
    for name in CASES:
        v = [r["first_200_ms"] for r in rows if r["workload"] == name and r["first_200_ms"] is not None]
        if v:
            print(f"{name:<11}{statistics.median(v):>9.1f}{min(v):>9.1f}{max(v):>9.1f}")


if __name__ == "__main__":
    main()
