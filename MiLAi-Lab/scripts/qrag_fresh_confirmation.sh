#!/usr/bin/env bash
# Build a confirmation-only cold episode database from the scoped local exposure records.
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
root=${MILAI_V13_ROOT:-/cra/milai-experiments/v13-qrag}
historical=/cra/memory/mx_memory
reservation=/data/milai-experiments/20261112-reader-utility/new-confirmation-source-reservation-v1
export PYTHONPATH="$project/src${PYTHONPATH:+:$PYTHONPATH}"
export TOKENIZERS_PARALLELISM=false
build_python=${MILAI_DATA_PYTHON:-/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python}
replay=$(find "$root/ref/exposure-replay" -name initial-validation-replay.json -print -quit)
test -s "$replay"
output=${MILAI_FRESH_DIR:-"$root/staging/fresh-confirm"}
"$build_python" -m milai_lab.datasets.memory_control_fresh \
  --parent /cra/milai-datasets/memory_control_v1_2 \
  --qasper "$root/fresh-sources/qasper-test-and-evaluator-v0.3.tgz" \
  --persona-root "$historical/benchmarks/contextual-user-memory/personamem-v2" \
  --reservation "$reservation/reserved-source-identities.txt" \
  --role-inventory "$root/inventory/native-groups.tsv.gz" \
  --ref-exposure "$replay" --ref-roster "$root/ref/fixed-dev-roster.json" \
  --history /data/milai-experiments "$historical/MiLAi-worktrees" "$historical/MiLAi" \
    "$historical/MiLAi-Lab" "$historical/MiLAi-Artifact-Archive" "$historical/artifacts" "$historical/var" "$historical/evidence" \
  --output "$output"
cp "$output/source-role-audit.json" "$root/fresh-sources/final-source-role-audit.json"
"$build_python" "$project/scripts/qrag_audit_fresh_ledgers.py" \
  --dataset "$output/memory_control.sqlite3" \
  --history /data/milai-experiments/20261118-memory-control-v11 /data/milai-experiments/20261119-memory-control-v12 \
  --contextual "$historical/MiLAi/MiLAi-Lab/artifacts/contextual-user-memory" \
  --native-databases /cra/milai-datasets/{memory_control_v1,memory_control_v1_1,memory_control_v1_2}/memory_control.sqlite3 \
  --output "$root/fresh-sources/final-packet-ledger-audit.json"
