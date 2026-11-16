# Historical reader checkpoints

# Full-pool CE live handoff (2026-10-16)

Goal ACTIVE/incomplete; this turn made progress through completed matched training,
real finite read trajectories and a newly verified recall bottleneck. No subagents/SHA.
Only live task at checkpoint: ce-c20-v1 PID94497/exec59654, frozen sourcecc8f8af6,
CUDA_VISIBLE_DEVICES2,3, native8192/head512,4epochs/602train/223dev,152plannedupdates.
At snapshot39updates/epoch2; original zero12/223,epoch1 79/223 with121wrong exhausted
stops. Inspect actual process/run.json; don't restart from a missing observer handle.
Artifacts under artifacts/jev-reader/ce-c20-v1, stderr/stdout in runtime. No Reader queue.

C8 ordinary-ce-v1 CLOSED/exit0,exec87911,sourcef62635d2,120updates and saved fp16
encoder+CLS checkpoint. Final83/164:complement26/78,exhausted57/73,sufficient0/13.
1459.237wall/1867.384CPU;15648train encoding rows17873160tokens;8395dev10084795tokens.
C8 Laya CE final73/164 and ordinary83 both poor stopping; constant exhausted73.
Raw curves/checkpoints/failures and original budget retained. C8 actual selection
chain CLOSED/exit0 exec24015 source43f5a302: all3models46cases,fixed2/adaptive4;
reference proof complete of24positive: base1/2,CE2/1,ordinary2/0. BM25k2/k4/k8=2/3/10.
Both trained checkpoints reloaded:46initial-state argmax46/46match each; not all203.
Import failure before first selection (rank_bm25 missing in CUDAenv) was0model calls;
fixed by moving offline preparation import into prepare(), original stderr retained.

CRITICAL: C8 contains full annotated support in only10of24 answerable dev cases.
Review section5 prioritizes fixing recall. C8 Reader protocol414calls is PREPARED/0HTTP,
not an admitted net-benefit trial; do not dispatch it from stale plans. Preserve it.
C20 reuses same sampled families/source rows, all20original paragraphs, no gold insertion.
Data artifacts/jev-reader/data/decisions-c20-v1:602train/223dev/206calib/212test states.
C20 lengths max3791/4960/4333/4232,all complete at8192/512. C8 membership/exposure unchanged;
2dev/1test sampled families preexposed, exclude test overlap from future blind result.

NEXT: inspect C20 terminal/curves and costs; adapt selector/prepare/ordinary capacity
and pool limits for20 (current run_bounded_reader_selection still8/4096/384!), complete
same-input C20 controls/logits baseline and real common Reader QA. Current C8 figures
are not QA. Ordinary full-state independent action encoding is a matched scalar
baseline, not all optimized rerankers. Avoid claiming Jev advantage from its higher cost.
Native MuSiQue scorer fetched under artifacts/jev-reader/musique-official; original
paired metric needs22complete pairs,2orphan positives retained in overall24 denominator.
Reader driver/tests ready; use official CLI, not dynamic imports. No unconfirmed replay.
Full unexposed LME,MemOps/MEME,W/B calibration/trajectory requirements still pending.

Only7862authorizedcontainer is stopped. bge-m3 PID47436 and bge-reranker52982 unchanged;
othermodels/GPU0/1 untouched. Keep models/env/caches under /cra/memory/mx_memory.
Restore7862only after GPUtraining/selection ends; don't release protected BGE allocations.
15directchecks/Ruff/package+tools boundaries pass. No fullrepo/remoteCI/publication.
Reports docs/MILAI_JEV_READ_DECISIONS_20261016.md; 3new manifests C8selection,ordinary,C20.

# Reader CE terminal (2026-10-16)

Previous goal turn was progress: data/split/finite-policy implementation and real
training. ce-gpu-v2 now CLOSED/exit0, PID4093998 gone, exec37838 completed. Source8c6cb000,
120updates, full encoder+head native checkpoint. Epoch0/1/2/3/4 dev15/82/79/67/73 of164;
constant exhaustion73. Final complement26/78, exhausted46/73, sufficient1/13. No net
benefit or adequate stop-learning claim. Training348.325wall/463.399CPU;1868training
sequences2311796tokens,1015dev1314820tokens, all in original ledger. Save fp16, in-memory
float32 curves; full checkpoint reload dev not yet checked. Original failedV1 preserved.
Ordinary matched CLS cross-encoder tools added; its native shape/gradient/reload check
passed, full training not yet dispatched at this checkpoint. It uses own base encoder
copy; never modifies BGE or any protected service. Keep full original benchmark scope.

# Live reader CE handoff (2026-10-16)

Goal ACTIVE/incomplete. ce-gpu-v2 is live at this checkpoint: PID4093998,
exec37838, frozen method source8c6cb000. Inspect /proc and run.json before any
new work; never restart just because the exec handle is missing. Four epochs,
467 labelled train prefixes from64families/122events;203dev prefixes,164labelled.
CUDA_VISIBLE_DEVICES=2,3, full encoder+head soft-CE; no calibration/test inference.
Artifacts: artifacts/jev-reader/ce-gpu-v2; stdout/stderr in ../runtime.
Original ce-gpu-v1 FAILED/exit1 after29updates: compiled ModernBERT with DP last
3-row batch hit FX/Dynamo error. Sourceb57c29ef and all first results preserved.
reference_compile=False fixes native eager path; actual two-GPU batch4->3
forward/backward probe passed with encoder/head gradients, original ledger charged.
V2 GPU initial dev15/164 matches CPU; do not treat later majority STOP as success.
Constant-stop baselines are now reported. Full downstream QA/net benefit unproven.
CPU base-dev-prefix-v1 CLOSED203forwards/262964tokens/390.706wall/1436.094CPU,
15/164accepted;39masked. Its compute is in original ledger; V2 ledger closes in finally.
CUDAenv/CPython/caches all under /cra/memory/mx_memory; task-created348KiBTriton
root cache moved to .cache/triton-first-gpu-run afterV1terminated. Explicit Triton,
Inductor and CUDA cache vars now in runtime/env.sh; /root/.triton absent atcheck.
Do not touch protected BGE services. 7862 remains normally stopped for authorized
training. Restore only after checking live training allocation and next work.
Next: verify V2 terminal/checkpoint, inspect all per-stratum curves and costs;
then ordinary supervised reranker/logits control, fixed-k versus STOP/complement
ablation, calibrated and unseen LME/MemOps/MEME requirements. No completion claim.
Preview-exposure manifest excludes one sampled test family from future blind test;
two dev families are exposed diagnostics. Detailed report and preparation manifest
in docs/MILAI_JEV_READ_DECISIONS_20261016.md and data/manifests/.

# User GPU allocation (2026-10-16)

User now explicitly authorizes releasing ONLY milai-unified-v8-v9-native-host-r2
(7862, physical GPUs2/3) for training. This supersedes older no-GPU-change rules
only for that container. bge-m3(7861), bge-reranker(7961), GPU0/1 Qwen and all other
models must remain untouched. 7862 was idle, stopped normally, original container
retained; restore with docker start milai-unified-v8-v9-native-host-r2.
Before/after and restore command: artifacts/jev-reader/gpu-allocation-v1/.
CUDA environment/cache under /cra/memory/mx_memory, no requirement hash validation.
Training explicitly CUDA_VISIBLE_DEVICES=2,3,75% own-memory cap per GPU; BGE retains
its existing allocations. Check live jobs before restoring 7862 to avoid contention.

# Current bounded reader worktree (2026-10-16)

Goal ACTIVE/incomplete. This independent jev-read-decisions-20261016 worktree
continues the same bottleneck review from20bc06d6. The sibling bottleneck worktree
has concurrent source/report edits; preserve them and do not overwrite its files.
This branch owns bounded_evidence.py, prepare_musique_decisions.py,
evaluate_bounded_laya.py and their new direct tests. No subagents or SHA checks.
User requires downloads/models/environments under /cra/memory/mx_memory, not /root.
artifacts/jev-reader/runtime/env.sh sets HF/Torch/pip/uv/XDG/temp paths explicitly.
New train-env uses a locally copied CPython and existing /cra packages; original
training environments, model checkpoints, failed runs and GPU services stay intact.
MuSiQue mirror download COMPLETED39876rows/476696984bytes, no checksum. Official
archive equivalence unverified. Family split896connected components; discarded
cross-split target exposures. Shared non-target backgrounds are NOT independent.
Frozen decisions-v1: train64families/124rows/556prefixes; dev24/46/203;
calibration24/42/186; test24/44/195. Labels mask unprovable answerable retrieval
gaps, retain reference complements and two STOP meanings; literal equivalent
supports share target mass. Prefixes do not create new independent events.
Full native tokenizer audit4096/384: no truncation/invalid targets; max2137tokens.
No Reader QA, CE benefit, calibrated stopping or downstream net-cost claim yet.
Real CPU inference must use original continuous budget.json below for compute,
record actual sequence rows/tokens/time; no synthetic HTTP or generated-token counts.
Inspect each live process/terminal before new work; old process snapshots are history.

