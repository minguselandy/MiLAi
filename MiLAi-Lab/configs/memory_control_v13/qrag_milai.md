# Q-RAG-MiLAi environment and feedback

The project adapter uses the V1.2 read-only SQLite release, which carries the V1 clean splits, deterministic MCQ choices, public navigation and Reader contract. All project policies share the initial BM25 search over 32 candidates, the first eight ranked objects, the 2,048-token material limit and six operations including SEARCH. A terminal action at the operation limit can be a READ. CorpusExecution then delivers the normalized packet to DatasetReader. The scored MuSiQue training branch uses its companion's independent cold rollout under the same frozen policy, decoding settings and seed. The controller sees only its own legal observation.

| Property | Official Q-RAG reference | Q-RAG-MiLAi |
| --- | --- | --- |
| Task and supervision | Official QA task and supporting-fact collection | Clean three-source tasks, measured Reader results at delivery |
| Observation | State and document chunk bodies | Acquired and delivered evidence, public previews, operation history and budget |
| Choices | Remaining document chunks | Common R2, R3 and HANDOFF legal menu |
| Return | Official PQN discount and soft value | Undiscounted finite-horizon TD(λ) with one native quality payment |
| Critic | State and action towers, dot-product heads for the same return | Full GTE embedding towers, two half-vector dot products for quality and a separate future-cost head |
| Exploration and bootstrap | PQN top-five temperature sampling and entropy-regularized target | Top-five temperature sampling using predicted quality less cost, Polyak target with an expected native value under that distribution |
| Costs | Reference recipe | Exact immediate incremental material tokens, future material deltas and actual Reader input/output tokens; GPU and wall times recorded separately |
| Terminal and unknown | Reference environment rules | HANDOFF or hard task limits terminate, unavailable native quality stays masked |

The adapter uses temperature 0.005, λ-return coefficient 0.6, Polyak update fraction 0.02 and full-parameter AdamW. Each update fits a batch of freshly visited, completed task trajectories. Unmeasured Reader quality or usage stays masked. Repeat and companion calls enter the arm's exposure. The original reference implementation and retrieval curves are tracked separately in this directory.

From MiLAi-Lab, the shared seed-11 warm collection uses

```bash
PYTHONPATH=src python -m milai_lab.runners.control_policy_iteration \
  --output /cra/milai-experiments/v13-qrag/warm-11 --seed 11 --calls 2000
```

Each compressed pack in `packs/` contains one legal root, the action bindings, measured outcomes and eligible comparisons. Terminal responses, actual Reader debits, timing, native scores and companion receipt keys are retained in `receipts/`. A busy Reader lease is retried before dispatch. Unknown in-flight measurements consume conservative exposure and carry a quality mask. Sampling and fitting both use the TRAIN split.

For the 2k–6k mechanism stage, both arms use a common pool seed, frozen rule continuation, the same candidate window, and `--exclude-roots-from` pointing to warm. The active arm supplies its warm checkpoint to `--sampler-checkpoint`. A compatible earlier arm can be passed as `--reuse-from`; whole Reader requests, native task, seed and protocol must match. Each round directory owns its own `--calls` quota. To obtain checkpoints at 6k, 12k and 24k after 2k warm, the incremental quotas are 4k, 6k and 12k. Natural online rounds take their arm's preceding checkpoint via `--continuation-checkpoint`. The training driver reads the `continuation_policy_id` for every label.

The dual-tower online trainer accepts `--backbone`, `--output`, `--calls` and `--cost-scale`. Use the common TRAIN cost normalization frozen for all arms. Evaluation uses the `qrag_milai` policy and its saved `control.pt` and `controller.json` directory through the shared episode runner, with `environment=qrag_milai_v13`.

## Embedding backbone retrieval

The executed QR pilot used the historical GTE configuration compatible with the installed Transformers 4.57 environment. The listed revision is a download locator. The config, tokenizer and weights can be acquired into the experiment volume with these commands.

```bash
set -e
qr=/cra/milai-experiments/v13-qrag/staging/qr/gte-multilingual-base
mkdir -p "$qr"
cd "$qr"
for f in config.json tokenizer.json tokenizer_config.json special_tokens_map.json; do
  curl -fLsS --retry 2 "https://hf-mirror.com/Alibaba-NLP/gte-multilingual-base/resolve/9bbca17d9273/$f" -o "$f.part"
  mv "$f.part" "$f"
done
curl -fLsS --retry 2 'https://modelscope.cn/models/iic/gte-multilingual-base/resolve/master/model.safetensors' -o weights.part
python3 - <<'PY'
import json
from pathlib import Path
p = Path("weights.part")
with p.open("rb") as f:
    size = int.from_bytes(f.read(8), "little")
    header = json.loads(f.read(size))
assert p.stat().st_size == 8 + size + max(
    t["data_offsets"][1] for t in header.values() if "data_offsets" in t
)
p.replace("model.safetensors")
PY
cp ../../gte/base/{configuration.py,modeling.py} .
python3 - <<'PY'
import json
from pathlib import Path
p = Path("config.json")
config = json.loads(p.read_text())
config["auto_map"] = {k: v.split("--")[-1] for k, v in config["auto_map"].items()}
p.write_text(json.dumps(config, indent=2))
PY
```

The two copied files are the same local GTE implementation used by the controller. QR loads every embedding/encoder tensor into two independent trainable towers and creates its own projection and cost layers. DatasetReader stays frozen.

The 48-call resource pilot uses batch eight, seed 11 and a scale of 1,413 from the first 60 complete warm TRAIN packs. Its exact entry point from MiLAi-Lab is

```bash
root=/cra/milai-experiments/v13-qrag
env CUDA_VISIBLE_DEVICES=3 PYTHONPATH=src HF_HOME="$root/staging/qr/hf-cache" HF_HUB_OFFLINE=1 \
  TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 \
  /data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python \
  -m milai_lab.runners.qrag_milai_train --backbone "$root/staging/qr/gte-multilingual-base" \
  --output "$root/qr-s0" --checkpoint-root "$root/staging/qr/s0" \
  --calls 48 --batch 8 --cost-scale 1413
```

## Formal QR scheduling and storage

The seed-11 online job waits for the shared 2,000-call warm round and the 48-call pilot. From MiLAi-Lab, use the pilot's Python/CUDA environment and run

```bash
python tools/run_qrag_milai_after_warm.py --root /cra/milai-experiments/v13-qrag --calls 12000
```

The supervisor records both live producer leases in `qr-11/launch.json`, computes the shared warm median and replaces itself with the online trainer. Compact episode summaries, per-update measurements and launch state live in `qr-11/`. During the disk capacity constraint `qr-11/receipts` links to `staging/qr/formal-receipts`, which holds raw Reader responses and replayable action transitions on the temporary mount. Evaluation weights and their native TRAIN group bindings live in `staging/qr/formal/checkpoint-{calls}`. The fitted-group roster and an optional arm `feedback_calls` binding are checked by the `qrag_milai` backend before evaluation. The temporary mount requires migration for long-term retention.

The formal learning-rate horizon covers 24k exposures so the 12k weights are comparable when training continues. Its length is computed before fitting from the TRAIN group roster, batch size and the 6k/12k/24k boundaries under one charged request per member. For seed 11 and batch 32 this gives 422 planned updates. AdamW uses a 5% linear warmup and linear decay to 10% of the 5e-6 peak. Actual update counts, learning rates and quality-observed transitions are recorded independently. Exploration temperature stays fixed at 0.005. The resource pilot used constant 5e-6.

To check a saved formal checkpoint, run `tools/verify_qrag_milai_checkpoint.py --run /cra/milai-experiments/v13-qrag/qr-11 --checkpoint /cra/milai-experiments/v13-qrag/staging/qr/formal/checkpoint-12000` with the training Python environment. This resolves linked native measurements, detects overlap in receipt provenance, measures changes in both encoder towers, reloads the policy and compares its scores on the recorded live observation. The early 48-call pilot has a post-load score measurement and reconstructed native group bindings.
