#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$REPO_ROOT/_site}"
PREVIEW_PREFIX="/untrace/preview/dev"

cd "$REPO_ROOT"
git fetch origin main dev

rm -rf "$OUT"
mkdir -p "$OUT/preview/dev"

extract_docs() {
  local ref="$1"
  local dest="$2"
  local tmp
  tmp="$(mktemp -d)"
  git archive "$ref" docs | tar -x -C "$tmp"
  cp -r "$tmp/docs/." "$dest/"
  rm -rf "$tmp"
}

extract_docs "origin/main" "$OUT"
extract_docs "origin/dev" "$OUT/preview/dev"

while IFS= read -r -d '' html; do
  sed -i "s|href=\"/untrace/\"|href=\"${PREVIEW_PREFIX}/\"|g" "$html"
done < <(find "$OUT/preview/dev" -maxdepth 1 -name '*.html' -print0)

echo "Pages site built at $OUT (main + preview/dev)"
