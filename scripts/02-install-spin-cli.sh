#!/usr/bin/env bash
# Installs the Spin CLI at the same version embedded in containerd-shim-spin.
set -euo pipefail
SPIN_VERSION="${SPIN_VERSION:-v4.0.1}"
case "$(uname -m)" in
  x86_64) SPIN_ARCH=amd64 ;;
  aarch64|arm64) SPIN_ARCH=arm64 ;;
  *) echo "unsupported arch: $(uname -m)"; exit 1 ;;
esac
TMP="$(mktemp -d)"
curl -fsSL -o "${TMP}/spin.tar.gz" \
  "https://github.com/spinframework/spin/releases/download/${SPIN_VERSION}/spin-${SPIN_VERSION}-linux-${SPIN_ARCH}.tar.gz"
tar -xzf "${TMP}/spin.tar.gz" -C "${TMP}"
sudo install -m 0755 "${TMP}/spin" /usr/local/bin/spin
rm -rf "${TMP}"
spin --version
