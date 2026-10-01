#!/bin/sh
# Construit le .whl du plugin dans dist/
set -eu
cd "$(dirname "$0")"

if command -v uv >/dev/null 2>&1; then
    exec uv build
fi

exec python3 -m build
