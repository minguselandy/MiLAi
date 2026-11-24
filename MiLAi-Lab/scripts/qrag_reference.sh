#!/usr/bin/env bash
# Run from an environment with CUDA PyTorch and Transformers installed.
set -euo pipefail
project=$(cd "$(dirname "$0")/.." && pwd)
experiment=${MILAI_V13_ROOT:-/cra/milai-experiments/v13-qrag}
assets=${MILAI_REF_ASSETS:-"$experiment/staging/ref"}
model=${MILAI_REF_BASE:-"$experiment/models/multilingual-e5-large"}
source_dir="$experiment/reference/Q-RAG"
result_dir="$experiment/ref"
revision=42358d78ac491843763b90677f07237471c97086
official_zip=${MUSIQUE_ZIP:-/cra/milai-datasets/memory_control_v1/raw/musique_full/musique_data_v1.0.zip}
export CUDA_VISIBLE_DEVICES=${REF_GPU:-2}
export TORCH_COMPILE_DISABLE=1
export TOKENIZERS_PARALLELISM=false
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
# Compilation caches and HF metadata must not consume space in the code worktree.
export HF_HOME="$assets/cache/hf"
export TORCHINDUCTOR_CACHE_DIR="$assets/cache/torchinductor"
export TRITON_CACHE_DIR="$assets/cache/triton"

case "${1:-}" in
prepare)
    mkdir -p "$experiment/reference" "$result_dir" "$model" "$assets/musique"
    if [[ ! -d "$source_dir" ]]; then
        git init -q "$source_dir"
        git -C "$source_dir" remote add origin https://github.com/griver/Q-RAG.git
        git -C "$source_dir" fetch -q --depth 1 origin "$revision"
        git -C "$source_dir" checkout -q --detach FETCH_HEAD
    fi
    patch="$project/configs/memory_control_v13/qrag_ref_40gb.patch"
    if ! git -C "$source_dir" apply --reverse --check "$patch" 2>/dev/null; then
        git -C "$source_dir" apply "$patch"
    fi
    # The upstream local loader reads just these two members of the V1 archive.
    unzip -jn "$official_zip" 'data/musique_ans_v1.0_train.jsonl' 'data/musique_ans_v1.0_dev.jsonl' -d "$assets/musique"
    # Older saved configurations named the staged base path. Keep it loadable on rebuild.
    if [[ ! -e "$assets/e5-large" && "$model" != "$assets/e5-large" ]]; then
        ln -s "$model" "$assets/e5-large"
    fi
    python3 "$project/scripts/qrag_ref_dev_roster.py" --roles "$experiment/inventory/native-groups.tsv.gz" \
        --source "$assets/musique" --output "$assets/musique-tune300" --frozen "$result_dir/fixed-dev-roster.json"
    for f in config.json tokenizer_config.json special_tokens_map.json sentencepiece.bpe.model tokenizer.json model.safetensors; do
        if [[ ! -s "$model/$f" ]]; then
            curl -fL --retry 3 --continue-at - -o "$model/$f.part" \
                "https://huggingface.co/intfloat/multilingual-e5-large/resolve/3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3/$f?download=true"
            mv "$model/$f.part" "$model/$f"
        fi
    done
    ;;
train)
    label=${2:?provide new run label}
    mkdir -p "$result_dir"
    run="$result_dir/$label"
    mkdir "$run"
    cd "$source_dir"
    /usr/bin/time -q -f '{"elapsed_seconds":%e,"cpu_user_seconds":%U,"cpu_sys_seconds":%S,"max_rss_kib":%M,"exit_code":%x}' \
        -o "$run/fit-resource.json" python3 -u train_q_rag.py envs=musique algo=pqn_e5_musique \
        "envs.data_path=$assets/musique-tune300" "algo.model.model_name=$model" \
        steps_count=10000 batch_size=12 accumulate_grads=8 eval_interval=100 \
        eval_episodes=300 seed=42 envs_parallel=1 max_action_length=110 \
        max_action_length_in_memory=110 +algo.pqn.hyperparams.critic_microbatch=2 \
        "logger.log_dir=$run" "+checkpoint_dir=$assets/checkpoints/$label" \
        > "$run/training.log" 2>&1
    trained=$(dirname "$(find "$run" -name config.yaml -print -quit)")
    "$project/scripts/qrag_reference.sh" evaluate "$trained" > "$run/retrieval-validation.log" 2>&1
    ;;
evaluate)
    trained=$(realpath "${2:?provide upstream run directory containing config.yaml}")
    exec {evaluation_lock}>"$trained/.retrieval-evaluation.lock"
    flock "$evaluation_lock"
    if [[ ! -s "$trained/reference-result.json" ]]; then
        python3 "$project/scripts/qrag_ref_result.py" --prepare-terminal --run "$trained"
        if [[ ! -e "$assets/musique-tune300/roster.json" || ! -e "$assets/e5-large/config.json" ]]; then
            "$project/scripts/qrag_reference.sh" prepare
        fi
        python3 "$project/scripts/qrag_ref_result.py" --begin-validation --run "$trained"
        cd "$source_dir"
        /usr/bin/time -q -f '{"elapsed_seconds":%e,"cpu_user_seconds":%U,"cpu_sys_seconds":%S,"max_rss_kib":%M,"exit_code":%x}' \
            -a -o "$trained/validation-resource.jsonl" python3 -u eval_retriever.py \
            "pretrained_path=$trained" num_samples=-1 +envs.max_steps=4
        timing_args=()
        if [[ -s "$experiment/initial-schedule.json" ]]; then
            timing_args+=(--schedule "$experiment/initial-schedule.json")
        fi
        python3 "$project/scripts/qrag_ref_result.py" "${timing_args[@]}" --run "$trained" \
            --roster "$assets/musique-tune300/roster.json"
    fi
    # An attached mirror may still be verifying the last atomic checkpoint after fit exit.
    if [[ -e "$trained/retained-actors/.writer.lock" ]]; then
        flock "$trained/retained-actors/.writer.lock" true
    fi
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 nice -n 8 python3 "$project/scripts/qrag_ref_result.py" \
        --run "$trained" --archive-terminal "$model/model.safetensors"
    cat "$trained/reference-result.json"
    ;;
*)
    echo "Usage: $0 prepare | train RUN_LABEL | evaluate UPSTREAM_RUN_DIR" >&2
    exit 2
    ;;
esac
