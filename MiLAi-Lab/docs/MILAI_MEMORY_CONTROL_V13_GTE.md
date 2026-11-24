# V13 GTE interaction controller

The fitted controller uses the 306M GTE sequence-classification checkpoint and its pretrained pooler. A single joint encoding covers both READ levels for one object. Four value heads consume that representation, the original relevance logit, the legal level and the action-aligned Host features. The trainable controller has 306,375,945 parameters. The Reader is external to the optimizer.

The text serializer reserves capacity for task, remaining budget, acquired-only evidence, delivered evidence, action history, the menu and the current object preview. It reads the online observation and action table. A controller decision maximizes the four-head mean of quality minus the calibrated penalty times predicted future cost plus known immediate cost, with the penalty applied to their sum. Cost units in training are incremental material tokens and actual Reader input/output tokens. The first uniform TRAIN feedback package fixes their normalizing median. Deployment efficiency is evaluated using the measured resource categories.

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

The fitter accepts one or more pack directories for the same frozen continuation target. Both DQ and PQ-U take the same inputs and optimization seed. PQ adds a Huber loss on observed within-root quality differences. Each root normalizes the contributions of its measured actions and pairs before its source and native-group weighting. The two objectives share four group-bootstrap heads. Evaluation uses their mean. The warm scale and source package are recorded in the receipt. Later rounds initialize from their previous checkpoint. For a 6k common-policy checkpoint, include both the shared warm and arm-specific completed packs. For a new continuation policy, pass its newly collected packs.

```bash
for objective in direct paired; do
    "$PYTHON" -m milai_lab.runners.pretrained_control_train \
        --objective "$objective" --data "$R/warm-11/packs" \
        --warm-packs "$R/warm-11/packs" --initialize "$G/s1/checkpoint" \
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
