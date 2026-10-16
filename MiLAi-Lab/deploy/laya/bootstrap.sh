#!/usr/bin/env bash
# Deploy upstream open-source Laya with its official CPU/CUDA Compose files.
set -euo pipefail

ROOT="${LAYA_SOURCE_DIR:-${HOME}/.local/share/milai-laya-upstream}"
REF="${LAYA_SOURCE_REF:-main}"
if [[ ! -d "${ROOT}/.git" ]]; then
  git clone --filter=blob:none https://github.com/NandhaKishorM/laya.git "${ROOT}"
fi
git -C "${ROOT}" fetch origin "${REF}"
git -C "${ROOT}" checkout --detach FETCH_HEAD
printf 'Laya source: %s\n' "$(git -C "${ROOT}" rev-parse HEAD)"

export LAYA_MODEL="${LAYA_MODEL:-multilingual}"
export LAYA_MODELS="${LAYA_MODELS:-multilingual}"
export LAYA_PRELOAD="${LAYA_PRELOAD:-1}"
export LAYA_BIND_ADDRESS="${LAYA_BIND_ADDRESS:-127.0.0.1}"
export LAYA_PORT="${LAYA_PORT:-8000}"
export LAYA_REVISION="${LAYA_REVISION:-reviewed}"

cd "${ROOT}"
files=(-f compose.yaml -f compose.http.yaml)
if [[ "${LAYA_DEVICE:-cpu}" == cuda ]]; then
  files+=(-f compose.cuda.yaml)
fi
docker compose "${files[@]}" up --build -d --wait laya-serve
printf 'Laya health: http://127.0.0.1:%s/health\n' "${LAYA_PORT}"
