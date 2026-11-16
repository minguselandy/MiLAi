# Open Jev-compatible Laya for MiLAi Impact

**Laya** is an Apache-2.0, open-weights, non-autoregressive System-One
decision model. This is **not** TypeSafe's proprietary Jev model. This
integration replaces only MiLAi's root/preserve Impact decision; the existing
Writer creates facts and the existing MemoryService commits them.

Upstream: https://github.com/NandhaKishorM/laya
Weights: https://huggingface.co/convaiinnovations/laya

## Deploy the official Laya HTTP service

Run on a host with Docker Engine/Compose v2 and internet. Upstream's CPU
quickstart suggests at least 8 GB RAM and 10 GB free disk. The first boot
downloads the selected model checkpoint into a named model cache volume.

From the MiLAi repo root:

    bash MiLAi-Lab/deploy/laya/bootstrap.sh
    curl -fsS http://127.0.0.1:8000/health

For NVIDIA hosts with NVIDIA Container Toolkit installed:

    LAYA_DEVICE=cuda bash MiLAi-Lab/deploy/laya/bootstrap.sh

To freeze upstream source code for reproducibility:

    LAYA_SOURCE_REF=<reviewed-upstream-commit-sha> bash MiLAi-Lab/deploy/laya/bootstrap.sh

The script clones upstream outside MiLAi and uses its official
compose.yaml + compose.http.yaml (+ compose.cuda.yaml for CUDA). It prints
the exact source commit. The default checkpoint is multilingual for Chinese
and English Impact tasks; the default checkpoint revision is
LAYA_REVISION=reviewed. The HTTP port binds **127.0.0.1** by default.
Set LAYA_API_KEY and put TLS in front before enabling remote access.
GET /health should report the **actual device**, not just the CUDA
preference; Laya may fall back to CPU.

For offline Hugging Face environments, upstream supplies
compose.modelscope.yaml. Follow their ModelScope and volume instructions
rather than assuming the default downloader works.

## Smoke test with the real model

    cd MiLAi-Lab
    PYTHONPATH=src python tools/laya_impact_smoke.py

Environment: LAYA_BASE_URL (default http://127.0.0.1:8000),
LAYA_IMPACT_MODEL (default multilingual), and LAYA_API_KEY if required.

The smoke returns the model's Impact selection and provider usage, but
**does not create or modify memory**. A selected label is not a validated
semantic update.

## Opt-in MiLAi integration

The new adapter uses existing Impact request messages and returns the
unchanged schema: roots and preserve. No second review model or writer.

    from milai_lab.methods.laya_impact import LayaImpactClient
    from milai_lab.methods.edit_maintenance import maintain_event

    laya = LayaImpactClient(
        base_url="http://127.0.0.1:8000",
        model="multilingual",
        on_receipt=lambda entry: print(entry["usage"]),
    )
    result = maintain_event(
        method, delivery, session=session, request_id=request_id, date=date,
        recipe="single_pass", model_call=laya.wrap(existing_model_call),
        commit=commit,
    )

The adapter redirects impact and impact:<child> stages and leaves Writer,
Extractor and all other calls with the original provider. Empty roots
do **not** mean "skip writing" (a fully new fact needs no old target).
HTTP failures are raised, never silently turned into no-change results.

Benchmark and ordinary Host now accept an explicit `laya_impact` setting:

```json
{
  "laya_impact": {
    "base_url": "http://127.0.0.1:7870",
    "model": "milai-impact-ce-v1",
    "max_len": 2048,
    "head_max_len": 256,
    "timeout_seconds": 180.0
  }
}
```

Use that CE alias only after a real checkpoint is complete and registered with
`LAYA_EXTRA_MODELS`. The current pilot initially serves `milai-impact-base-v1`.
For a serialized HTTP-owner Host, add the same five-field configuration to the
existing `http_ownership_domain.clients` list. The shared adapter registers the
actual typed endpoint, reserves the original computation budget, records the raw
response before semantic validation, and shares Host call admission. No separate
ledger is created. Non-autoregressive work uses the original generation budget
bucket and is also itemized under `compute.laya_impact` (requests, questions,
input tokens, wall time). Missing usage stays unknown. A saved response is reused;
an unresolved request is not repeated.

Laya is a finite-context encoder. Training and serving use the same
`impact_payload`; a training audit measures every complete state+question+options
sequence, and serving rejects a response reporting truncated input. Each question
has its own encoded sequence even when several questions share one HTTP request.
Full-candidate Writer delivery remains the first-stage control.

## Source-reviewed training and actual serving

See [execution record](../../docs/MILAI_JEV_EXECUTION_20261016.md) for current results,
limitations, original artifact paths and the still-incomplete requirement audit.
These tools run from `MiLAi-Lab`; Laya/Torch are optional training-environment
dependencies, not new mandatory dependencies for ordinary MiLAi runtime imports.

```bash
PYTHONPATH=src python tools/prepare_laya_impact.py \
  data/fixtures/milai-laya-impact-reviews-v1.jsonl \
  /absolute/path/to/strong-v1/run/candidate /new/path/to/data
PYTHONPATH=src python tools/train_laya_impact.py \
  /new/path/to/data /absolute/path/to/laya-multilingual-base /new/path/to/run \
  --budget /absolute/path/to/existing/budget.json --device cpu
```

`--audit-only` writes full sequence lengths without optimizing parameters. The
training command keeps the original encoder and decision head, uses soft-CE and
external family splits, and disables upstream random item-level calibration.
The small pilot is uncalibrated. Check the actual effective items, optimizer
updates, losses and root/preserve errors before interpreting an accuracy gain.

After the checkpoint exists, register its real absolute directory:

```bash
export LAYA_EXTRA_MODELS='{"milai-impact-ce-v1":"/absolute/path/to/completed/checkpoint"}'
export LAYA_MODELS=milai-impact-ce-v1
export LAYA_DEFAULT_MODEL=milai-impact-ce-v1
export LAYA_PRELOAD=1 LAYA_HOST=127.0.0.1 LAYA_DEVICE=cpu
laya-serve
```

The checkpoint contains `model.safetensors`, `encoder/`, `tokenizer/`, and
`rl_agent_config.json`. The HTTP response's generic `model` field is not sufficient
checkpoint identity; save the actual service registration and loaded-alias health
alongside checkpoint configuration. `tools/evaluate_laya_impact.py` uses the metered
adapter to evaluate one explicitly named split and writes per-role/event metrics.
It does not execute Writer or Reader. Local files are used without SHA verification.

## Offline tests (no checkpoint download)

    cd MiLAi-Lab
    PYTHONPATH=src pytest -q tests/test_laya_impact.py

Tests use HTTPX MockTransport to check mapping, child-stage routing,
empty roots, unknown choices and HTTP failure propagation. They verify
the bridge contract, **not** inference accuracy or deployment success.

## Research controls

Compare D0 no independent Impact, D1 generative Impact, D2 Laya Impact
with the same full Writer, then D3 the same Laya selection with a
separately implemented local Writer projection. **D3 is not implemented
by this branch**. MiLAi's experimental semantic_delta_v1/v2 path
currently disables dependency_updates; do not enable both by removing
its compatibility check without a specific delta-scoped compiler.

The current execution has downloaded and served the multilingual checkpoint on
CPU. Full fine-tuning and the D0–D4 state/Writer comparisons have separate statuses
in the execution record; the offline tests below are not model-quality evidence.
