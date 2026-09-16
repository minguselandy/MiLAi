"""Sequential research adapter over the pinned native LifelongAgentBench loop.

Run using the external lifelong venv. Native task reset, action parsing,
interaction, completion and metric calculation remain upstream implementations.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

from milai_lab.methods.evidence_utility_session import EvidenceUtilitySession
from milai_lab.methods.experience_revision import ExperienceRevisionSession
from milai_lab.methods.memrl_port import MemRLBank, MemRLConfig, MemRLSession, restore_rng
from milai_lab.methods.reasoning_bank import BankConfig, ExperienceBank, ReasoningBankSession
from reasoningbank_om import (
    NativeCapacityOMSession,
    NativeOMSession,
    om_method_version,
    om_session_class,
)
from reasoningbank_provider import EmbeddingProvider, NativeProvider
from reasoningbank_runtime_policy import (
    action_budget,
    actor_runtime_context,
    candidate_session_class,
    load_memory_policies,
)
from replay_v0213_cost import save, sha
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL

MEMORY_INTERFACE = """Auxiliary memory interface: if you need a memory operation, reply ONLY
<memory_request>{"kind":"revise","handles":["card:1"],"feedback_refs":["source:4"],
"reason":"specific mismatch"}</memory_request>
or <memory_request>{"kind":"read","ref":"source:2","start":0,"length":4000}</memory_request>.
For a task-local correction or selection change, use
<memory_request>{"kind":"state","working_note":"current interpretation",
"frame":{"selected_refs":[]}}</memory_request>. Omit unchanged fields; [] explicitly deselects.
This changes task-local judgment, not long-term experience, and needs no maintenance-model call.
After the receipt, resume the original native action format.
Memory requests do not execute SQL or bash.
"""


def atomic_save(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    save(temporary, value)
    temporary.replace(path)


def native_visible_trajectory(chat_history, role_dict) -> str:
    """Retain native initialization failures that have no visible conversation."""
    if chat_history.get_value_length() == 0:
        return ""
    return chat_history.get_value_str(role_dict, start_index=None, end_index=None)


def save_source_binding(root: Path, lab: Path, config: dict | None = None) -> None:
    paths = [
        "src/milai_lab/methods/reasoning_bank.py",
        "src/milai_lab/methods/experience_revision.py",
        "src/milai_lab/methods/experience_utility.py",
        "src/milai_lab/methods/evidence_utility_session.py",
        "src/milai_lab/methods/controlled_workspace.py",
        "src/milai_lab/methods/observational_memory.py",
        "src/milai_lab/methods/observational_capacity.py",
        "src/milai_lab/methods/memrl_port.py",
        "src/milai_lab/methods/memrl_text.py",
        "src/milai_lab/methods/MEMRL_LICENSE.txt",
        "configs/policies/memrl/provenance.json",
        "configs/policies/memrl/LICENSE.upstream",
        "tools/reasoningbank_provider.py",
        "tools/reasoningbank_tool_transport.py",
        "tools/reasoningbank_om.py",
        "tools/reasoningbank_runtime_policy.py",
        "tools/run_reasoningbank_lifelong.py",
        "tools/run_reasoningbank_travel.py",
    ]
    paths.extend(
        str(path.relative_to(lab))
        for directory in (
            "reasoning_bank",
            "om_sync",
            "experience_revision",
            "memrl",
            "native_travel",
        )
        for path in sorted((lab / "configs/policies" / directory).rglob("*.txt"))
    )
    observed = {path: sha((lab / path).read_bytes()) for path in paths}
    if config and config.get("source_lock"):
        lock_path = Path(config["source_lock"])
        if sha(lock_path.read_bytes()) != config["source_lock_sha256"]:
            raise ValueError("SOURCE_LOCK_CHANGED")
        if json.loads(lock_path.read_text())["sha256"] != observed:
            raise ValueError("FROZEN_IMPLEMENTATION_CHANGED")
    save(
        root / "source-binding.json",
        {
            "sha256": observed,
            "base_version": ReasoningBankSession.method_version,
            "candidate_version": candidate_session_class(config or {}).method_version,
        },
    )


def execute(config: dict) -> dict:
    root = Path(config["output_root"])
    root.mkdir(parents=True, exist_ok=False)
    save(root / "config.json", config)
    lab = Path(__file__).resolve().parents[1]
    save_source_binding(root, lab, config)
    checkout = Path(config["benchmark_root"]) / "LifelongAgentBench"
    sys.path.insert(0, str(checkout))
    from src.agents.instance.language_model_agent import LanguageModelAgent
    from src.callbacks.callback import CallbackArguments
    from src.callbacks.instance.previous_sample_utilization_callback import (
        PreviousSampleUtilizationCallback,
    )
    from src.factories.chat_history_item import ChatHistoryItemFactory
    from src.factories.chat_history_item.offline.construct import construct_offline
    from src.language_models import LanguageModel
    from src.tasks.instance.db_bench import task as db_module
    from src.tasks.instance.os_interaction import task as os_module
    from src.typings import (
        ChatHistoryItem,
        Role,
        SampleStatus,
        Session,
        SessionMetricCalculationPartial,
        TaskName,
    )

    split_path = Path(config["split_manifest"])
    if sha(split_path.read_bytes()) != config["split_sha256"]:
        raise ValueError("FROZEN_SPLIT_CHANGED")
    split = json.loads(split_path.read_text())
    allowed = {
        row["id"] for row in split["domains"][config["domain"]]["partitions"][config["split"]]
    }
    if not set(config["ids"]) <= allowed or len(set(config["ids"])) != len(config["ids"]):
        raise ValueError("TASKS_OUTSIDE_DECLARED_SPLIT")
    if config["model"] != MODEL:
        raise ValueError("ONLY_USER_SELECTED_SOLVER_ALLOWED")
    if config["method"] not in {
        "NATIVE_AGENT_OR_HISTORY",
        "OM_SYNC_PORT",
        "NATIVE_VERIFIED_HISTORY_REFERENCE",
        "REASONINGBANK_BASE_PORT",
        "MILAI_EXPERIENCE_REVISION",
        "MEMRL_LLB_PORT_v0.1",
    }:
        raise ValueError("METHOD_ADAPTER_NOT_AVAILABLE")
    provider = NativeProvider(
        root / "provider",
        max_tokens=config["max_tokens"],
        max_requests=config["max_requests"],
        deadline=time.monotonic() + config["wall_seconds"],
        request_timeout_seconds=config.get("request_timeout_seconds", 180),
    )
    provider.verify()
    embedding = EmbeddingProvider(root / "embedding", max_requests=config["max_requests"])
    policies = load_memory_policies(lab, config)
    bank_config = BankConfig(**config.get("bank_config", {}))
    memrl_config = MemRLConfig(**config.get("memrl_config", {}))
    is_memrl = config["method"] == MemRLSession.method_version
    scope = {
        key: config[key] for key in ("experiment", "method", "model", "protocol", "split", "stream")
    }
    scope.update(
        domain=config["domain"],
        method_version={
            "REASONINGBANK_BASE_PORT": ReasoningBankSession.method_version,
            "MILAI_EXPERIENCE_REVISION": candidate_session_class(config).method_version,
            "OM_SYNC_PORT": om_method_version(config),
        }.get(config["method"], config["method"]),
    )
    if is_memrl:
        scope["feedback_regime"] = config["feedback_regime"]
    contract = (
        MemRLSession.contract(memrl_config, policies)
        if is_memrl
        else ReasoningBankSession.contract(bank_config, policies)
    )
    bank_class = MemRLBank if is_memrl else ExperienceBank
    bank = bank_class(scope, contract)
    om_state = {}
    if config.get("bank_input"):
        saved = json.loads(Path(config["bank_input"]).read_text())
        if config["method"] == "OM_SYNC_PORT":
            om_state = saved
        else:
            source = bank_class.restore(saved, scope=saved["scope"], contract=contract)
            bank = source if source.scope == scope else source.fork(scope)
        save(root / "restored-bank.json", saved)
    evaluation_rng = None
    if is_memrl and config["protocol"] == "F":
        # Evaluation sampling advances in this run, while the seed bank stays byte-identical.
        evaluation_rng = (
            restore_rng(bank.rng_state)
            if bank.rng_state is not None
            else random.Random(memrl_config.seed)  # noqa: S311 -- scientific epsilon sampling
        )
    prompts = root / "native-prompts"
    verified = config["method"] == "NATIVE_VERIFIED_HISTORY_REFERENCE"
    suffix = "\n\nNow, I will give you the question that you need to solve."
    if verified:
        suffix = "\n\n{previous_sample_utilization_target_position}" + suffix
    construct_offline(str(prompts), suffix)
    factory = ChatHistoryItemFactory(str(prompts / f"{config['domain']}.json"))
    # Bind only deployment identity; native container operations remain unchanged.
    original_db_container = db_module.DBBenchContainer
    original_os_container = os_module.OSInteractionContainer
    db_module.DBBenchContainer = lambda: original_db_container(image=config["mysql_image"])
    os_module.OSInteractionContainer = lambda timeout: original_os_container(
        timeout, image=config["os_image"]
    )
    data_path = split_path.parent / "native" / f"{config['domain']}.json"
    memrl_queries = (
        {str(key): entry["instruction"] for key, entry in json.loads(data_path.read_text()).items()}
        if is_memrl
        else {}
    )
    task_class = db_module.DBBench if config["domain"] == "db_bench" else os_module.OSInteraction
    task_args = {
        "task_name": TaskName(config["domain"]),
        "chat_history_item_factory": factory,
        "data_file_path": str(data_path),
        "max_round": 3 if config["domain"] == "db_bench" else 5,
    }
    if config["domain"] == "os_interaction":
        task_args["command_execution_timeout"] = 20
    start = time.monotonic()
    task = task_class(**task_args)
    initialization_seconds = time.monotonic() - start
    memory = None
    task_id = ""

    class NativeLanguageModel(LanguageModel):
        def __init__(self):
            super().__init__({"user": "user", "agent": "assistant"})

        def _inference(self, batch_chat_history, inference_config_dict, system_prompt):
            results = []
            for history in batch_chat_history:
                native = list(self._convert_chat_history_to_message_list(history))
                auxiliary = []
                while True:
                    budget = action_budget(
                        task.max_round, task.current_round, unit="native interaction"
                    )
                    runtime_context = actor_runtime_context(lab, config, budget)
                    if isinstance(memory, ExperienceRevisionSession):
                        memory.set_action_budget(
                            budget if config.get("action_budget_context", False) else {}
                        )
                    if isinstance(memory, NativeOMSession):
                        memory.native_messages = [
                            {"role": "system", "content": system_prompt + "\n\n" + runtime_context},
                            *native,
                            *auxiliary,
                        ]
                    context = memory.memory_context() if memory else ""
                    if isinstance(memory, ExperienceRevisionSession) and context:
                        context += "\n\n" + MEMORY_INTERFACE
                    elif isinstance(memory, EvidenceUtilitySession):
                        context = (
                            "Optional source access: reply only <memory_request>"
                            '{"kind":"read","ref":"experience:catalog","start":0,'
                            '"length":4000}</memory_request> for available handles.'
                        )
                    elif isinstance(memory, NativeOMSession) and not isinstance(
                        memory, NativeCapacityOMSession
                    ):
                        context += (
                            '\nRead a source by replying ONLY <memory_request>{"kind":"read",'
                            '"ref":"event:0","start":0,"length":4000}</memory_request>.'
                        )
                    messages = [
                        {
                            "role": "system",
                            "content": system_prompt
                            + ("\n\n" + context if context else "")
                            + ("\n\n" + runtime_context if runtime_context else ""),
                        },
                        *native,
                        *auxiliary,
                    ]
                    if isinstance(memory, MemRLSession):
                        messages[0]["content"] = memory.actor_system(runtime_context)
                    if isinstance(memory, (EvidenceUtilitySession, MemRLSession)):
                        memory.prepare_actor_input(messages)
                    if isinstance(memory, NativeCapacityOMSession):
                        memory.check_actor_request(messages)
                    message = provider.generate_message(task_id, messages)
                    if isinstance(memory, (EvidenceUtilitySession, MemRLSession)):
                        memory.confirm_actor_input(provider.last_receipt)
                    elif isinstance(memory, ExperienceRevisionSession):
                        memory.confirm_actor_input()
                    if isinstance(memory, NativeOMSession):
                        memory.mark_seen()
                    content = message.get("content")
                    if not isinstance(content, str):
                        raise ValueError("NATIVE_TEXT_ACTOR_RETURNED_NO_TEXT")
                    match = re.fullmatch(
                        r"\s*<memory_request>(.*?)</memory_request>\s*", content, re.DOTALL
                    )
                    if not match or not isinstance(
                        memory, (ExperienceRevisionSession, NativeOMSession)
                    ):
                        results.append(ChatHistoryItem(role=Role.AGENT, content=content))
                        break
                    try:
                        request = json.loads(match[1])
                        if request["kind"] == "read":
                            read = (
                                memory.actor_read
                                if isinstance(memory, ExperienceRevisionSession)
                                else memory.read
                            )
                            receipt = read(
                                request["ref"], request.get("start", 0), request.get("length")
                            )
                        elif request["kind"] == "state" and isinstance(
                            memory, ExperienceRevisionSession
                        ):
                            receipt = memory.request_task_update(request)
                        elif request["kind"] == "revise" and isinstance(
                            memory, ExperienceRevisionSession
                        ):
                            receipt = memory.request_revision(request)
                        else:
                            raise ValueError("UNKNOWN_MEMORY_OPERATION")
                    except (ValueError, KeyError, TypeError) as error:
                        receipt = {"status": "REJECTED", "reason": str(error)}
                    receipt_text = "Memory receipt: " + json.dumps(receipt, ensure_ascii=False)
                    history.inject({"role": Role.AGENT, "content": content})
                    history.inject({"role": Role.USER, "content": receipt_text})
                    auxiliary.extend(
                        [
                            {"role": "assistant", "content": content},
                            {
                                "role": "user",
                                "content": receipt_text,
                            },
                        ]
                    )
            return results

    agent = LanguageModelAgent(NativeLanguageModel())
    replay = None
    if verified:
        replay = PreviousSampleUtilizationCallback(
            factory.construct(0).content, config["verified_history_count"]
        )
        replay.set_state_dir(str(root / "verified-history"))
        if config.get("verified_history_input"):
            replay.utilized_session_list = [
                Session.model_validate(value)
                for value in json.loads(Path(config["verified_history_input"]).read_text())
            ]
    sessions = []
    results = []
    try:
        for sample_id in config["ids"]:
            provider.begin_unit(config.get("unit_limits"))
            task_id = f"{config['domain']}:{sample_id}"
            session = Session(task_name=task.task_name, sample_index=sample_id)
            callback_args = CallbackArguments(session, task, agent, sessions)
            if replay:
                replay.on_session_create(callback_args)
            begin = time.monotonic()
            task.reset(session)
            task_root = root / f"task-{sample_id}"
            task_root.mkdir()
            memory = None
            if session.sample_status == SampleStatus.RUNNING and config["method"] not in {
                "NATIVE_AGENT_OR_HISTORY",
                "NATIVE_VERIFIED_HISTORY_REFERENCE",
            }:

                def emit(event, path=task_root):
                    append_event(path / "memory-events.jsonl", event)

                if config["method"] == "OM_SYNC_PORT":
                    memory = om_session_class(config)(
                        state=om_state,
                        scope=scope,
                        provider=provider,
                        task_id=task_id,
                        policy_root=lab / "configs/policies/om_sync",
                        emit=emit,
                        config=config.get("om_config"),
                        compact_provenance=config.get("om_compact_provenance", False),
                    )
                elif is_memrl:
                    memory = MemRLSession(
                        bank=bank,
                        config=memrl_config,
                        policies=policies,
                        generate=lambda call, tid=task_id: provider.memory_call(tid, call),
                        embed=lambda texts, tid=task_id: embedding.embed(tid, texts),
                        emit=emit,
                        evaluation_rng=evaluation_rng,
                    )
                else:
                    session_class = (
                        candidate_session_class(config)
                        if config["method"] == "MILAI_EXPERIENCE_REVISION"
                        else ReasoningBankSession
                    )
                    memory = session_class(
                        bank=bank,
                        config=bank_config,
                        policies=policies,
                        generate=lambda call, tid=task_id: provider.memory_call(tid, call),
                        embed=lambda texts, tid=task_id: embedding.embed(tid, texts),
                        emit=emit,
                        **(
                            {
                                "revision_application": config.get(
                                    "revision_application", "replace"
                                ),
                                "projection_mode": config.get("projection_mode", "selected"),
                                "post_task_revision": config.get("post_task_revision", False),
                                "action_budget": action_budget(
                                    task.max_round, task.current_round, unit="native interaction"
                                )
                                if config.get("action_budget_context", False)
                                else None,
                            }
                            if issubclass(session_class, ExperienceRevisionSession)
                            else {}
                        ),
                        **(
                            {"task_costs": lambda tid=task_id: provider.task_usage(tid)}
                            if session_class is EvidenceUtilitySession
                            else {}
                        ),
                    )
                memory.start(
                    task_id,
                    memrl_queries[str(sample_id)]
                    if is_memrl
                    else session.chat_history.get_item_deep_copy(-1).content,
                )
            while session.sample_status == SampleStatus.RUNNING:
                try:
                    agent.inference(session)
                except ValueError as error:
                    if str(error) not in {
                        "MODEL_CONTEXT_LIMIT",
                        "UNIT_GENERATION_LIMIT",
                        "UNIT_TOKEN_LIMIT",
                        "UNIT_TIME_LIMIT",
                        "OM_NATIVE_CONTEXT_CAPACITY",
                    }:
                        raise
                    session.sample_status = SampleStatus.AGENT_CONTEXT_LIMIT
                    session.finish_reason = str(error)
                    break
                if replay:
                    replay.on_agent_inference(callback_args)
                previous_length = session.chat_history.get_value_length()
                if memory:
                    memory.observe("actor", session.chat_history.get_item_deep_copy(-1).content)
                task.interact(session)
                if memory:
                    for index in range(previous_length, session.chat_history.get_value_length()):
                        memory.observe(
                            "tool", session.chat_history.get_item_deep_copy(index).content
                        )
            # Only native chat enters memory. Completion/evaluator fields stay separate.
            trajectory = native_visible_trajectory(session.chat_history, agent.get_role_dict())
            save(task_root / "visible-trajectory.json", {"text": trajectory})
            task.complete(session)
            if replay:
                replay.on_task_complete(callback_args)
                replay.on_state_save(callback_args)
            save(task_root / "native-session.json", session.model_dump(mode="json"))
            maintenance = None
            if memory:
                if isinstance(memory, (EvidenceUtilitySession, MemRLSession)):
                    # Release only a correctness bit after the terminal record is saved.
                    # Fixed TEST never publishes a result to the method.
                    allowed = config.get("feedback_regime", "H") == "R" and not (
                        config["split"] == "TEST" and config["protocol"] == "F"
                    )
                    if isinstance(memory, MemRLSession) and config["protocol"] == "F":
                        allowed = False
                    outcome = str(session.evaluation_record.outcome)
                    bit = (
                        (outcome == "correct")
                        if allowed and outcome in {"correct", "incorrect"}
                        else None
                    )
                    memory.seal_result(str(task_root / "native-session.json"), bit)
                maintenance = memory.finish(trajectory, commit=config["protocol"] != "F")
                atomic_save(root / "bank.json", memory.checkpoint())
            sessions.append(session)
            result = {
                "id": sample_id,
                "status": str(session.sample_status),
                "outcome": str(session.evaluation_record.outcome),
                "finish_reason": session.finish_reason,
                "seconds": time.monotonic() - begin,
                "maintenance": maintenance,
            }
            results.append(result)
            atomic_save(
                root / "progress.json",
                {"completed": results, "remaining": config["ids"][len(results) :]},
            )
            print(json.dumps(result, ensure_ascii=False), flush=True)
            state = accounting(read_events(provider.ledger))
            if state["pending"] or state["violations"]:
                raise ValueError("UNSETTLED_USAGE_STOPS_WORKER")
        metric = task.calculate_metric(
            [
                SessionMetricCalculationPartial(
                    sample_index=s.sample_index,
                    evaluation_record=s.evaluation_record,
                    sample_status=s.sample_status,
                )
                for s in sessions
            ]
        )
        save(root / "native-metrics.json", metric)
        result = {
            "status": "COMPLETED",
            "tasks": results,
            "initialization_seconds": initialization_seconds,
            "usage": accounting(read_events(provider.ledger)),
        }
        save(root / "result.json", result)
        return result
    except Exception as error:
        save(
            root / "failure.json",
            {
                "error_type": type(error).__name__,
                "reason": str(error),
                "completed": results,
                "usage": accounting(read_events(provider.ledger)),
            },
        )
        raise
    finally:
        task.release()
        provider.close()
        embedding.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    execute(json.loads(args.config.read_text()))


if __name__ == "__main__":
    main()
