#!/usr/bin/env bash
# Download promtool and amtool (static release binaries) into ./bin for local rule/config
# validation. Verifies the SHA-256 against the upstream sha256sums.txt. Starts nothing.
set -euo pipefail

PROMETHEUS_VERSION="${PROMETHEUS_VERSION:-3.16.0}"
ALERTMANAGER_VERSION="${ALERTMANAGER_VERSION:-0.35.0}"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$(uname -m)" in
  x86_64 | amd64) ARCH=amd64 ;;
  aarch64 | arm64) ARCH=arm64 ;;
  *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
esac

cd "$(dirname "$0")/.."
mkdir -p bin
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

fetch() {
  local project="$1" version="$2" binary="$3"
  local name="${project}-${version}.${OS}-${ARCH}"
  local base="https://github.com/prometheus/${project}/releases/download/v${version}"
  echo "==> ${project} ${version} (${OS}/${ARCH})"
  curl -fsSL -o "$tmp/${name}.tar.gz" "${base}/${name}.tar.gz"
  curl -fsSL -o "$tmp/sha256sums.txt" "${base}/sha256sums.txt"
  (cd "$tmp" && grep " ${name}.tar.gz\$" sha256sums.txt | sha256sum -c -)
  tar -xzf "$tmp/${name}.tar.gz" -C "$tmp" "${name}/${binary}"
  install -m 0755 "$tmp/${name}/${binary}" "bin/${binary}"
}

fetch prometheus "$PROMETHEUS_VERSION" promtool
fetch alertmanager "$ALERTMANAGER_VERSION" amtool
bin/promtool --version | head -1
bin/amtool --version | head -1
