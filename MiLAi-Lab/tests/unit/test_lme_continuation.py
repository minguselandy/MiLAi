"""Explicit continuation executes untouched positions and retains all earlier failure evidence."""

import json
from pathlib import Path

import httpx
import pytest
from test_lme_archives import files
from test_lme_evaluation import fixture, response
from test_lme_protocol import UPSTREAM

from milai_lab.harness.artifact_io import read_json, read_jsonl, write_json
from milai_lab.providers.chat_bridge import IncompleteChatResponse
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners.lme_archives import archive_lme_cases, restore_lme_case
from milai_lab.runners.lme_evaluation import predict_cohort, score_cohort


def test_separate_asset_root_keeps_failed_first_and_reuses_completed_source_imports(
    tmp_path, monkeypatch
):
    import base64

    from milai_lab.datasets.longmemeval_v2 import asset_path

    snapshot = fixture(tmp_path, monkeypatch)
    assets = tmp_path / "released-assets"
    (assets / "screens").mkdir(parents=True)
    (assets / "questions").mkdir()
    image_bytes = b"unchanged released image; mocked Reader does not decode it"
    (assets / "screens/0.png").write_bytes(image_bytes)
    (assets / "questions/2.png").write_bytes(image_bytes)
    (snapshot / "screens").symlink_to(assets / "screens", target_is_directory=True)
    (snapshot / "questions").symlink_to(assets / "questions", target_is_directory=True)
    trajectories = read_jsonl(snapshot / "trajectories.jsonl")
    trajectories[0]["states"][0]["screenshot"] = "screens/0.png"
    (snapshot / "trajectories.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in trajectories))
    questions = read_jsonl(snapshot / "questions.jsonl")
    questions[2]["image"] = "questions/2.png"
    (snapshot / "questions.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in questions))
    original, continued = tmp_path / "original", tmp_path / "continued"
    with pytest.raises(ValueError, match="inside its declared data root"):
        predict_cohort(tmp_path / "settings.json", snapshot, UPSTREAM, original,
            source_version="mechanical", capacity_factory=HostCapacity,
            transport=httpx.MockTransport(lambda _: pytest.fail("No Reader before image binding")))
    assert [row["status"] for row in read_json(original / "driver.json")["cases"]] == [
        "FAILED_RETRIEVING", "NOT_RUN", "NOT_RUN"]
    backend = original / "memory/pool-0000"
    # Reproduce the earlier artifact layout: the import report survived only inside the bank.
    (backend / "source-setup.json").unlink()
    setup = read_json(next(backend.glob("template/banks/*/retrieval-setup.json")))
    before = files(original)
    wires = []

    def reader(request):
        payload = json.loads(request.content)
        wires.append(payload)
        assert "Public request number 0" not in request.content.decode()
        assert "REFERENCE_ONLY_FOR_JUDGE" not in request.content.decode()
        if len(wires) == 2:
            images = [part["image_url"]["url"] for message in payload["messages"]
                      if isinstance(message["content"], list) for part in message["content"]
                      if part["type"] == "image_url"]
            # The original query image survives; Source images attach only when actually read.
            assert images
            assert all(base64.b64decode(image.split(",", 1)[1]) == image_bytes for image in images)
        return response("\\boxed{blue}")

    result = predict_cohort(tmp_path / "settings.json", snapshot, UPSTREAM, continued,
        source_version="mechanical", capacity_factory=HostCapacity,
        transport=httpx.MockTransport(reader), continue_from=original, asset_root=assets)
    assert result["asset_root"] == str(assets.resolve())
    assert result["status"] == "COMPLETED_WITH_RETAINED_FAILURES" and len(wires) == 2
    assert result["inherited_rows"] == [0]
    assert [row["status"] for row in result["cases"]] == [
        "FAILED_RETRIEVING", "COMPLETED", "COMPLETED"]
    recovered = continued / "memory/pool-0000"
    assert read_json(recovered / "source-setup.json") == setup
    assert read_json(recovered / "continuation-template.json")["asset_bindings_rebuilt"] is True
    media = list(read_json(recovered / "bound-images.json").values())
    assert len(media) == 1 and media[0]["original_event_id"] == "a/state-0"
    assert Path(media[0]["image"]) == assets / "screens/0.png"
    assert Path(media[0]["image"]).read_bytes() == image_bytes
    assert files(original) == before
    assert files(backend / "template") == files(recovered / "template")
    with pytest.raises(ValueError, match="inside its declared data root"):
        asset_path(assets, "../settings.json")


def test_prediction_continuation_keeps_failed_case_and_reuses_exact_original_haystack(
    tmp_path, monkeypatch
):
    snapshot = fixture(tmp_path, monkeypatch)
    original, continued = tmp_path / "original", tmp_path / "continued"
    wires = []

    def reader(request):
        wires.append(json.loads(request.content))
        return response("\\boxed{blue}", "length" if len(wires) == 2 else "stop")

    with pytest.raises(IncompleteChatResponse):
        predict_cohort(
            tmp_path / "settings.json",
            snapshot,
            UPSTREAM,
            original,
            source_version="mechanical",
            capacity_factory=HostCapacity,
            transport=httpx.MockTransport(reader),
        )
    previous = files(original)
    # The continuation consumes the original private input snapshot, not changed source files.
    (snapshot / "questions.jsonl").write_text("CHANGED_AFTER_FIRST_ATTEMPT\n")
    (snapshot / "trajectories.jsonl").write_text("CHANGED_AFTER_FIRST_ATTEMPT\n")

    def tail(request):
        text = request.content.decode()
        assert "Public request number 2" in text and "Public request number 0" not in text
        assert "REFERENCE_ONLY_FOR_JUDGE" not in text and "OFFLINE_ID_" not in text
        wires.append(json.loads(request.content))
        return response("\\boxed{blue}")

    result = predict_cohort(
        tmp_path / "settings.json",
        snapshot,
        tmp_path / "unused-upstream",
        continued,
        source_version="mechanical",
        capacity_factory=HostCapacity,
        transport=httpx.MockTransport(tail),
        continue_from=original,
    )
    assert result["status"] == "COMPLETED_WITH_RETAINED_FAILURES" and len(wires) == 3
    assert result["inherited_rows"] == [0, 1]
    assert [c["status"] for c in result["cases"]] == ["COMPLETED", "FAILED_READING", "COMPLETED"]
    assert result["cases"][0] == read_json(original / "driver.json")["cases"][0]
    assert result["cases"][2]["runtime"].endswith("pool-0000/cases/0001")
    assert files(original) == previous
    assert files(original / "memory/pool-0000/template") == files(
        continued / "memory/pool-0000/template"
    )
    scores = tmp_path / "scores"
    score_cohort(
        continued,
        scores,
        source_version="mechanical",
        transport=httpx.MockTransport(
            lambda _: pytest.fail("Failed Reader is not regenerated or sent to a Judge")
        ),
    )
    metrics = read_json(scores / "metrics.json")
    assert metrics["planned"] == 3 and metrics["scored"] == 2 and metrics["unscored"] == 1
    assert metrics["native_complete_cohort_metrics"] is None
    assert read_json(tmp_path / "isolated-mechanical-budget.json")["generation_requests"] == 3
    actual = {c["row"]: Path(c["runtime"]) for c in result["cases"]}
    originals = {i: files(p) for i, p in actual.items()}
    old_driver = (original / "driver.json").read_bytes()
    archived = archive_lme_cases(continued, scores, source_version="mechanical")
    assert archived["archived_cases"] == 3
    assert (original / "driver.json").read_bytes() == old_driver
    for i, path in actual.items():
        assert not path.exists()
        assert restore_lme_case(continued, i) == path
        assert files(path) == originals[i]


def test_scoring_continuation_preserves_failed_judge_and_never_regenerates_readers(
    tmp_path, monkeypatch
):
    snapshot = fixture(tmp_path, monkeypatch)
    predictions = tmp_path / "predictions"
    predict_cohort(
        tmp_path / "settings.json",
        snapshot,
        UPSTREAM,
        predictions,
        source_version="mechanical",
        capacity_factory=HostCapacity,
        transport=httpx.MockTransport(lambda _: response("\\boxed{blue}")),
    )
    old_scores, continued = tmp_path / "old-scores", tmp_path / "new-scores"
    with pytest.raises(IncompleteChatResponse):
        score_cohort(
            predictions,
            old_scores,
            source_version="mechanical",
            transport=httpx.MockTransport(lambda _: response("incomplete judge", "length")),
        )
    before = files(old_scores)
    retained = [
        (predictions / f"predictions/{i:04d}/prediction.json").read_bytes() for i in range(3)
    ]
    result = score_cohort(
        predictions,
        continued,
        source_version="mechanical",
        continue_from=old_scores,
        transport=httpx.MockTransport(
            lambda _: pytest.fail("Only the untouched exact rule remains")
        ),
    )
    assert [r["status"] for r in result["cases"]] == ["COMPLETED", "FAILED_SCORING", "COMPLETED"]
    assert result["inherited_rows"] == [0, 1]
    assert [r["score"] for r in result["cases"]] == [1, None, 1]
    assert files(old_scores) == before
    assert retained == [
        (predictions / f"predictions/{i:04d}/prediction.json").read_bytes() for i in range(3)
    ]
    assert read_json(tmp_path / "isolated-mechanical-budget.json")["generation_requests"] == 4


def test_changed_condition_cannot_be_a_continuation_and_no_attempt_is_retried(
    tmp_path, monkeypatch
):
    snapshot = fixture(tmp_path, monkeypatch)
    original = tmp_path / "original"
    calls = []

    def reader(request):
        calls.append(request)
        return response("\\boxed{blue}", "length")

    with pytest.raises(IncompleteChatResponse):
        predict_cohort(
            tmp_path / "settings.json",
            snapshot,
            UPSTREAM,
            original,
            source_version="mechanical",
            capacity_factory=HostCapacity,
            transport=httpx.MockTransport(reader),
        )
    config = read_json(tmp_path / "settings.json")
    config["memory_control"]["policy"] = "rules"
    changed = tmp_path / "changed.json"
    write_json(changed, config)
    with pytest.raises(ValueError, match="unchanged inputs/method"):
        predict_cohort(
            changed,
            snapshot,
            UPSTREAM,
            tmp_path / "changed-run",
            source_version="mechanical",
            continue_from=original,
        )
    assert len(calls) == 1 and not (tmp_path / "changed-run").exists()


def test_multiple_continuations_find_ancestor_template_and_keep_original_pool_indices(
    tmp_path,
    monkeypatch,
):
    snapshot = fixture(tmp_path, monkeypatch)
    roots = [tmp_path / f"attempt-{i}" for i in range(3)]
    wires = []

    def reader(request):
        wires.append(request.content.decode())
        return response("\\boxed{blue}", "length" if len(wires) <= 2 else "stop")

    for i, root in enumerate(roots):
        kwargs = {
            "source_version": "mechanical",
            "capacity_factory": HostCapacity,
            "transport": httpx.MockTransport(reader),
            "continue_from": roots[i - 1] if i else None,
        }
        if i < 2:
            with pytest.raises(IncompleteChatResponse):
                predict_cohort(tmp_path / "settings.json", snapshot, UPSTREAM, root, **kwargs)
        else:
            result = predict_cohort(tmp_path / "settings.json", snapshot, UPSTREAM, root, **kwargs)
    assert len(wires) == 3
    assert [c["status"] for c in result["cases"]] == [
        "FAILED_READING",
        "FAILED_READING",
        "COMPLETED",
    ]
    assert result["cases"][2]["runtime"].endswith("pool-0000/cases/0001")
    assert read_json(roots[-1] / "memory/pool-0000/continuation-template.json")[
        "original_backend"
    ] == str((roots[0] / "memory/pool-0000").resolve())
    with pytest.raises(ValueError, match="closed failed"):
        predict_cohort(
            tmp_path / "settings.json",
            snapshot,
            UPSTREAM,
            tmp_path / "no-retry",
            source_version="mechanical",
            continue_from=roots[-1],
        )
    assert not (tmp_path / "no-retry").exists()


def test_retrieval_failure_is_retained_while_untouched_questions_can_execute(tmp_path, monkeypatch):
    from milai_lab.memory.service import MemoryService

    snapshot = fixture(tmp_path, monkeypatch)
    original_search = MemoryService.search_sources
    attempts = []

    def first_search_fails(self, *args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("synthetic first retrieval failure")
        return original_search(self, *args, **kwargs)

    monkeypatch.setattr(MemoryService, "search_sources", first_search_fails)
    original, continued = tmp_path / "original", tmp_path / "continued"
    wires = []

    def reader(request):
        wires.append(request.content.decode())
        return response("\\boxed{blue}")

    args = (tmp_path / "settings.json", snapshot, UPSTREAM)
    kwargs = {
        "source_version": "mechanical",
        "capacity_factory": HostCapacity,
        "transport": httpx.MockTransport(reader),
    }
    with pytest.raises(RuntimeError, match="First failed retrieval"):
        predict_cohort(*args, original, **kwargs)
    previous = files(original)
    result = predict_cohort(*args, continued, **kwargs, continue_from=original)
    assert [c["status"] for c in result["cases"]] == ["FAILED_RETRIEVING", "COMPLETED", "COMPLETED"]
    assert len(wires) == 2 and all("Public request number 0" not in wire for wire in wires)
    assert files(original) == previous
