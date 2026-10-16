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

**Important integration boundary:** This is an opt-in method_call wrapper.
Default Benchmark/Host configuration does **not yet select Laya
automatically**. laya.receipts and on_receipt expose model, selected
probabilities, actual server-reported usage and latency, but they are
**not automatically booked in the old model provider's ledger**. To
publish an accurate experiment, connect on_receipt to the existing run
accounting and charge local GPU/CPU costs, not just output tokens. For
a real full maintenance run, instantiate the client at the runner/Host
model-call boundary and call wrap exactly once.

Laya is a finite-context encoder, not an arbitrary-long-history reader.
The bridge requests max_len=4096; that is an input cap, not evidence that
the entire MiLAi packet fits or is preserved without truncation. First
evaluate short packets that fit both providers; for long packets build
and compare an explicit context-selection method. Do not silently
truncate disjoint scopes or independent supports.

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

The current work environment does not provide Docker, a GPU or external
weight downloads, so this branch includes an executable deployment
recipe and locally contract-tested integration, **not** a live model
server or end-to-end model-quality result.
