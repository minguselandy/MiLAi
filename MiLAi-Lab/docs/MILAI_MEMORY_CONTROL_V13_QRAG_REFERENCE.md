# Q-RAG Reference on one A100 40GB

The reference uses the standalone official MuSiQue-Ans recipe and its ground-truth support-fact feedback. Both state and action towers initialize from intfloat/multilingual-e5-large. The upstream loader opened 19,938 train and 2,417 dev questions from the V1 raw MuSiQue archive. For the retained experiment, its validation input is a frozen 300-question subset of official dev selected solely from V13 TUNE native IDs. No collection calls go to a Reader.

| Setting | Reference | Q-RAG-MiLAi specification |
| --- | --- | --- |
| Observation and actions | Full document chunks, upstream chunk index | Legal previews, R2/R3 and HANDOFF |
| Reward and termination | First completion of the facts earns the configured reward, training can continue through four steps | Terminal Reader once on normal handoff or hard limit, native Full pair scorer |
| Optimization | Upstream parallel rollout, twin Q components, TD(λ) with γ=0.99, λ=0.6 and target EMA=0.02 | Native terminal quality with γ=1, explicit costs |
| Evaluation | Ground-truth dev return curve, official retrieval F1 and support-set coverage | Paired native-group quality and total deployment cost |

The upstream source version is `42358d78ac491843763b90677f07237471c97086`. The base encoder version is `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`. The script selects versions without SHA verification. Reference train and dev exposure belong to the official benchmark. Its weights are kept separate from project-trained methods. [Official implementation](https://github.com/griver/Q-RAG/tree/42358d78ac491843763b90677f07237471c97086)

## Local resource adaptations

The patch under `configs/memory_control_v13` applies to the dedicated reference checkout. The upstream training loop, official config composition, TD targets, reward, action selection and target updates are retained. The patch restricts package imports to the MuSiQue GT path. This avoids loading vLLM into the training process. The selected environment uses PyTorch 2.7.0+cu126 and Transformers 4.52.3.

Only encoder forward matmuls run under CUDA BF16 autocast. Outputs return to FP32 before pool/value calculations, and parameter and AdamW moment storage uses FP32. Eager execution avoids compiled-graph storage. The official 12-transition rollout and accumulation of eight are preserved. Each critic backward processes two transitions. Sum reduction over the original rollout matches the upstream sample weights even for a final partial microbatch. The official seed is 42. The schedule covers 10,000 updates with a validation every 100 updates and an added final validation. The curve counts actual critic transitions separately from optimizer updates. The bootstrap value after the final transition provides its next-state target.

Actor checkpoints preserve exact policy-state and online-action tower tensors for greedy retrieval. Best and final actors are saved under the experiment asset root. Live optimizer and target weights participate in training. The compact actor does not support an exact training restart. A fresh run label starts a separate optimization. An interrupted run should retain its original logs and partial curve.

## Validation exposure

All 2,417 official Ans dev question IDs also occur in Full dev. The first run used the official random validation draws. We stopped it after 32 rollouts and four optimizer updates, before the second validation. The initial 300 observations had mean GT completion return 0.29. Replaying the initial upstream iteration with identical seeds and ID logging reproduced the observed mean and the independently reconstructed set of 284 distinct question IDs. Forty-four of the 295 candidate Full pairs were exposed in this validation. Its run log, cost and actor are retained. Its partial training is excluded from the retained curve.

The retained run starts again from the general E5 weights. Every validation pass and the final support-fact retrieval evaluation use the same 300 TUNE native IDs. These IDs come from the host's role inventory via seeded selection. Both actual curve measurements and final retrieval metrics therefore apply to this fixed development subset. The official training data, GT behavior, TD and 10,000-update schedule are preserved. The role inventory and readback of the first validation must be kept with the experiment.

## Reproduction

Start in the MiLAi-Lab directory. The local experiment used the system CUDA Python environment with an isolated target for the smaller packages. The following installation assumes torch, transformers, accelerate, sentencepiece, protobuf, NumPy and their transitive dependencies are already present.

```bash
export PYTHONPATH=/data/milai-experiments/v13-ref-python
python3 -m pip install --target "$PYTHONPATH" --no-deps --no-cache-dir \
    hydra-core==1.3.2 omegaconf==2.3.0 antlr4-python3-runtime==4.9.3 \
    rotary-embedding-torch==0.8.9 einops==0.8.1 sortedcontainers==2.4.0 \
    tensorboard==2.20.0 tensorboard-data-server==0.7.2 markdown==3.8.2 werkzeug==3.1.3
export REF_GPU=2 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
# Requires the V13 native-group role inventory to have been generated.
scripts/qrag_reference.sh prepare
scripts/qrag_reference.sh train official-musique-tune300-seed42
```

`MILAI_V13_ROOT` defaults to `/cra/milai-experiments/v13-qrag`. `MILAI_REF_ASSETS` defaults to its `staging/ref` directory. On this host the first run uses a temporary in-memory mount below `/cra` for the base weights, extracted data and checkpoints. A persistent copy of the base weights was verified at `/cra/milai-experiments/v13-qrag/models/multilingual-e5-large`. New downloads target this path through `MILAI_REF_BASE`. Small run records and source stay on the persistent volume. The compact best and final actors occupy about 9 GB combined. Provide persistent capacity to retain those model artifacts across a restart.

After the run finishes, select the matching generated `config.yaml` in the run directory. The evaluator applies the same backbone precision to the recorded zero-update actor, the strictly best GT-return actor and the final actor. Each uses the same four-retrieval maximum and completion stop. Per-question records include retrieved and reference support indices, episode return and native metrics.

```bash
run=/cra/milai-experiments/v13-qrag/ref/official-musique-tune300-seed42
trained=$(dirname "$(find "$run" -name config.yaml -print -quit)")
scripts/qrag_reference.sh evaluate "$trained"
```

TensorBoard records and `reference-curve.jsonl` are under the generated run's `tb_logs` directory. `optimizer-progress.jsonl` contains early weight changes, observed optimizer moment dtype, memory and timings. Success requires the full curve and terminal retrieval evaluation. The actual run status and evaluation files determine the reported result.

The interrupted pre-cutover actor at its first validation can be restored exactly from the public E5 weights and the durable local delta. A tensor-by-tensor reconstruction checked dtype and values for all 790 tensors. The delta occupies 12,682,821 bytes and the expanded actor occupies 4,483,665,967 bytes. The first run made four optimizer updates after that checkpoint. Those live optimizer steps appear in the cost but do not appear in the actor.

```bash
root=/cra/milai-experiments/v13-qrag
python3 scripts/qrag_ref_actor_delta.py restore \
    --actor "$root/staging/ref/checkpoints/official-musique-ans-seed42/model_best.pt" \
    --base "$root/models/multilingual-e5-large/model.safetensors" \
    --delta "$root/ref/official-musique-ans-seed42/initial-actor-delta.pt"
```

The original cutover occupied one GPU process for 195.5 seconds. The separate exposure replay spans approximately 118 seconds between log creation and final write, measured to one-second precision. These costs are separate from the retained fit. A completed retained fit reports its one-GPU process wall time, retrieval job hours for each of the three actors, all validation points and a learning-curve PNG. A GPU process duration includes initialization and checkpoint I/O.

At the first post-update validation, 100 optimizer updates had increased mean GT return from 0.286667 to 0.340000 on the same 300 TUNE questions. The backbone probe changed by 3.97e-5 and peak allocated GPU memory reached 29,108,853,760 bytes. The corresponding exact FP32 retrieval actor is durable at `/cra/milai-experiments/v13-qrag/ref/actor-archives/first-trained-best.zip`. A CPU-only 4 MiB blockwise XOR against the original E5 weights and DEFLATE reduced its storage from 4,483,665,967 to 1,844,242,617 bytes in 171.0 seconds. Readback verified 780 XOR tensors, eight literal tensors and two unchanged tensors against the actual actor. The measured archive ratio is specific to this checkpoint.

To restore this trained actor, pass its ZIP path to `scripts/qrag_ref_actor_delta.py restore` with the same persistent base and an unused output `--actor` path. This checkpoint represents one early point of the 10,000-update schedule.

The initial Reader phase parked the live REF and S1 processes with their allocations resident. The 100-update validation precedes that interval. `initial-schedule.json` supplies the REF PID, start and end of the hold. The terminal resource summary distinguishes full one-GPU process wall time from wall time excluding observed parking. The running training log's elapsed time includes this hold.

## Restart and staging recovery

The retained run is `ref/official-musique-tune300-seed42/Nov25_00-48-23_QRAG_musique` below the persistent experiment root. `retained-actors/index.json` points to the last atomically published and losslessly verified retrieval actors. The observer reads the existing training process and its published files. It holds an immutable hardlink during encoding, verifies reconstructed tensor bytes and replaces the persistent index only after the checkpoint receipt is durable. It retains the latest best, the final last when available, and the separate update-100 measurement. An interrupted encode leaves the previous indexed version available.

`retained-actors/live-resource.json` records the most recent observed process/CPU wall time, scheduling interval, optimizer evidence and durable actor step. The original run had logged 140 optimizer updates when parked; its best inference actor was at update 100. The live training state includes the optimizer moments, EMA target towers, rollout state, random generators and pending accumulated gradients. The original process exposes evaluation actors through its file interface. Its optimizer state cannot be restored exactly from those files. After a host loss during fitting, reproducing the full official schedule requires a separate run from the original E5 initialization. Preserve the interrupted run's elapsed resources and partial curve.

When just the temporary filesystem disappears, the private ext4 underlay already contains the current run's checkpoint destination and a link to the durable base. The observer also reinstates a missing output directory while its original process handle is live. A loss coincident with a checkpoint write may leave only the last verified mirror. The original trainer and scheduling owner were kept alive throughout the underlay preparation.

A private mount namespace replaced staging with an empty 480 MiB tmpfs for a recovery drill. The original MuSiQue archive and persistent frozen cohort restored 19,938 training and 300 development questions without a model download. The live actor and the actor rebuilt from the durable update-100 archive produced identical CPU logits for all 20 candidates of a TUNE example and selected the same greedy action. The drill used no GPU or Reader and wrote no expanded checkpoint file. Three independent fresh cold preparations and the complete 610-group capacity also reopened with the original staging tree inaccessible.

The same empty-staging test reconstructed three closed 150-task evaluation summaries from their durable packets. Request counts, input/output tokens, timing and native results matched the original reports. A snapshot of the open warm lane contained 709 receipts and 699 actual requests. Its receipt prefix and the project cost readback are saved under `ref/reboot-drill`. A provider dispatch interrupted before its terminal receipt stays unknown. Normal episode recovery preserves a stored scored packet and marks a previously dispatching packet interrupted without sending it again.

After a lost staging mount use the normal `prepare` command. For a completed schedule use `evaluate` on its saved upstream run directory. It checks all 101 validation positions, reconstructs any missing selected evaluation actor from the matching durable archive, resumes the official retrieval evaluator by native ID and exports both terminal actors. A torn final JSONL write is preserved before the incomplete row is re-evaluated. Launch counts and settled evaluation durations distinguish known costs from missing post-crash timing. If only a live observation or final curve survives, fit time is reported as a lower bound. A settlement attempt at 100 optimizer updates correctly rejected the incomplete curve. The positive closure and missing-file recovery paths were exercised with test fixtures.

An existing live run can reattach its single file observer with `scripts/qrag_ref_watch.py --pid PID --run UPSTREAM_RUN_DIR --root EXPERIMENT_ROOT --base PUBLIC_MODEL_SAFETENSORS`. The observer binds the process start tick and verifies its run arguments. The status of the actual curve remains authoritative after the reattachment.

The current terminal owner uses an independent process session with its logs on persistent storage. Its `terminal-owner.json` binds the trainer PID and Linux start tick; it waits on a pidfd. When the original process exits, it settles the wall interval, requires the full validation curve, then invokes the registered retrieval evaluation with a file lock. It does not replace the training process. The transient session survives the launching shell's exit. Host-reboot recovery uses the persistent files and explicit evaluation entry point above.

## Terminal actor comparison

The pre-cutover zero-update actor is a recorded copy from the seed-42 E5 initialization. Its source delta restored all 790 actor tensors. The actual embedding and encoder parameters used in each tower's forward pass, 389 tensors per tower, matched the general public E5 weights directly. The terminal evaluator repeats this functional check after loading. `ref/zero-update-actor-source.json` records its origin and measured tensor counts. A new independent reproduction without this archive uses a freshly seeded native E5 initialization and verifies the same forward parameters. The resulting origin remains explicit.

The three official evaluator passes have separate directories, native prediction files, timing ledgers and restart markers under the upstream run's `retrieval/initial`, `retrieval/best` and `retrieval/final`. All retrieved support sets are scored using the official support F1 and its EM convention of covering all reference supports. Each measured GT return must agree with that convention under the registered completion feedback. The reports compare each actor's mean against the corresponding logged training validation checkpoint. The paired file joins all three actors by original MuSiQue question ID and retains the three score differences per metric. Paired bootstrap intervals resample the same 300 native questions with 5,000 common draws. Best was selected on this development roster.

The report records whether the selected best improves both retrieval metrics, whether the final actor regresses on both, and whether a sustained gain is established on this roster. The latter requires all final five logged GT returns above initialization, agreement of all three native GT readbacks and positive paired lower endpoints for final F1 and coverage EM. Mixed directions and disagreements remain visible separately. The criterion was set after 300 updates and before later checkpoints or terminal evaluation. No additional Reader training labels are consumed.

The evaluation-only patch `qrag_ref_terminal_actors.patch` loads registered actor transports into the native evaluator; all three passes run upstream `evaluate_episode` and `calc_fact_f1_em`. The pinned checkout plus both patches reconstructed the evaluator, training loop and PQN source exactly. A single-question CPU transport diagnostic loaded the actual zero-update actor through this entry point on the TUNE split. It consumed 89.73 seconds of process wall, zero GPU-seconds and zero Reader calls. This check does not contribute any responses to the three terminal evaluations.

## Failure diagnosis

The terminal result links the measured data inventory and legal support reachability, actual optimizer changes and moment dtype, upstream PQN return calculation and prior TD boundary/gradient checks, and the actual termination witness for each actor. The fixed dev roster contains 170 two-support, 83 three-support and 47 four-support questions. Every support set fits the four available retrievals. Uniform distinct actions have an expected completion rate of 0.01892 on this roster. Native output also records the fraction of first reads hitting support and the distribution of chosen root Q scores on successes and failures.

If the final GT return and the mean of the last five GT checkpoints are both below initialization, the three terminal evaluator processes run an additional TRAIN-only probe. The seed and 32 matched before-state pairs are fixed across actors. Each actual three-read prefix admits a last support and a distractor. Executing either fourth action in the official environment yields the terminal reward. Since the native not-done mask is zero, this is the exact TD target irrespective of bootstrap value. The probe compares component predictions, the original twin-MSE residuals, positive-versus-zero action ordering, and autograd on the first query projection and last output normalization in each tower. We disable dropout for this controlled comparison and do not step any optimizer. The published per-edge derivatives precede rollout averaging and gradient accumulation. The enriched TRAIN pairs measure terminal value discrimination. Historical nonterminal EMA targets and past stochastic gradients remain unavailable from inference checkpoints. The final report itemizes probe GPU time inside each evaluation job's total time.

A one-pair CPU check ran this path for the actual zero-update and update-100 actors on a shared native TRAIN prefix. True terminal targets were approximately 0.75 and 0. On this pair both scaled Q heads initially exceeded both targets. Their absolute errors fell at update 100 while the online preference for the last support over the distractor increased. The recorded per-parameter gradients and losses are under `ref/reboot-drill/terminal-gradient-implementation`. This test cannot identify the cause of later policy deterioration.

To refresh the in-progress plot in the saved upstream run directory, execute the following from MiLAi-Lab. It reads complete validation rows, shows the latest measured update against the 10,000-update schedule, and writes `reference-learning-curve-progress.png`. It runs without a model or Reader.

```bash
python3 scripts/qrag_ref_result.py --run "$trained" --plot-progress
```
