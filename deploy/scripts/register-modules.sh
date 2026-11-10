#!/usr/bin/env bash
# Thin wrapper: prefer Python registrar (no curl/apt needed inside containers).
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/register-modules.py"
