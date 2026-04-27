#!/usr/bin/env bash
set -euo pipefail

cd /home/runner/FinanceNotebook
NB="/home/runner/FinanceNotebook/FinMarketsNotebook.ipynb"

/usr/bin/env python3 -m jupyter nbconvert \
  --to notebook \
  --execute "$NB" \
  --inplace \
  --ExecutePreprocessor.kernel_name=python3 \
  --ExecutePreprocessor.timeout=7200
