#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required for mission setup." >&2
  exit 1
fi

for pkg in automake autoconf pkg-config pcre xz ripgrep ugrep rust; do
  if ! brew list --formula "$pkg" >/dev/null 2>&1; then
    brew install "$pkg"
  fi
done

if [ ! -d ".venv-ag-tests" ]; then
  python3 -m venv .venv-ag-tests
fi

.venv-ag-tests/bin/python -m pip install --upgrade pip >/dev/null
.venv-ag-tests/bin/python -m pip install cram >/dev/null

if [ ! -x "./ag" ]; then
  ./build.sh
fi

if [ -f "Cargo.toml" ] || [ -f "rust-ag/Cargo.toml" ]; then
  cargo fetch
fi

echo "init complete"
