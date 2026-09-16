"""Complete native MemoryArena groups with scoped research memory adapters."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

from milai_lab.methods.evidence_utility_session import EvidenceUtilitySession
from milai_lab.methods.experience_revision import ExperienceRevisionSession
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
from run_reasoningbank_lifelong import atomic_save, save_source_binding
from v02_local_provider import accounting, append_event, read_events
from v0213_provider import MODEL


def memory_tools(candidate):
    result = [
        {
            "type": "function",
            "function": {
                "name": "memory_read",
                "description": "Read a published source or original plan by character range.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "start": {"type": "integer"},
                        "length": {"type": "integer"},
                    },
                    "required": ["ref"],
                },
            },
        }
    ]
    if candidate:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": "memory_revise",
                    "description": "Revise seen experience based on actual tool feedback.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "handles": {"type": "array", "items": {"type": "string"}},
                            "feedback_refs": {"type": "array", "items": {"type": "string"}},
                            "reason": {"type": "string"},
                        },
                        "required": ["handles", "feedback_refs", "reason"],
                    },
                },
            }
        )
        result.append(
            {
                "type": "function",
                "function": {
                    "name": "memory_state",
                    "description": "Correct task-local interpretation or experience selection.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "working_note": {"type": "string"},
                            "frame": {
                                "type": "object",
                                "properties": {
                                    "question": {"type": "string"},
                                    "intent": {"type": "string"},
                                    "selected_refs": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                        },
                    },
                },
            }
        )
    return result


def execute(config):
    lab = Path(__file__).resolve().parents[1]
    root = Path(config["output_root"])
    root.mkdir(parents=True, exist_ok=False)
    save(root / "config.json", config)
    save_source_binding(root, lab, config)
    checkout = Path(config["benchmark_root"]) / "MemoryArena"
    sys.path.insert(0, str(checkout))
    from agent.travel_planner import TravelPlannerAgent
    from env.env_systems import travel_env
    from env.env_systems.travel_planner_env import eval as evaluator
    from env.env_systems.travel_planner_env.clients.base_client import ModelResponse, ToolCall
    from env.env_systems.travel_planner_env.clients.openai_client import OpenAIClient
    from env.env_systems.travel_planner_env.combination import parse_plan_text
    from env.env_systems.travel_planner_env.data_loader import _convert_row
    from run_travel import format_person_plan, parse_all_plans

    sp = Path(config["split_manifest"])
    if sha(sp.read_bytes()) != config["split_sha256"] or config["model"] != MODEL:
        raise ValueError("SPLIT_OR_MODEL_BINDING_CHANGED")
    split = json.loads(sp.read_text())
    allowed = {row["id"] for row in split["domains"]["travel"]["partitions"][config["split"]]}
    if not set(config["ids"]) <= allowed or len(set(config["ids"])) != len(config["ids"]):
        raise ValueError("TRAVEL_GROUPS_OUTSIDE_DECLARED_SPLIT")
    # The original converter and evaluator receive pinned data. Answers are kept
    # only inside the evaluator/environment and never serialized to memory.
    rows = [_convert_row(row) for row in json.loads((sp.parent / "native/travel.json").read_text())]
    selected_rows = [row for row in rows if str(row["id"]) in config["ids"]]
    travel_env.load_travel_data = lambda: selected_rows
    evaluator.load_travel_data = lambda: selected_rows
    env = travel_env.TravelPlannerEnvironment({"judgement_mode": "none"})
    provider = NativeProvider(
        root / "provider",
        max_tokens=config["max_tokens"],
        max_requests=config["max_requests"],
        deadline=time.monotonic() + config["wall_seconds"],
        tool_transport=config.get("tool_transport", "native_auto"),
        request_timeout_seconds=config.get("request_timeout_seconds", 180),
    )
    provider.verify()
    embedding = EmbeddingProvider(root / "embedding", max_requests=config["max_requests"])
    policies = load_memory_policies(lab, config)
    bank_config = BankConfig(**config.get("bank_config", {}))
    scope = {k: config[k] for k in ("experiment", "method", "model", "protocol", "split", "stream")}
    scope.update(
        domain="travel",
        method_version={
            "REASONINGBANK_BASE_PORT": ReasoningBankSession.method_version,
            "MILAI_EXPERIENCE_REVISION": candidate_session_class(config).method_version,
            "OM_SYNC_PORT": om_method_version(config),
        }.get(config["method"], config["method"]),
    )
    contract = ReasoningBankSession.contract(bank_config, policies)
    seed = ExperienceBank(scope, contract)
    om_seed = {}
    if config.get("bank_input"):
        saved = json.loads(Path(config["bank_input"]).read_text())
        if config["method"] == "OM_SYNC_PORT":
            om_seed = saved
        else:
            seed = ExperienceBank.restore(saved, scope=saved["scope"], contract=contract).fork(
                scope
            )
    memory = None
    task_id = ""
    cursor = 0
    legal_trajectory = []
    tool_names = {}

    class Client(OpenAIClient):
        def __init__(self):
            # Keep native formatting methods without creating an unmetered SDK client.
            self.model_name = MODEL
            self.native_steps = 0

        def capture(self, messages):
            nonlocal cursor
            for message in messages[cursor:]:
                if message["role"] != "system":
                    legal_trajectory.append(copy.deepcopy(message))
                    if memory:
                        business_tool = message["role"] == "tool" and not tool_names.get(
                            message.get("tool_call_id"), ""
                        ).startswith("memory_")
                        memory.observe(
                            "tool" if business_tool else "message",
                            json.dumps(message, ensure_ascii=False),
                        )
            cursor = len(messages)

        def chat_with_tools(self, messages, tools, temperature=0.0, max_tokens=4096):
            self.last_messages = messages
            while True:
                self.capture(messages)
                actual = copy.deepcopy(messages)
                budget = action_budget(agent.max_steps, self.native_steps, unit="native step")
                runtime_context = actor_runtime_context(lab, config, budget)
                if runtime_context:
                    actual[0]["content"] += "\n\n" + runtime_context
                if isinstance(memory, ExperienceRevisionSession):
                    memory.set_action_budget(
                        budget if config.get("action_budget_context", False) else {}
                    )
                extra_tools = (
                    memory_tools(isinstance(memory, ExperienceRevisionSession))
                    if isinstance(memory, (ExperienceRevisionSession, NativeOMSession))
                    else []
                )
                if isinstance(memory, NativeOMSession):
                    # The final request receives memory below. Keep a separate
                    # native-only snapshot for later capacity maintenance.
                    memory.native_messages = copy.deepcopy(actual)
                    memory.native_tools = [*tools, *extra_tools]
                if memory:
                    actual[0]["content"] += "\n\n" + memory.memory_context()
                if isinstance(memory, EvidenceUtilitySession):
                    memory.prepare_actor_input(actual)
                if isinstance(memory, NativeCapacityOMSession):
                    memory.check_actor_request(actual, [*tools, *extra_tools])
                message = provider.generate_message(task_id, actual, tools=[*tools, *extra_tools])
                if isinstance(memory, EvidenceUtilitySession):
                    memory.confirm_actor_input(provider.last_receipt)
                elif isinstance(memory, ExperienceRevisionSession):
                    memory.confirm_actor_input()
                if isinstance(memory, NativeOMSession):
                    memory.mark_seen()
                calls = message.get("tool_calls") or []
                tool_names.update({tc["id"]: tc["function"]["name"] for tc in calls})
                if calls and all(
                    tc["function"]["name"] in {"memory_read", "memory_revise", "memory_state"}
                    for tc in calls
                ):
                    # Keep real auxiliary interactions in the same native history
                    # so later business actions can still use previously read facts.
                    messages.append(message)
                    for tc in calls:
                        receipt = operation(
                            tc["function"]["name"], json.loads(tc["function"]["arguments"])
                        )
                        messages.append(self.format_tool_result(tc["id"], receipt))
                    continue
                self.native_steps += 1
                return ModelResponse(
                    content=message.get("content"),
                    tool_calls=[
                        ToolCall(
                            tc["id"],
                            tc["function"]["name"],
                            json.loads(tc["function"]["arguments"]),
                        )
                        for tc in calls
                    ]
                    or None,
                    raw_response={"message": message},
                )

    client = Client()

    class Agent(TravelPlannerAgent):
        def _create_client(self, model_name):
            return client

    agent = Agent(model_name=MODEL, max_steps=30)
    native_execute = agent.executor.execute

    def operation(name, args):
        if name not in {"memory_read", "memory_revise", "memory_state"}:
            return native_execute(name, args)
        try:
            if name == "memory_read" and isinstance(
                memory, (ExperienceRevisionSession, NativeOMSession)
            ):
                read = (
                    memory.actor_read
                    if isinstance(memory, ExperienceRevisionSession)
                    else memory.read
                )
                return json.dumps(
                    read(args["ref"], args.get("start", 0), args.get("length")),
                    ensure_ascii=False,
                )
            if name == "memory_state" and isinstance(memory, ExperienceRevisionSession):
                return json.dumps(memory.request_task_update(args), ensure_ascii=False)
            if name == "memory_revise" and isinstance(memory, ExperienceRevisionSession):
                return json.dumps(memory.request_revision(args), ensure_ascii=False)
            raise ValueError("MEMORY_OPERATION_NOT_AVAILABLE")
        except (ValueError, KeyError, TypeError) as error:
            return json.dumps({"status": "REJECTED", "reason": str(error)})

    agent.executor.execute = operation
    submissions = []
    group_results = []
    try:
        for group_id in config["ids"]:
            provider.begin_unit(config.get("unit_limits"))
            group_root = root / f"group-{group_id}"
            group_root.mkdir()
            group_scope = {**scope, "stream": f"{scope['stream']}/group-{group_id}"}
            bank = seed.fork(group_scope)
            om_state = copy.deepcopy(om_seed)
            obs = env.reset(seed=int(group_id))
            base = obs["base_person"]
            questions = obs["questions"]
            # Do not retain or pass obs['answers'] to a provider/memory callback.
            del obs
            agent.reset()
            base_plan = format_person_plan(base["name"], base["daily_plans"])
            if config.get("candidate_policy") == "evidence_utility":
                save(group_root / "base-plan.json", {"given_plan": base_plan})
            plans = [("Given base-person plan", base_plan)]
            accumulated = base_plan
            people = []

            def new_memory(
                identifier,
                query,
                facts=(),
                group_root=group_root,
                om_state=om_state,
                group_scope=group_scope,
                bank=bank,
            ):
                def emit(event):
                    append_event(group_root / "memory-events.jsonl", event)

                if config["method"] == "NATIVE_AGENT_OR_HISTORY":
                    return None
                if config["method"] == "OM_SYNC_PORT":
                    value = om_session_class(config)(
                        state=om_state,
                        scope=group_scope,
                        provider=provider,
                        task_id=identifier,
                        policy_root=lab / "configs/policies/om_sync",
                        emit=emit,
                        config=config.get("om_config"),
                        compact_provenance=config.get("om_compact_provenance", False),
                    )
                else:
                    cls = (
                        candidate_session_class(config)
                        if config["method"] == "MILAI_EXPERIENCE_REVISION"
                        else ReasoningBankSession
                    )
                    value = cls(
                        bank=bank,
                        config=bank_config,
                        policies=policies,
                        generate=lambda call: provider.memory_call(identifier, call),
                        embed=lambda texts: embedding.embed(identifier, texts),
                        emit=emit,
                        **(
                            {
                                "revision_application": config.get(
                                    "revision_application", "replace"
                                ),
                                "projection_mode": config.get("projection_mode", "selected"),
                                "post_task_revision": config.get("post_task_revision", False),
                                "project_task_facts": not config.get("shared_native_plans", False),
                                "action_budget": action_budget(
                                    agent.max_steps, client.native_steps, unit="native step"
                                )
                                if config.get("action_budget_context", False)
                                else None,
                            }
                            if issubclass(cls, ExperienceRevisionSession)
                            else {}
                        ),
                        **(
                            {"task_costs": lambda: provider.task_usage(identifier)}
                            if cls is EvidenceUtilitySession
                            else {}
                        ),
                    )
                if isinstance(value, ExperienceRevisionSession):
                    value.start(identifier, query, task_facts=tuple(facts))
                else:
                    value.start(identifier, query)
                return value

            if config["method"] == "NATIVE_AGENT_OR_HISTORY" or config.get("shared_native_plans"):
                agent.set_base_person(base["name"], base["query"], base_plan)
            if config["method"] != "NATIVE_AGENT_OR_HISTORY":
                task_id = f"travel:{group_id}:base"
                memory = new_memory(task_id, base["query"], facts=plans)
                memory.observe("given_base_plan", base_plan)
                if isinstance(memory, EvidenceUtilitySession):
                    memory.seal_result(str(group_root / "base-plan.json"))
                memory.finish("Given completed base-person plan:\n" + base_plan, commit=True)
                # The base is supplied data, not an Actor-generated task outcome.
                save(group_root / "base-memory.json", memory.checkpoint())
            for question in questions:
                position = question["round_idx"]
                task_id = f"travel:{group_id}:{position}"
                begin = time.monotonic()
                client.native_steps = 0
                memory = new_memory(task_id, question["query"], facts=plans)
                cursor, legal_trajectory = 0, []
                tool_names.clear()
                agent.prepare_for_person(
                    name=question["name"],
                    round_idx=position,
                    include_previous_plans=memory is None
                    or config.get("shared_native_plans", False),
                )
                action = agent.act(question["query"])
                client.capture(client.last_messages)
                legal_trajectory.append({"role": "assistant", "content": action})
                if memory:
                    memory.observe("actor", action)
                # Native environment step with judgment disabled. Evaluation is
                # performed separately after complete group submissions exist.
                env.step(action, need_judge=False)
                native_result = agent.last_result
                person = {
                    "round": position,
                    "steps": native_result.total_steps,
                    "native_success": native_result.success,
                    "final_nonempty": bool(action),
                    "seconds": time.monotonic() - begin,
                }
                save(
                    group_root / f"person-{position}.json",
                    {
                        **person,
                        "query": question["query"],
                        "final_plan": action,
                        "scratchpad": agent.get_scratchpad_dict(),
                    },
                )
                if memory:
                    if isinstance(memory, EvidenceUtilitySession):
                        memory.seal_result(str(group_root / f"person-{position}.json"))
                    person["maintenance"] = memory.finish(
                        json.dumps(legal_trajectory, ensure_ascii=False), commit=True
                    )
                    atomic_save(group_root / "bank.json", memory.checkpoint())
                people.append(person)
                plans.append((f"Generated plan for person {position}: {question['name']}", action))
                accumulated += "\n\n" + action
                atomic_save(
                    group_root / "progress.json", {"people": people, "planned": len(questions)}
                )
            final = parse_all_plans(accumulated, questions)
            submissions.append(
                {
                    "id": int(group_id),
                    "persons": [
                        {
                            "person_idx": p["person_idx"],
                            "name": p["name"],
                            "query": p["query"],
                            "plan": parse_plan_text(p["result"]),
                        }
                        for p in final
                    ],
                }
            )
            group_results.append(
                {"id": group_id, "planned_sessions": len(questions), "people": people}
            )
            atomic_save(root / "progress.json", group_results)
            if config["split"] == "SUPPORT":
                seed = bank.fork(scope)
                om_seed = copy.deepcopy(om_state)
                atomic_save(
                    root / "bank.json",
                    om_seed if config["method"] == "OM_SYNC_PORT" else seed.checkpoint(),
                )
        submission = root / "submission.jsonl"
        submission.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in submissions)
        )
        raw = evaluator.evaluate(str(submission), model_name=MODEL, memory_system=config["method"])
        result = {
            "status": "COMPLETED",
            "groups": group_results,
            "raw_native_metrics": raw,
            "group_coverage": len(submissions) / len(config["ids"]),
            "planned_sessions": sum(len(row["questions"]) for row in selected_rows),
            "completed_sessions": sum(len(row["people"]) for row in group_results),
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
                "completed_groups": group_results,
                "usage": accounting(read_events(provider.ledger)),
            },
        )
        raise
    finally:
        provider.close()
        embedding.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    execute(json.loads(args.config.read_text()))


if __name__ == "__main__":
    main()
