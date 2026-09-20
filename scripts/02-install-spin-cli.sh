#!/usr/bin/env bash
# Installs the Spin CLI at the same version embedded in containerd-shim-spin.
# Finds the release asset by pattern (asset naming differs per architecture).
set -euo pipefail
SPIN_VERSION="${SPIN_VERSION:-v4.0.1}"
case "$(uname -m)" in
  x86_64) PATTERN='linux-(amd64|x86_64)\.tar\.gz$' ;;
  aarch64|arm64) PATTERN='linux-(aarch64|arm64)\.tar\.gz$' ;;
  *) echo "unsupported arch: $(uname -m)"; exit 1 ;;
esac
URL=$(curl -fsSL "https://api.github.com/repos/spinframework/spin/releases/tags/${SPIN_VERSION}" \
  | jq -r '.assets[].browser_download_url' | grep -E "$PATTERN" | grep -v static | head -1 || true)
[ -n "$URL" ] || { echo "no matching Spin release asset for $(uname -m) at ${SPIN_VERSION}"; exit 1; }
echo ">> downloading $URL"
TMP="$(mktemp -d)"
curl -fsSL -o "${TMP}/spin.tar.gz" "$URL"
tar -xzf "${TMP}/spin.tar.gz" -C "${TMP}"
sudo install -m 0755 "${TMP}/spin" /usr/local/bin/spin
rm -rf "${TMP}"
spin --version
