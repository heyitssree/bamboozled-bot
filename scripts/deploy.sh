#!/bin/bash
# scripts/deploy.sh [env] [--yes]   Diff first, then deploy all four stacks. Needs Docker running (the image is built here)
# and a bootstrapped account. Never changes run_enabled: use enable.sh / disable.sh.
set -euo pipefail
cd "$(dirname "$0")" && cd .. && cd infra
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f bamboozled.env ] || { echo "infra/bamboozled.env is missing: run scripts/find-host.sh first"; exit 1; }
cdk synth --strict -q
cdk diff || true
[ "${2:-}" = "--yes" ] || read -r -p "Deploy these changes? [y/N] " ok && [ "${ok:-y}" = "y" ] || exit 1
cdk deploy --all --require-approval broadening
