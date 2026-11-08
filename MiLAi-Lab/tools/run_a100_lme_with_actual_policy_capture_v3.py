"""Run native LME predictions with actual retrieval-state capture and a paired first-call replay.

This experiment adapter changes observation/copy wiring only. Native public input,
retrieval execution, complete-input guard, image binding, Reader and scoring remain
in the frozen runtime. It never dispatches a subsequent method or retries an outcome.
"""
from __future__ import annotations

import argparse
import copy
import json
import site
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def preserve_replay_recording():
    """Keep the existing verifier and recorder when functional replay installs both."""
    from milai_lab.methods.intent_retrieval import IntentRetrievalMemory
    from milai_lab.runners.frozen_retrieval import RetrievalRecorder

    original = IntentRetrievalMemory.__setattr__

    def assign(memory, name, value):
        if name == "retrieval_observer":
            current = memory.__dict__.get(name)
            if isinstance(current, RetrievalRecorder) and callable(value) and not isinstance(value, RetrievalRecorder):
                assert value.__name__ == "verify_replay"
                verifier, recorder = value, current

                def verify_and_record(event):
                    verifier(event)
                    recorder(event)

                value = verify_and_record
        original(memory, name, value)

    IntentRetrievalMemory.__setattr__ = assign
    try:
        yield
    finally:
        IntentRetrievalMemory.__setattr__ = original


@contextmanager
def archive_control_snapshots():
    """Keep each complete before in the existing verified common-base byte format."""
    from milai_lab.harness.artifact_io import write_json
    from milai_lab.harness.case_archive import archive_case
    from milai_lab.runners import frozen_retrieval

    original = frozen_retrieval.copy_call_root

    def archived(root, bank_root, destination):
        base = root.parents[1] / "template"
        assert base.is_dir()
        original(root, bank_root, destination)
        details = archive_case(destination, destination.with_name("before.tar.gz"), base)
        write_json(destination.with_name("before-archive.json"), {
            "status": "COMPLETE_BEFORE_ARCHIVED_EVERY_RECONSTRUCTED_BYTE_EQUAL",
            "snapshot": str(destination), **details,
            "original_snapshot_reconstructible": True,
            "Source_state_head_menu_or_bindings_shortened": False,
            "no_sha_validation": True, "ledger_recorded": False})

    frozen_retrieval.copy_call_root = archived
    try:
        yield
    finally:
        frozen_retrieval.copy_call_root = original


@contextmanager
def capture_original_calls(output: Path):
    from milai_lab.harness.artifact_io import read_json
    from milai_lab.runners import lme_v2

    original = lme_v2.message

    def captured(root, **kwargs):
        row = read_json(output / "driver.json")["active_row"]
        assert kwargs["given_retrieval_request"] == {"query": kwargs["content"]}
        assert "retrieval_snapshots" not in kwargs and "retrieval_step_snapshots" not in kwargs
        return original(root, **kwargs,
            retrieval_snapshots=output / "actual-retrieval-captures" / f"{row:04d}",
            retrieval_step_snapshots=True)

    lme_v2.message = captured
    try:
        yield
    finally:
        lme_v2.message = original


@contextmanager
def replay_original_calls(output: Path, baseline: Path, config: Path):
    from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
    from milai_lab.harness.artifact_io import entrypoint_settings, read_json, write_json
    from milai_lab.harness.case_archive import restore_case
    from milai_lab.memory.service import MemoryService
    from milai_lab.runners import lme_evaluation
    from milai_lab.runners.functional import _bank_reference, frozen, message
    from milai_lab.runners.multimodal_evidence import delivered_image_context

    parent = read_json(baseline / "driver.json")
    assert parent["schema"] == "lme_prediction_cohort_v2"
    assert parent["status"] in {"COMPLETED", "COMPLETED_WITH_RETAINED_FAILURES", "FAILED"}
    assert parent["planned_positions"] == len(parent["cases"]) == 451
    assert all(case["status"] in {"COMPLETED", "FAILED_PREPARING_INPUT",
        "FAILED_RETRIEVING", "FAILED_READING"} for case in parent["cases"])
    baseline_config = read_json(baseline / "configuration.json")
    current_config = read_json(config)
    before = entrypoint_settings(baseline_config, "functional")
    after = entrypoint_settings(current_config, "functional")
    assert before["memory_control"]["policy"] == "fixed"
    assert after["memory_control"]["policy"] == "laya"
    original_control = before["memory_control"]
    adjusted = copy.deepcopy(after)
    adjusted["memory_control"].update({key: original_control[key] for key in ("policy", "checkpoint")})
    assert adjusted == before
    # functional.message consumes the entire policy config rather than a patch.
    policy = copy.deepcopy(after["memory_control"])
    original_class = lme_evaluation.LmeMemoryBackend

    class PairedBackend(original_class):
        def query(self, query, query_image=None):
            assert not self.failed
            local_index = self.queries
            self.queries += 1
            row = read_json(output / "driver.json")["active_row"]
            base_case = parent["cases"][row]
            base_owner = Path(base_case["owner_predictions"])
            candidates = list((base_owner / "actual-retrieval-captures" / f"{row:04d}").glob("*/call.json"))
            call_path, = candidates
            captured = call_path.parent
            call = read_json(call_path)
            assert call["schema"] == "frozen_retrieval_call_v2"
            assert call["status"] in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}
            assert call["public_message"]["content"] == query
            assert call["public_message"]["given_retrieval_request"] == {"query": query}
            assert not call["host_request_generated"]
            assert "control_checkpoint" not in call
            case_root = self.output / "cases" / f"{local_index:04d}"
            report = {"status": "RUNNING", "row": row, "query": query, "query_image": query_image,
                "automatic_retry": False, "baseline_capture": str(captured),
                "host_request_regenerated": False,
                "query_isolation": "Literal baseline pre-retrieval Store/Saver clone; no baseline answer enters.",
                "policy_override": policy, "source_version": self.source_version,
                "reader_called": False}
            started, cpu = time.perf_counter(), time.process_time()
            try:
                # Use the existing complete closed-template copier, retaining all history/image
                # metadata for native continuation and post-scoring case archives.
                if not self.template.exists():
                    self.reuse_closed_template(Path(base_case["runtime"]).parents[1])
                saved_before = read_json(captured / "before-archive.json")
                assert saved_before["status"] == "COMPLETE_BEFORE_ARCHIVED_EVERY_RECONSTRUCTED_BYTE_EQUAL"
                restore_case(Path(saved_before["archive"]), Path(saved_before["base"]), case_root)
                result = message(case_root, bank=call["bank"], **call["public_message"],
                    replay_retrieval=call, control_policy_override=policy, control_models=self.models,
                    source_search_cache=self.source_search_cache, resume=True,
                    retrieval_snapshots=output / "actual-retrieval-captures" / f"{row:04d}",
                    retrieval_step_snapshots=True)
                assert result["frozen_initial_observation_and_actions_equal"]
                report["first_observation_and_all_legal_bindings_equal"] = True
                if result["status"] != "COMPLETED":
                    raise RuntimeError("First failed retrieval retained: " + str(result.get("error")))
                # Keep the original native delivered-image projection, including every text/error field.
                settings = frozen(case_root)
                bank_id = _bank_reference(case_root, settings["run_id"], self.bank, self.owner)
                directory = case_root / "banks" / bank_id
                media = self.media
                with SqliteStore.from_conn_string(str(directory / "memory.sqlite")) as store:
                    service = MemoryService(store,
                        ("functional", settings["run_id"], self.bank, self.owner), self.owner,
                        directory / "memory.lock", functional_contract="functional_v1",
                        memory_profile=settings["config"]["memory_profile"],
                        memory_ranking=settings["config"]["memory_ranking"])
                    context = delivered_image_context(service, result["retrieval_result"], media)
                write_json(case_root / "memory-context.json", context)
                report.update(status="COMPLETED", images=sum(c["type"] == "image" for c in context))
                return context
            except BaseException as error:
                self.failed = True
                report.update(status="FAILED", error_type=type(error).__name__, error=str(error))
                raise
            finally:
                report.update(cpu_seconds_nested=time.process_time()-cpu,
                    wall_seconds=time.perf_counter()-started, ledger_recorded=False)
                write_json(case_root / "query.json", report)

    lme_evaluation.LmeMemoryBackend = PairedBackend
    try:
        yield
    finally:
        lme_evaluation.LmeMemoryBackend = original_class


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--continue-unattempted", type=Path)
    parser.add_argument("--replay-baseline", type=Path)
    parser.add_argument("--site-packages", action="append", type=Path, default=[])
    args = parser.parse_args()
    for path in args.site_packages:
        site.addsitedir(str(path))
    from milai_lab.harness.artifact_io import entrypoint_settings, read_json
    from milai_lab.runners.lme_evaluation import predict_cohort

    settings = entrypoint_settings(read_json(args.config), "functional")
    assert settings["memory_control"]["max_len"] == 16384
    assert settings["memory_control"]["head_max_len"] == 2048
    assert settings["memory_control"]["source_observation_tokens"] == 2048
    assert settings["memory_control"]["source_range_tokens"] == 256
    assert settings["ordinary_material_tokens"] == 2048
    assert settings["max_calls_per_message"] == 24
    assert settings["memory_control"]["internal_views"] is False
    if args.replay_baseline is None:
        assert settings["memory_control"]["policy"] == "fixed"
        observe = capture_original_calls(args.output)
    else:
        parent = read_json(args.replay_baseline / "driver.json")
        assert parent["source_version"] == args.source_version
        for source, saved in [
            (args.snapshot / "questions.jsonl", "questions.jsonl"),
            (args.snapshot / "trajectories.jsonl", "trajectories.jsonl"),
            (args.snapshot / "haystacks/lme_v2_small.json", "haystacks.json")]:
            assert source.read_bytes() == (args.replay_baseline / "offline-input" / saved).read_bytes()
        observe = replay_original_calls(args.output, args.replay_baseline, args.config)
    with archive_control_snapshots(), preserve_replay_recording(), observe:
        result = predict_cohort(args.config, args.snapshot, args.upstream, args.output,
            source_version=args.source_version, continue_from=args.continue_unattempted)
    print(json.dumps({"status": result["status"], "positions": result["planned_positions"],
        "actual_retrieval_capture": True, "paired_baseline": str(args.replay_baseline),
        "automatic_retry": False}), flush=True)


if __name__ == "__main__":
    main()
