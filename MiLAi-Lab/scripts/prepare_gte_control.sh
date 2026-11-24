#!/usr/bin/env bash
set -euo pipefail
target=${1:-/cra/milai-experiments/v13-qrag/staging/gte/base}
mkdir -p "$target"
base=https://hf-mirror.com/Alibaba-NLP/gte-multilingual-reranker-base/resolve/8215cf04918b
implementation=https://hf-mirror.com/Alibaba-NLP/new-impl/resolve/40ced75c3017
get_asset() {
    local file=$1 url=$2
    [[ -s "$target/$file" ]] && return 0
    curl --fail --location --silent --show-error --retry 3 --connect-timeout 12 \
        --max-time 1200 --output "$target/$file.part" "$url" || return 1
    mv "$target/$file.part" "$target/$file"
}
for file in model.safetensors config.json tokenizer_config.json special_tokens_map.json; do
    get_asset "$file" "$base/$file"
done
get_asset tokenizer.json "$base/tokenizer.json" || get_asset tokenizer.json \
    https://modelscope.cn/models/iic/gte-multilingual-reranker-base/resolve/master/tokenizer.json
for file in modeling.py configuration.py; do
    get_asset "$file" "$implementation/$file"
done
"${PYTHON:-python3}" - "$target" <<'PY'
import json
import sys
from pathlib import Path
from safetensors import safe_open
from transformers import AutoTokenizer

base = Path(sys.argv[1])
config = base / "config.json"
values = json.loads(config.read_text())
values["auto_map"] = {k: v.split("--")[-1] for k, v in values["auto_map"].items()}
config.write_text(json.dumps(values, indent=2))
with safe_open(base / "model.safetensors", framework="pt") as f:
    print("GTE pretrained tensors", len(f.keys()))
print("tokenizer vocab", AutoTokenizer.from_pretrained(base, local_files_only=True).vocab_size)
PY
