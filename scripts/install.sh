#!/usr/bin/env bash
set -euo pipefail

REPO=lovebrownie/untrace
API="https://api.github.com/repos/${REPO}/releases/latest"

tag=$(
  curl -fsSL "$API" |
    grep -m1 '"tag_name"' |
    sed 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/'
)
if [ -z "$tag" ]; then
  echo "failed to resolve latest release tag" >&2
  exit 1
fi

ver="${tag#v}"
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *)
    echo "unsupported architecture: $(uname -m)" >&2
    exit 1
    ;;
esac

deb="untrace-${ver}-${arch}.deb"
url="https://github.com/${REPO}/releases/download/${tag}/${deb}"

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

curl -fsSL -o "${tmpdir}/${deb}" "$url"
sudo apt install -y "${tmpdir}/${deb}"
