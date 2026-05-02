#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export APP_SECRETS_DIR="${APP_SECRETS_DIR:-$PROJECT_ROOT/secrets}"

if [[ -x ".venv/bin/financial-market-report" ]]; then
  CMD=(".venv/bin/financial-market-report")
else
  CMD=("financial-market-report")
fi

"${CMD[@]}" run "$@"
