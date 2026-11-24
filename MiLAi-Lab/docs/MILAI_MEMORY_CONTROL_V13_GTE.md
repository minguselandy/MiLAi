# V13 GTE interaction controller

The fitted controller uses the 306M GTE sequence-classification checkpoint and its pretrained pooler. A single joint encoding covers both READ levels for one object. Four value heads consume that representation, the original relevance logit, the legal level and the action-aligned Host features. The trainable controller has 306,375,945 parameters. The Reader is external to the optimizer.

The text serializer reserves capacity for task, remaining budget, acquired-only evidence, delivered evidence, action history, the menu and the current object preview. It reads the online observation and action table. A controller decision maximizes the four-head mean of quality minus the calibrated penalty times predicted future cost plus known immediate cost, with the penalty applied to their sum. Cost units in training are incremental material tokens and actual Reader input/output tokens. The shared formal normalizing scale is 1,912 tokens, the median Host terminal prompt size across 192 TRAIN groups at a 2,048-token material budget. This calibration made zero Reader requests. QR, DQ, PQ-U and PQ-A can each obtain it before feedback collection. Deployment efficiency is evaluated using the measured resource categories.

## Rebuilding the local assets

These commands use the existing V12 Python environment on this machine. The pre-native Transformers integration of the official GTE model supports its installed Transformers 4.57.6. The downloader uses a pinned model revision and the corresponding locally imported model implementation. Downloads and checkpoints use the mounted experimental storage under `/cra`.

```bash
cd /data/milai-worktrees/memory-control-v13-qrag-20261125/MiLAi-Lab
export PYTHON=/data/milai-experiments/20261116-small-memory-control/verification-env-v1/bin/python
export PYTHONPATH=src TOKENIZERS_PARALLELISM=false CUDA_VISIBLE_DEVICES=3
R=/cra/milai-experiments/v13-qrag
G="$R/staging/gte"
export HF_HOME="$G/hf-cache"
scripts/prepare_gte_control.sh "$G/base"
```

## Evidence initialization

Recompute the inherited clean TRAIN roles using the V1.2 execution index. The first pass follows native evidence on legal V13 trajectories. It supplies a demonstration after a complete annotated set is actually delivered at a legal HANDOFF or a feasible hard operation limit. The second pass translates action bindings from registered 2,048-token TRAIN states and replays them under the same 32-retrieved, eight-object, six-operation environment. It adds distinct reachable prefixes and recomputes the native evidence labels. Each task is committed independently for resumption.

```bash
"$PYTHON" -m milai_lab.runners.control_evidence_init --dataset /cra/milai-datasets/memory_control_v1_2 --output "$G/evidence.sqlite"
"$PYTHON" -m milai_lab.runners.control_evidence_replay --dataset /cra/milai-datasets/memory_control_v1_2 --output "$G/evidence.sqlite"
"$PYTHON" -m milai_lab.runners.pretrained_control_train --objective evidence --data "$G/evidence.sqlite" --output "$G/s1" --metrics "$R/gte/s1" --seed 11
```

The default S1 fit traverses every eligible root once. Each native group shuffles its roots and spaces them across allocation windows averaging at most 256 roots. Within each window, group-first shuffling visits distinct native groups before cycling. Initial source weights are 0.50/0.35/0.15 among available groups. The window count admits at most four roots per MuSiQue group and six per QASPER or Persona group. Sources relinquish slots after exhausting their allowance. Each unique root contributes once over the full traversal. The epoch loss gives each source its registered mass, then equal mass to each native group in that source. The run receipt lists root counts by source, fitted group identities, task counts, demonstration steps and optimizer updates.

## Outcome training

The fitter accepts one or more pack directories for the same frozen continuation target. Both DQ and PQ-U take the same inputs and optimization seed. PQ adds a Huber loss on observed within-root quality differences. Each root normalizes the contributions of its measured actions and pairs before its source and native-group weighting. The two objectives share four group-bootstrap heads. Evaluation uses their mean. The fit receipt records the frozen Host cost scale, its report and the compact semantic witness. Parent and child fits check the same source/group/task/token observations. Later rounds initialize from their previous checkpoint. For a 6k mechanism checkpoint, start from the shared 2k paired fit and train on that arm’s newly completed 4k packs under the same frozen continuation policy. The 6k direct comparison starts from its corresponding 2k direct fit and uses the uniform arm’s new packs. Later rounds consume the newly collected packs for their registered continuation policy.

```bash
"$PYTHON" tools/calibrate_memory_control_v13_cost_unit.py --data /cra/milai-datasets/memory_control_v1_2 --output "$R/frozen-host-cost-scale.json" --budget 2048 --groups-per-source 64 --seed 20261125
for objective in direct paired; do
    "$PYTHON" -m milai_lab.runners.pretrained_control_train \
        --objective "$objective" --data "$R/warm-11/packs" \
        --cost-scale-report "$R/frozen-host-cost-scale.json" --initialize "$G/s1/checkpoint" \
        --output "$G/warm-$objective" --metrics "$R/gte/warm-$objective"
done
```

Run the warm fits on the frozen 2k package. Their default exposure is three epochs, AdamW in FP32 with BF16 encoder computation, an effective batch of 32 root states, a learning rate of 1e-5, 5% warmup and unit gradient clipping. Per-update curves and the first real encoder gradient/update go into the metrics directory. The encoder batch counter tracks object batches submitted for scoring. The measured fit duration includes activation recomputation during backpropagation. The checkpoint loader reads the controller weights and its explicit model configuration. Each finished fit must reproduce the final in-memory action scores after reloading. The normal episode runner accepts `pretrained_checkpoint` with an explicit `utility_lambda` and `gte_relevance` with a fixed read count, level and explicit object batch. Frozen baseline arms can set `object_batch=8` to match the formal evaluated controller.

## Executed checks

A 64-root diagnostic performed two optimizer updates in 22.05 seconds of fit time and used 8.65 GB peak allocated CUDA memory. A separate matched 64-root throughput run evaluated a cap of 4,096 padded tokens per encoder forward. Processing up to eight objects reduced fit time from 30.03 to 23.41 seconds and forward batches from 289 to 178. Peak memory was 8.43 GB under both configurations. Formal fits use the eight-object setting. The sampled QKV parameter had a nonzero gradient and changed from −0.02165222 to −0.02166222. The reloaded policy chose HANDOFF for the predeclared QASPER TRAIN diagnostic task 44720. Its native F1 was zero. The Reader ledger charged one request with 275 input and 21 output tokens. Controller forward time was 469.92 GPU-ms. A matched 32-root DQ/PQ diagnostic exercised 69 observed action comparisons and reproduced both models’ action scores after reload. The diagnostic fits used window-normalized root weights. Formal DQ and PQ share epoch-normalized source and group weights. These measurements cover pipeline execution. The full learning curves require the declared checkpoint populations.

The machine stores the compact diagnostic receipts under `/cra/milai-experiments/v13-qrag/gte/`. The `staging/` mount is volatile. The running S1 output path `staging/gte/s1` is bind-mounted to persistent `weights/s1` on the same host. Its recovery and final checkpoint files use that persistent directory. Persistent replicas of the foundation reranker and frozen S1 evidence database are in `models/gte-multilingual-reranker-base/` and `gte/evidence.sqlite` under the same experiment root. The SQLite backup retains the full source/group/task inventory.

The formal S1 roster contains 119,394 legal roots from 43,901 processed TRAIN tasks. MuSiQue contributes 110,133 roots from 19,924 groups, QASPER 5,351 from 817 papers and Persona 3,910 from 65 personas. The registered run uses one traversal and 3,732 optimizer updates. Its live curve and completion receipt are in `gte/s1/`. Source inventory and the 2,048-token protocol are in `gte/evidence-inventory.json` and the fit contract.

An initial allocation by large source passes produced gaps of 71,516 roots for QASPER and 78,612 for Persona. This partial run ended at update 77 after 2,464 roots and a 544.58-second shared-device fit window. The corrected run restarted from the same pretrained GTE weights and seed. Its verified longest gaps are 291 and 275 roots respectively, and each of its ten epoch deciles contains all three sources. The retained partial curve is in `gte/s1-initial-allocation/`. The full corrected schedule counts are in `gte/s1-corrected-schedule.json`.

New fits acquire exclusive filesystem locks for both their checkpoint directory and their metric directory. Each checkpoint package contains its original run identity, finite fit declaration, legal parity input and the expected output computed by the live model. After publication, closeout reloads on the recorded device type, verifies those scores exactly, and publishes the canonical and metric receipts. A retry following interruption at this boundary uses the same weights and performs zero additional optimizer updates. A pre-journal checkpoint with an unfinished receipt requires finite replay and exact parameter equality before attachment to a fit. The CUDA interruption diagnostic and recovery receipt are in `gte/closeout-test/`.

The first persistent S1 recovery file contained 3,677,074,147 bytes at optimizer and scheduler update 256. A CPU load verified 156 model tensors, FP32 Adam moments for 156 tensors, 8,192 root exposures, and the CPU and CUDA generator states. The existing scheduling owner controls the live S1 process on this host. Fit-active GPU time can be derived from its recorded running intervals. The trainer's monotonic elapsed time includes time spent suspended.

## Input boundary and cost units

The frozen S1 database has 119,394 task fields matching the original TRAIN query and fixed public read goal. Among them, 76,211 contain delivered evidence and zero contain nonempty acquired-only evidence. The 120,005 observed source handles inside delivered records use request-local evidence aliases. Group identity controls offline weighting and bootstrap membership. Successful-path supervision uses the teacher's legal previous actions as state history.

An independent replay selected 18 roots across sources, prefix lengths and demonstrated states. The current runtime and frozen records produced identical GTE token IDs, object bindings, level indices and Host features. Adding unread-body and offline-answer canaries and renaming current menu IDs preserved the encodings. Moving delivered material into the acquired-only role changed all 12 nonempty examples. These checks cover implementation behavior. Natural performance on acquired-only states remains unmeasured.

The first 149 uniform comparison packs provided 470 terminal branches, including 255 MuSiQue branches linked to 85 distinct companion receipts. Each recorded immediate target agreed exactly with the Host incremental material tokens, including zero for HANDOFF. Future cost was the subsequent material change plus the Reader's actual input and output tokens. The maximum difference in the reconstructed immediate, future and summed proxy targets was zero tokens. The deployment report tracks actual Reader charges and measured controller cost separately. The full structured receipt is in `gte/legal-input-and-host-cost-review.json`.

A read-only CPU pass linked each of the 28,446 demonstration edges to its own TRAIN task and preceding SEARCH/READ history. All 9,589 resulting paths replayed to a feasible terminal packet containing a complete native annotated evidence set. This is evidence sufficiency for initialization. The separate outcome objective measures the actual frozen Reader. The receipt and per-source counts are in `gte/demonstration-native-review.json`.

At S1 update 256, a tensor-level comparison with the original reranker weights found that all 140 pretrained tensors had changed from the original FP32-cast values. All 140 had nonzero Adam second moments. These measurements extend the first-update gradient probe in `gte/s1/checkpoint-storage.json`.

A CPU-only handoff probe strictly loaded the step-256 model from persistent storage and scored one real warm comparison pack per source. Both objectives were finite, and net values matched per-action Host immediate cost plus the future-cost head exactly. This probe used the initialization scale of 2,048, with zero optimizer updates and zero additional Reader calls. Its receipt is `gte/s1/dq-pq-handoff-probe.json`.

After a host restart, the following aliases can restore missing S1 paths from persistent storage before invoking the same finite fit command. Run this during a scheduled fit phase.

```bash
mkdir -p "$G"
[[ -e "$G/base" ]] || ln -s "$R/models/gte-multilingual-reranker-base" "$G/base"
[[ -e "$G/evidence.sqlite" ]] || ln -s "$R/gte/evidence.sqlite" "$G/evidence.sqlite"
[[ -e "$G/s1" ]] || ln -s "$R/weights/s1" "$G/s1"
"$PYTHON" -m milai_lab.runners.pretrained_control_train --objective evidence --data "$G/evidence.sqlite" --output "$G/s1" --metrics "$R/gte/s1" --seed 11
```

The formal normalizer comes from `frozen-host-cost-scale.json`. The `--warm-packs` normalization option remains available to reproduce historical S0 diagnostics whose scale used measured feedback costs. The formal change affects the unit for both the immediate and future terms in the value readout. The branch targets still measure the same future token costs.

### Restoring the S1 input order

The original native evidence and historical replay writers overlapped and resumed. SQLite allocated physical row addresses in arrival order. The epoch sampler shuffles relative positions within each group, so an independently regenerated table can require an address translation even with the same seed and legal root population.

The frozen SQLite backup `gte/evidence.sqlite` preserves the exact running input. The lightweight `gte/frozen-native-root-order.jsonl.gz` separately records all 43,901 eligible native TRAIN tasks and the original training index traversal of the 119,394 labeled roots. The task key uses source, official split, native group, native ID, setting and official source row. In MuSiQue, each of 19,924 native pair IDs occurs twice. The original row ordinal distinguishes the two members. Each root adds its executed action prefix. The mapping is read exclusively by the offline sampler.

To regenerate this registration from the stored backup, start in MiLAi-Lab with the environment defined above.

```bash
"$PYTHON" -m milai_lab.runners.control_evidence_order freeze \
    --evidence "$R/gte/evidence.sqlite" --master /cra/milai-datasets/memory_control_v1_2 \
    --output "$R/gte/frozen-native-root-order.jsonl.gz"
```

For a separately rebuilt evidence DB, set `REBUILT_EVIDENCE` to that SQLite file and `REBUILT_MASTER` to the matching native task database or dataset directory. The alignment command checks every task and prefix, compares each normalized model input and supervision payload with the backup, then writes and reads back a compact independent address index. Omitting `--reference-evidence` limits verification to the natural-key populations and order. Source or data revisions with ambiguous, missing, extra or mismatched roots need their own registration.

```bash
"$PYTHON" -m milai_lab.runners.control_evidence_order align \
    --reference "$R/gte/frozen-native-root-order.jsonl.gz" \
    --evidence "$REBUILT_EVIDENCE" --master "$REBUILT_MASTER" \
    --reference-evidence "$R/gte/evidence.sqlite" --output "$R/gte/rebuilt-addresses.jsonl.gz"
"$PYTHON" -m milai_lab.runners.pretrained_control_train --objective evidence \
    --data "$REBUILT_EVIDENCE" --evidence-master "$REBUILT_MASTER" \
    --evidence-order-map "$R/gte/frozen-native-root-order.jsonl.gz" \
    --backbone "$R/models/gte-multilingual-reranker-base" \
    --output "$R/weights/s1-rebuild" --metrics "$R/gte/s1-rebuild" --seed 11
```

The optional fitter argument resolves the frozen order against the rebuilt DB before shuffling. Model inputs use their original legal features. The loader translates rebuilt local task and row numbers into the frozen addresses for sampling and exposure accounting. An existing fit continues to use its registered input and configuration.

The order file occupies 1,476,130 bytes. An independent 4,354,048-byte SQLite address table reversed all 119,394 physical addresses while referencing the original frozen payloads. The full native-key alignment, all normalized training payloads and all 119,394 seed-11 sampler positions matched. The isolated test exercises changed address assignments. A new raw-data regeneration can verify its own outputs with the same alignment command. The receipts are `gte/s1-native-task-key-inventory.json` and `gte/native-root-order-verification.json`.

### Shared fitting-seed prefixes

After seed 11 has closed its complete S1 fit and both initial shared 2k outcome fits, a spare fit-only GPU window can prepare the evidence initializations for optimization seeds 29 and 47. The standalone command runs them serially from the original generic backbone on the same frozen evidence population. The production scheduler reserves this window after both warm fits. The initializer itself only needs the completed S1 declaration, foundation model and frozen evidence. Each output is a newly fitted model. This command performs zero Reader evaluations and selects no method or checkpoint on TUNE or fresh groups.

```bash
"$PYTHON" tools/repeat_memory_control_v13_finalists.py --root "$R" evidence-only \
    --s1 "$R/weights/s1/checkpoint"
```

The full S4 repeat later reuses the same `weights/s1-f29` and `weights/s1-f47` checkpoints once their controller configuration, backbone, frozen recipe, complete exposure and matching metric receipts are verified. Frozen-feedback outcome refits and readouts follow the 24k development selection. Precomputing evidence initializations provides no evidence of seed stability until those comparisons run.
