# V13 confirmation inventory

The cold-evaluation release contains 6,065 tasks from 610 native groups. Selection used source IDs, registered roles and prior exposure records. The build issued zero Reader requests. The frozen method and sample size still need to be chosen on development data.

| Source | Available groups | Available tasks | Group size, min / median / max |
| --- | ---: | ---: | --- |
| MuSiQue-Full | 251 pairs | 502 | 2 / 2 / 2 |
| QASPER | 160 papers | 569 | 1 / 3 / 9 |
| PersonaMem-v2 | 199 personas | 4,994 | 10 / 25 / 42 |

The derived V1.2 roles and completed V12 evaluation roster supplied 295 initial MuSiQue candidates. All official Ans dev IDs also appear in Full dev. The first REF validation drew 300 questions from that split. Its 284 distinct IDs included 44 candidate pairs. A replay logged the IDs and reproduced the baseline return, and these 44 pairs were removed. All later REF validation and retrieval evaluation use a fixed 300-question TUNE roster. The public Full test archive has 2,459 pairs with no official response or answerability labels.

All 416 QASPER official test papers were reconciled with existing roots and historical allocations. The 256 previously reserved papers were excluded. The independent PersonaMem benchmark contains 200 personas. One had a root in V1. The 199 retained personas use the original dialogue-only 32K histories and native deterministic MCQ protocol. All 4,994 retained tasks have valid frozen options. Native V1.2 MuSiQue task, object and view IDs were preserved. The release is a separate SQLite database with its own run ID. It has no fitting states.

## Exposure evidence

The metadata scan covers seven project and experiment trees plus the archive catalog. It reads only matched native identifiers from known roster, registration, episode, manifest and receipt patterns, including compressed JSON. It recognizes numbered MuSiQue graph topologies, quoted paper IDs, source/group encodings and historical Persona benchmark ordinals. A metadata-only collision is treated as a conservative exclusion. The retained pool had zero further collisions.

A second check enumerated 53,145 stored packet members in 85 V1.1/V1.2 archives and 7,768 loose packet members, joined to the original 125 experiment rosters. These counts can include repeated configurations or storage copies. Completed/retained native packets had touched 426 MuSiQue, 128 QASPER and 291 Persona groups. The V1/V1.1/V1.2 branch outcome tables had covered 12,502 MuSiQue, 940 QASPER and 135 Persona groups. Both checks found zero overlaps with the derived pool.

The historical contextual experiment had listed PersonaMem benchmark_text in its formal configuration. The two interrupted formal run trees contained only PersonaMem-v1. The old contextual PersonaMem-v2 tree yielded 70 train_text and 59 val_text packet files and zero benchmark_text files. A filename scan of available project and experiment trees found zero PersonaMem-v2 benchmark split packet directories or benchmark_text question-ID paths. The exposure claim covers the checked local experiments, recorded native IDs and archived receipts. External users' runs and pretraining corpora are outside that scope.

Structural readback opened the versioned release through the normal `MemoryControlDataset` interface, prepared a live post-SEARCH menu for one task from each source, checked the two native MuSiQue members and validated frozen MCQ availability. All 569 QASPER questions had usable native reference annotations. The readback did not issue a Reader request or measure a task score.

## Rebuild and artifacts

From MiLAi-Lab run `scripts/qrag_fresh_confirmation.sh` with a new output directory under `/cra` supplied through `MILAI_FRESH_DIR`. The script expects the frozen group inventory, original REF exposure replay, fixed REF roster and source archives from this experiment. The builder uses the retained native normalizers and runtime, with checksum verification disabled.

The verified persistent evaluation database is `/cra/milai-experiments/v13-qrag/fresh-sources/native-confirm/memory_control.sqlite3`. It preserves the run ID and inventory of the staging build. The persistent capacity report and packet audit are in `/cra/milai-experiments/v13-qrag/fresh-sources/final-source-role-audit.json` and `final-packet-ledger-audit.json`. The original public corpora, frozen role map and REF exposure records needed for a rebuild are on persistent storage.

## Frozen comparison and power procedure

The V13 registration entry point is `tools/confirm_memory_control_v13.py`. Its `capacity` command has read the verified 6,065-task release. The capacity result is in `fresh-sources/maximum-confirmation-capacity.json`. Model selection and formal registration require completed deployment runs on the common natural 2,048-token TUNE population.

A selection JSON contains four fields. `families` maps each method-family label to a list of actual closed TUNE run paths. `final` identifies the method frozen on development evidence. `same_backbone` lists competing families with the same pretrained backbone. `practical` lists eligible practical baselines. Both lists may contain the same comparator. The final family requires the actual fit seeds 11, 29 and 47 on frozen data. A competing family may supply three matched seeds or one fixed deployed policy. State the development reason for the final choice in the selection file alongside these fields.

The registrar ranks each comparator pool by mean three-source native macro quality across the supplied fits. Its selection score uses the lower end of the unknown-quality range. Lexicographic family label resolves an exact tie. It reads the training receipt for each checkpoint and checks fit seeds and source-group disjointness. Each distinct deployed configuration gets one registered run even when both claims use it. The receipt records the Reader cap, the number of unique first calls and the budget for each comparison.

The default minimum meaningful same-backbone quality effect is one macro percentage point. This is a predeclared experiment choice. The power calculation samples grouped DEV residuals using source and size matches to fresh groups. Fit-seed variation and group resampling are retained. The design tests 25%, 50% and 100% of the specified cap, admitting only whole groups. It uses the first grid point with 80% projected power for both a one-point quality improvement and the engineering design alternative of zero quality loss with 20% true total savings. Otherwise it registers the largest tested capacity with its measured power limits. If a full cost meter is unavailable, planning reports the quality projection conditional on DEV token-record coverage and leaves joint engineering power unknown.

Two one-sided primary tests share the Holm family at 0.025. The first tests positive native macro quality gain against the chosen same-backbone control. The engineering test requires quality delta above −1 percentage point and total cost savings above 15% relative to the DEV-selected practical baseline. Its raw p-value is the maximum of the two component p-values. Point estimates, paired intervals and missing-quality bounds accompany the decisions. End-to-end latency, vLLM RUNNING duration, controller measurements and Reader tokens retain their own units and coverage. The primary savings ratio uses the sum of measured costs on the registered task workload, averaged over fit replicates. Group draws keep the original task count of each source as its cost weight. The result also includes absolute totals by source and an equal-source-weighted sensitivity. The primary total-cost test can use a complete measured local GPU-second or currency field with an explicit common measurement scope covering Reader, controller, retrieval and preprocessing. Currency measurements require a common currency code.

After final TUNE runs and the selection file exist, an invocation has the following form. The Reader cap and the three output directories are supplied by the parent experiment. The registration command does not contact the Reader.

```bash
root=/cra/milai-experiments/v13-qrag
export PYTHONPATH=src
python3 tools/confirm_memory_control_v13.py register \
    --selection "$selection" --reader-cap "$reader_cap" --cost-unit local_gpu_seconds \
    --data "$root/fresh-sources/native-confirm/memory_control.sqlite3" \
    --role-audit "$root/fresh-sources/final-source-role-audit.json" \
    --packet-audit "$root/fresh-sources/final-packet-ledger-audit.json" \
    --output "$registration"
```

Use the generated `population.json` and each numbered arm JSON with the normal V13 episode evaluator. The required run subdirectory for each arm appears in `registration.json`. The `readout` command accepts only closed registered runs, retains failed-call costs and reports unknown engineering evidence when the total meter is missing.

```bash
python3 tools/confirm_memory_control_v13.py readout \
    --registration "$registration" --runs "$confirm_runs" --output "$confirmation_result"
```

A later registration reconciles V13 confirmation packets already present under the experiment root. Extra historical run paths can be supplied with `--prior-run`. A prepared protected packet conservatively excludes its native group from a new selection. Continue a suspended confirmation with its existing frozen registration.
