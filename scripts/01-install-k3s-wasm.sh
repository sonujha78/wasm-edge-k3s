#!/usr/bin/env bash
# Installs K3s + containerd-shim-spin-v2 on this node (works on x86_64 and aarch64)
set -euo pipefail

SHIM_VERSION="${SHIM_VERSION:-$(curl -fsSL https://api.github.com/repos/spinframework/containerd-shim-spin/releases/latest | jq -r .tag_name)}"
ARCH="$(uname -m)"

echo ">> Installing K3s"
curl -sfL https://get.k3s.io | sh -s - --write-kubeconfig-mode 644

echo ">> Installing containerd-shim-spin-v2 ${SHIM_VERSION} (${ARCH})"
TMP="$(mktemp -d)"
curl -fsSL -o "${TMP}/shim.tar.gz" \
  "https://github.com/spinframework/containerd-shim-spin/releases/download/${SHIM_VERSION}/containerd-shim-spin-v2-linux-${ARCH}.tar.gz"
tar -xzf "${TMP}/shim.tar.gz" -C "${TMP}"
sudo install -m 0755 "${TMP}/containerd-shim-spin-v2" /usr/local/bin/containerd-shim-spin-v2
rm -rf "${TMP}"

echo ">> Restarting K3s so it detects the shim"
sudo systemctl restart k3s
echo ">> Done. Shim version: ${SHIM_VERSION}"
