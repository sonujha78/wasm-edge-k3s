#!/usr/bin/env bash
# Part 7: portability. Same .wasm on arm64 (QEMU-emulated) vs a container needing a 2nd build.
# NOTE: arm64 here is EMULATED, so timings are not meaningful; only "same binary runs" is proven.
set -euo pipefail
cd "$(dirname "$0")/.."

SPIN_VERSION="${SPIN_VERSION:-v4.0.1}"
WASM=apps/wasm-echo/target/wasm32-wasip2/release/wasm_echo.wasm
TOML=apps/wasm-echo/spin.toml
WORK=/tmp/arm64-portability

echo "== host arch: $(uname -m)"
echo "== emulated arm64 check: $(docker run --rm --platform linux/arm64 alpine uname -m)"

echo; echo "== 1. the WASM artifact (built once on x86_64, never rebuilt)"
HOST_SHA=$(sha256sum "$WASM" | cut -d' ' -f1)
echo "host   sha256: $HOST_SHA"
ls -l "$WASM"
file "$WASM" || true

rm -rf "$WORK"
mkdir -p "$WORK/app/target/wasm32-wasip2/release" "$WORK/spin"
cp "$TOML" "$WORK/app/spin.toml"
cp "$WASM" "$WORK/app/target/wasm32-wasip2/release/wasm_echo.wasm"

echo; echo "== 2. run the SAME .wasm on an arm64 Spin runtime"
ASSET_URL=$(curl -fsSL "https://api.github.com/repos/spinframework/spin/releases/tags/${SPIN_VERSION}" \
  | jq -r '.assets[].browser_download_url' | grep -E 'linux-(aarch64|arm64)\.tar\.gz$' | grep -v static | head -1 || true)
[ -n "$ASSET_URL" ] || { echo "no arm64 Spin asset found for ${SPIN_VERSION}"; exit 1; }
echo "spin arm64 asset: $ASSET_URL"
curl -fsSL -o "$WORK/spin/spin.tar.gz" "$ASSET_URL"
tar -xzf "$WORK/spin/spin.tar.gz" -C "$WORK/spin"
file "$WORK/spin/spin" || true

docker rm -f wasm-arm64 >/dev/null 2>&1 || true
docker run -d --name wasm-arm64 --platform linux/arm64 \
  -v "$WORK/app:/app" -v "$WORK/spin/spin:/usr/local/bin/spin:ro" -w /app \
  -p 127.0.0.1:18090:3000 ubuntu:24.04 spin up --listen 0.0.0.0:3000 >/dev/null
sleep 2
echo "uname -m inside container: $(docker exec wasm-arm64 uname -m)"
echo "spin inside container:     $(docker exec wasm-arm64 spin --version)"
ARM_SHA=$(docker exec wasm-arm64 sha256sum /app/target/wasm32-wasip2/release/wasm_echo.wasm | cut -d' ' -f1)
echo "arm64  sha256: $ARM_SHA"
if [ "$HOST_SHA" = "$ARM_SHA" ]; then echo "identical binary: YES"; else echo "identical binary: NO"; exit 1; fi

OK=0
for i in $(seq 1 120); do
  if curl -fs -o /dev/null http://127.0.0.1:18090/healthz; then OK=1; break; fi
  sleep 0.5
done
if [ "$OK" != 1 ]; then echo "wasm on arm64 did NOT respond; container logs:"; docker logs wasm-arm64 2>&1 | tail -20; exit 1; fi
echo "GET /healthz -> $(curl -s http://127.0.0.1:18090/healthz)"
echo "GET /echo    -> $(curl -s 'http://127.0.0.1:18090/echo?arch=arm64')"
docker rm -f wasm-arm64 >/dev/null

echo; echo "== 3. the container equivalent needs a SECOND build for arm64"
echo "existing image arch: $(docker image inspect --format '{{.Architecture}}' localhost:5000/container-echo:v2)"
TIMEFORMAT='arm64 image build wall time (emulated): %R s'
time docker build --platform linux/arm64 -t localhost:5000/container-echo:v2-arm64 apps/container-echo >/tmp/arm64-build.log 2>&1 \
  || { echo "arm64 build FAILED:"; tail -20 /tmp/arm64-build.log; exit 1; }
echo "new image arch:      $(docker image inspect --format '{{.Architecture}}' localhost:5000/container-echo:v2-arm64)"
docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}' | grep container-echo

docker rm -f echo-arm64 >/dev/null 2>&1 || true
docker run -d --name echo-arm64 --platform linux/arm64 -p 127.0.0.1:18091:8080 \
  localhost:5000/container-echo:v2-arm64 >/dev/null
OK=0
for i in $(seq 1 60); do
  if curl -fs -o /dev/null http://127.0.0.1:18091/healthz; then OK=1; break; fi
  sleep 0.5
done
if [ "$OK" != 1 ]; then echo "arm64 container did NOT respond; logs:"; docker logs echo-arm64 2>&1 | tail -20; exit 1; fi
echo "GET /echo -> $(curl -s 'http://127.0.0.1:18091/echo?arch=arm64')"
docker rm -f echo-arm64 >/dev/null

echo; echo "SUMMARY: wasm rebuilds needed: 0 (sha256 identical). container: 1 extra build + 1 extra image per architecture."
