"""Frozen-candidate MiLAi adapter for the official LongMemEval-V2 harness.

The adapter is deliberately paper-plane only.  It implements the public
``Memory`` duck contract without importing the benchmark package at module
import time, so the candidate Runtime can stay in its isolated wheel
environment.  ``register_with_official_harness`` performs the exact source
identity checks and registers this class when the official harness starts.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import subprocess
import sys
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = Path("/cra/memory/mx_memory/benchmarks/LongMemEval-V2")
EXPECTED_BENCHMARK_COMMIT = "2cc8c540bdb87fe6761629b585e727e1c4704520"
EXPECTED_CANDIDATE_ID = (
    "712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51"
)
EXPECTED_RUNTIME_WHEEL_SHA256 = (
    "7fc0b1ab3babed5d99daca1ef92a7160ba0de729a34ccc1b1a10c5c82641e25a"
)
EXPECTED_MCP_WHEEL_SHA256 = (
    "7ef5b1038f38a47fdffa4c9f73e39072a0525174b7220022dbf1ae6ebfc089a2"
)
EXPECTED_PRODUCT_ADAPTER_SHA256 = (
    "b69a65280cdeeb6c9ece91cf96c759632961b4e1506755e818090da2d8c04fa9"
)
EXPECTED_PAPER_BACKEND_SHA256 = (
    "8907449de543ec0388aae1fe4a92a4b621ec5412028a8f70f16281a3c4ec8c62"
)
EXPECTED_OFFICIAL_FILES = {
    "data/longmemeval-v2/SCHEMA.md": (
        "0672cf47cf16c30365648770628b433076bb3f5b73edded673af7dd6d5f3246f"
    ),
    "evaluation/harness.py": (
        "93fe5855a74ad46d7e8b489cebac24de38a9b30ba7ec1de2dd8708bd4aeebdb6"
    ),
    "memory_modules/memory.py": (
        "607ca21320067df2abc3583b80debeb819781e90955776bdea4313a8b93a0586"
    ),
    "memory_modules/trajectory_store.py": (
        "437b825499000f7ae774f948a5e62a2ff9f455367491f97d0382431965ce594c"
    ),
}
DEFAULT_ENV_FILE = ROOT / "runtime/.env"
DEFAULT_RUNTIME_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_runtime-0.1.0-py3-none-any.whl"
)
DEFAULT_MCP_WHEEL = (
    ROOT / "var/dg11/freeze/candidate/packages/milai_mcp-0.1.0-py3-none-any.whl"
)
_PRODUCT_ADAPTER = ROOT / "evals/benchmark/lme_product_smoke.py"
_PAPER_BACKEND = ROOT / "evals/paper/runners/milai_contexts.py"
_TOKEN = re.compile(r"[\w.-]+", re.UNICODE)
_QUERY_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
_LABEL_KEYS = frozenset(
    {
        "answer",
        "answer_gold",
        "answer_session_ids",
        "eval_function",
        "gold",
        "label",
        "reference_answer",
        "score",
    }
)
_GLOBAL_RUNTIME_LOCK = threading.Lock()
_SYNTHETIC_TIME_ORIGIN = datetime(2000, 1, 1, tzinfo=timezone.utc)


class LMEV2AdapterError(RuntimeError):
    """Raised when adapter identity, schema, or runtime behavior drifts."""


class MemoryContextItem(TypedDict):
    type: Literal["text", "image"]
    value: str


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    logical_query_id: str
    query: str
    sessions: tuple[tuple[str, str], ...]
    observed_at: tuple[datetime, ...]
    question_at: datetime
    env_file: Path
    recall_limit: int


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    context: str
    context_status: str
    retrieved_trajectory_ids: tuple[str, ...]
    usage: Mapping[str, Any]


RuntimeBackend = Callable[[RuntimeRequest], RuntimeResult]


@dataclass(frozen=True, slots=True)
class _State:
    state_index: int
    step: int
    url: str
    action: str | None
    thought: str | None
    accessibility_tree: str
    screenshot_ref: str
    screenshot_path: Path


@dataclass(frozen=True, slots=True)
class _Trajectory:
    trajectory_id: str
    domain: str
    environment: str
    goal: str
    outcome: str
    start_url: str
    states: tuple[_State, ...]
    rendered: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def official_contract_identity() -> dict[str, Any]:
    """Verify only tracked public source contracts; never open question rows."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BENCHMARK_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LMEV2AdapterError("LongMemEval-V2 Git identity is unavailable") from exc
    commit = completed.stdout.strip()
    if commit != EXPECTED_BENCHMARK_COMMIT:
        raise LMEV2AdapterError("LongMemEval-V2 commit drifted")
    files: dict[str, dict[str, Any]] = {}
    for relative, expected_sha256 in EXPECTED_OFFICIAL_FILES.items():
        path = BENCHMARK_ROOT / relative
        if not path.is_file() or _sha256_file(path) != expected_sha256:
            raise LMEV2AdapterError(
                f"LongMemEval-V2 official interface drifted: {relative}"
            )
        files[relative] = {
            "bytes": path.stat().st_size,
            "sha256": expected_sha256,
        }
    return {
        "commit": commit,
        "files": files,
        "paper_data_opened": False,
        "question_rows_read": 0,
    }


def register_with_official_harness() -> dict[str, Any]:
    """Register ``milai`` after verifying the exact official harness contract."""

    identity = official_contract_identity()
    benchmark_text = str(BENCHMARK_ROOT)
    if benchmark_text not in sys.path:
        sys.path.insert(0, benchmark_text)
    memory_module = importlib.import_module("memory_modules.memory")
    registry = getattr(memory_module, "MEMORY_TYPES", None)
    register = getattr(memory_module, "register_memory", None)
    if not isinstance(registry, dict) or not callable(register):
        raise LMEV2AdapterError("official Memory registry contract drifted")
    existing = registry.get(MiLAiLMEV2Memory.memory_type)
    if existing is not None and existing is not MiLAiLMEV2Memory:
        raise LMEV2AdapterError("official Memory registry already owns type 'milai'")
    if existing is None:
        register(MiLAiLMEV2Memory)
    if registry.get(MiLAiLMEV2Memory.memory_type) is not MiLAiLMEV2Memory:
        raise LMEV2AdapterError("MiLAi Memory registration failed")
    return identity


def _string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise LMEV2AdapterError(f"trajectory {field} must be a string")
    return value.strip() if not allow_empty else value


def _reject_label_fields(value: object, *, location: str = "trajectory") -> None:
    if isinstance(value, dict):
        leaked = sorted(str(key) for key in value if str(key).casefold() in _LABEL_KEYS)
        if leaked:
            raise LMEV2AdapterError(
                f"scorer label fields are prohibited in {location}: {leaked}"
            )
        for key, child in value.items():
            _reject_label_fields(child, location=f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_label_fields(child, location=f"{location}[{index}]")


def _resolve_screenshot(root: Path, reference: str) -> Path:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise LMEV2AdapterError(
            "trajectory screenshot must be a contained relative path"
        )
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise LMEV2AdapterError(f"trajectory screenshot is unavailable: {reference}")
    return resolved


def _render_trajectory(
    *,
    trajectory_id: str,
    domain: str,
    environment: str,
    goal: str,
    outcome: str,
    start_url: str,
    states: Sequence[_State],
) -> str:
    lines = [
        f"TRAJECTORY_ID: {trajectory_id}",
        f"DOMAIN: {domain}",
        f"ENVIRONMENT: {environment}",
        f"GOAL: {goal}",
        f"OUTCOME: {outcome}",
        f"START_URL: {start_url}",
    ]
    for state in states:
        lines.extend(
            [
                "",
                f"STATE_INDEX: {state.state_index}",
                f"STEP: {state.step}",
                f"URL: {state.url}",
                f"ACTION: {state.action or '<none>'}",
                f"THOUGHT: {state.thought or '<none>'}",
                f"SCREENSHOT_REF: {state.screenshot_ref}",
                "ACCESSIBILITY_TREE:",
                state.accessibility_tree,
            ]
        )
    return "\n".join(lines).strip()


def _normalize_trajectory(
    value: Mapping[str, object], screenshot_root: Path
) -> _Trajectory:
    _reject_label_fields(value)
    trajectory_id = _string(value.get("id"), "id")
    domain = _string(value.get("domain"), "domain")
    if domain not in {"web", "enterprise"}:
        raise LMEV2AdapterError("trajectory domain must be web or enterprise")
    environment = _string(value.get("environment"), "environment")
    goal = _string(value.get("goal"), "goal")
    outcome = _string(value.get("outcome"), "outcome")
    if outcome not in {"success", "failure"}:
        raise LMEV2AdapterError("trajectory outcome must be success or failure")
    start_url = _string(value.get("start_url"), "start_url")
    raw_states = value.get("states")
    if not isinstance(raw_states, list) or not raw_states:
        raise LMEV2AdapterError("trajectory states must be a non-empty list")
    states: list[_State] = []
    for expected_index, raw_state in enumerate(raw_states):
        if not isinstance(raw_state, dict):
            raise LMEV2AdapterError("trajectory state must be an object")
        state_index = raw_state.get("state_index")
        step = raw_state.get("step", expected_index)
        if (
            isinstance(state_index, bool)
            or not isinstance(state_index, int)
            or state_index != expected_index
        ):
            raise LMEV2AdapterError(
                "trajectory state_index must be zero-based and ordered"
            )
        if isinstance(step, bool) or not isinstance(step, int):
            raise LMEV2AdapterError("trajectory step must be an integer")
        action_value = raw_state.get("action")
        thought_value = raw_state.get("thought")
        if action_value is not None and not isinstance(action_value, str):
            raise LMEV2AdapterError("trajectory action must be a string or null")
        if thought_value is not None and not isinstance(thought_value, str):
            raise LMEV2AdapterError("trajectory thought must be a string or null")
        screenshot_ref = _string(raw_state.get("screenshot"), "state.screenshot")
        states.append(
            _State(
                state_index=state_index,
                step=step,
                url=_string(raw_state.get("url"), "state.url"),
                action=action_value.strip() if isinstance(action_value, str) else None,
                thought=thought_value.strip()
                if isinstance(thought_value, str)
                else None,
                accessibility_tree=_string(
                    raw_state.get("accessibility_tree"),
                    "state.accessibility_tree",
                    allow_empty=True,
                ),
                screenshot_ref=screenshot_ref,
                screenshot_path=_resolve_screenshot(screenshot_root, screenshot_ref),
            )
        )
    rendered = _render_trajectory(
        trajectory_id=trajectory_id,
        domain=domain,
        environment=environment,
        goal=goal,
        outcome=outcome,
        start_url=start_url,
        states=states,
    )
    return _Trajectory(
        trajectory_id=trajectory_id,
        domain=domain,
        environment=environment,
        goal=goal,
        outcome=outcome,
        start_url=start_url,
        states=tuple(states),
        rendered=rendered,
    )


def _query_terms(query: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _TOKEN.findall(query)
        if len(token) >= 2
        and not token.isdecimal()
        and token.casefold() not in _QUERY_STOPWORDS
    )


def _state_score(
    query: str, terms: frozenset[str], trajectory: _Trajectory, state: _State
) -> tuple[int, int]:
    query_folded = query.casefold().strip()
    weighted_parts = (
        (trajectory.goal.casefold(), 2),
        (state.url.casefold(), 1),
        ((state.action or "").casefold(), 3),
        ((state.thought or "").casefold(), 1),
        (state.accessibility_tree.casefold(), 3),
    )
    score = 0
    for text, weight in weighted_parts:
        if query_folded and query_folded in text:
            score += 20 * weight
        counts = Counter(token.casefold() for token in _TOKEN.findall(text))
        score += weight * sum(min(counts[term], 3) for term in terms)
    return score, -state.state_index


def _select_state(query: str, trajectory: _Trajectory) -> _State:
    terms = _query_terms(query)
    return max(
        trajectory.states,
        key=lambda state: _state_score(query, terms, trajectory, state),
    )


def _path_param(value: object, field: str, default: Path) -> Path:
    raw = str(value).strip() if value is not None else str(default)
    if not raw:
        raise LMEV2AdapterError(f"memory_params.{field} must be non-empty")
    path = Path(raw)
    return path if path.is_absolute() else (ROOT / path).resolve()


def _int_param(value: object, field: str, default: int) -> int:
    raw = default if value is None else value
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise LMEV2AdapterError(f"memory_params.{field} must be an integer")
    return raw


def _default_runtime_backend(request: RuntimeRequest) -> RuntimeResult:
    if _sha256_file(_PRODUCT_ADAPTER) != EXPECTED_PRODUCT_ADAPTER_SHA256:
        raise LMEV2AdapterError("candidate-frozen product adapter drifted")
    if _sha256_file(_PAPER_BACKEND) != EXPECTED_PAPER_BACKEND_SHA256:
        raise LMEV2AdapterError("paper Runtime backend drifted")
    try:
        import milai
        import milai_mcp  # type: ignore[import-not-found]
    except ImportError as exc:
        raise LMEV2AdapterError("frozen MiLAi wheels are not installed") from exc
    prefix = Path(sys.prefix).resolve()
    origins = {
        "mcp": Path(str(milai_mcp.__file__)).resolve(),
        "runtime": Path(str(milai.__file__)).resolve(),
    }
    if any(not path.is_relative_to(prefix) for path in origins.values()):
        raise LMEV2AdapterError(
            "MiLAi adapter imported outside the isolated environment"
        )

    from evals.benchmark import lme_product_smoke as product
    from evals.paper.runners.milai_contexts import (
        _runtime_context_with_embedding_accounting,
    )

    case = product.ProductSmokeCase(
        case_id=f"longmemeval-v2:{request.logical_query_id}",
        source_case_id=request.logical_query_id,
        dataset="LONGMEMEVAL_V2_SMALL",
        category="agentic_trajectory_memory",
        question=request.query,
        answers=(),
        sessions=request.sessions,
        question_at=request.question_at,
        session_observed_at=request.observed_at,
    )
    context, trace = _runtime_context_with_embedding_accounting(
        case=case,
        env_file=request.env_file,
    )
    raw_ids = trace.get("retrieved_session_ids")
    if not isinstance(raw_ids, list) or not all(
        isinstance(item, str) for item in raw_ids
    ):
        raise LMEV2AdapterError("MiLAi Runtime omitted retrieved trajectory identities")
    accounting = trace.get("paper_embedding_accounting")
    if not isinstance(accounting, dict):
        raise LMEV2AdapterError("MiLAi Runtime omitted embedding accounting")
    return RuntimeResult(
        context=str(context.rendered),
        context_status=str(context.status),
        retrieved_trajectory_ids=tuple(raw_ids),
        usage={
            "compiler_version": str(
                getattr(context, "compiler_version", "DG10_LEGACY")
            ),
            "embedding_accounting": dict(accounting),
            "governed_claim_count": trace.get("governed_claim_count"),
            "index_time_ms": trace.get("ingest_ms"),
            "mcp_origin": str(origins["mcp"]),
            "memory_status": trace.get("memory_status"),
            "projected_events": trace.get("projected_events"),
            "retrieval_time_ms": trace.get("retrieval_ms"),
            "runtime_origin": str(origins["runtime"]),
            "total_runtime_ms": trace.get("total_runtime_ms"),
        },
    )


class MiLAiLMEV2Memory:
    """Official Memory-compatible adapter for the frozen DG11 candidate."""

    memory_type = "milai"

    def __init__(
        self,
        memory_params: dict[str, object],
        *,
        _backend: RuntimeBackend | None = None,
    ) -> None:
        allowed = {
            "candidate_id",
            "env_file",
            "max_case_attempts",
            "max_retrieved_screenshots",
            "mcp_wheel",
            "method_id",
            "recall_limit",
            "runtime_wheel",
            "trajectories_root_dir",
        }
        unexpected = sorted(set(memory_params) - allowed)
        if unexpected:
            raise LMEV2AdapterError(f"unexpected MiLAi memory params: {unexpected}")
        candidate_id = str(memory_params.get("candidate_id", EXPECTED_CANDIDATE_ID))
        method_id = str(memory_params.get("method_id", "DG11-FULL"))
        if candidate_id != EXPECTED_CANDIDATE_ID or method_id != "DG11-FULL":
            raise LMEV2AdapterError(
                "MiLAi candidate identity is not the frozen DG11 method"
            )
        self.env_file = _path_param(
            memory_params.get("env_file"), "env_file", DEFAULT_ENV_FILE
        )
        self.runtime_wheel = _path_param(
            memory_params.get("runtime_wheel"), "runtime_wheel", DEFAULT_RUNTIME_WHEEL
        )
        self.mcp_wheel = _path_param(
            memory_params.get("mcp_wheel"), "mcp_wheel", DEFAULT_MCP_WHEEL
        )
        root_value = memory_params.get("trajectories_root_dir")
        if not isinstance(root_value, str) or not root_value.strip():
            raise LMEV2AdapterError("memory_params.trajectories_root_dir is required")
        self.trajectories_root_dir = Path(root_value).resolve()
        if not self.trajectories_root_dir.is_dir():
            raise LMEV2AdapterError("trajectories_root_dir is unavailable")
        self.recall_limit = _int_param(
            memory_params.get("recall_limit"), "recall_limit", 3
        )
        self.max_retrieved_screenshots = _int_param(
            memory_params.get("max_retrieved_screenshots"),
            "max_retrieved_screenshots",
            3,
        )
        self.max_case_attempts = _int_param(
            memory_params.get("max_case_attempts"), "max_case_attempts", 2
        )
        if self.recall_limit != 3:
            raise LMEV2AdapterError("frozen MiLAi PE06 recall_limit must equal 3")
        if not 1 <= self.max_retrieved_screenshots <= self.recall_limit:
            raise LMEV2AdapterError("max_retrieved_screenshots is invalid")
        if not 1 <= self.max_case_attempts <= 2:
            raise LMEV2AdapterError("max_case_attempts is invalid")
        if _backend is None and (
            not self.env_file.is_file()
            or not self.runtime_wheel.is_file()
            or _sha256_file(self.runtime_wheel) != EXPECTED_RUNTIME_WHEEL_SHA256
            or not self.mcp_wheel.is_file()
            or _sha256_file(self.mcp_wheel) != EXPECTED_MCP_WHEEL_SHA256
        ):
            raise LMEV2AdapterError("frozen MiLAi PE06 artifacts drifted")
        self._backend = _backend or _default_runtime_backend
        self._trajectories: dict[str, _Trajectory] = {}
        self._state_lock = threading.RLock()
        self._query_context_local = threading.local()
        self._query_started = False
        self._runtime_metadata_local = threading.local()
        self.memory_params: dict[str, object] = {
            "candidate_id": candidate_id,
            "env_file": str(self.env_file),
            "max_case_attempts": self.max_case_attempts,
            "max_retrieved_screenshots": self.max_retrieved_screenshots,
            "mcp_wheel": str(self.mcp_wheel),
            "method_id": method_id,
            "recall_limit": self.recall_limit,
            "runtime_wheel": str(self.runtime_wheel),
            "trajectories_root_dir": str(self.trajectories_root_dir),
        }

    @property
    def memory_config(self) -> dict[str, object]:
        return {
            "memory_type": self.memory_type,
            "memory_params": deepcopy(self.memory_params),
        }

    def configure_runtime(self, **kwargs: object) -> None:
        allowed = {
            "cancel_event",
            "generation_temperature",
            "generation_top_p",
            "query_trace_dir",
        }
        unexpected = sorted(set(kwargs) - allowed)
        if unexpected:
            raise LMEV2AdapterError(f"unexpected runtime overrides: {unexpected}")

    def set_query_context(self, *, query_invocation_id: str) -> None:
        if not isinstance(query_invocation_id, str) or not query_invocation_id.strip():
            raise LMEV2AdapterError("query_invocation_id must be non-empty")
        self._query_context_local.context = {
            "query_invocation_id": query_invocation_id.strip()
        }

    def clear_query_context(self) -> None:
        if hasattr(self._query_context_local, "context"):
            delattr(self._query_context_local, "context")

    def get_query_context(self) -> dict[str, str]:
        value = getattr(self._query_context_local, "context", None)
        return dict(value) if isinstance(value, dict) else {}

    def insert(self, trajectory: dict[str, object]) -> None:
        if not isinstance(trajectory, dict):
            raise LMEV2AdapterError("trajectory must be an object")
        # A JSON round-trip makes caller mutation unable to alter indexed evidence.
        try:
            isolated = json.loads(json.dumps(trajectory, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise LMEV2AdapterError("trajectory must be JSON serializable") from exc
        normalized = _normalize_trajectory(isolated, self.trajectories_root_dir)
        with self._state_lock:
            if self._query_started:
                raise LMEV2AdapterError("insert after first query is prohibited")
            if normalized.trajectory_id in self._trajectories:
                raise LMEV2AdapterError("duplicate trajectory id")
            self._trajectories[normalized.trajectory_id] = normalized

    def _snapshot(self) -> tuple[_Trajectory, ...]:
        with self._state_lock:
            if not self._trajectories:
                raise LMEV2AdapterError("MiLAi memory has no trajectories")
            self._query_started = True
            return tuple(self._trajectories.values())

    def _logical_query_id(self, query: str) -> str:
        context = self.get_query_context()
        opaque = context.get("query_invocation_id")
        if opaque:
            return opaque
        return "query-" + hashlib.sha256(query.encode("utf-8")).hexdigest()[:24]

    def _invoke_backend(self, request: RuntimeRequest) -> tuple[RuntimeResult, int]:
        last_error: Exception | None = None
        attempts = 0
        for attempt in range(1, self.max_case_attempts + 1):
            attempts = attempt
            try:
                with _GLOBAL_RUNTIME_LOCK:
                    return self._backend(request), attempts
            except Exception as exc:  # noqa: BLE001 - bounded infra retry
                last_error = exc
                retryable = any(
                    marker in str(exc)
                    for marker in ("endpoint is unavailable", "database cleanup failed")
                )
                if not retryable or attempt == self.max_case_attempts:
                    break
        assert last_error is not None
        raise LMEV2AdapterError(
            f"MiLAi Runtime query failed after {attempts} attempt(s)"
        ) from last_error

    def query(
        self,
        query: str,
        query_image: str | None = None,
    ) -> list[MemoryContextItem]:
        if not isinstance(query, str) or not query.strip():
            raise LMEV2AdapterError("MiLAi query must be non-empty")
        query_image_path: Path | None = None
        if query_image is not None:
            query_image_path = Path(query_image).resolve()
            if not query_image_path.is_file():
                raise LMEV2AdapterError("query image is unavailable")
        trajectories = self._snapshot()
        observed = tuple(
            _SYNTHETIC_TIME_ORIGIN + timedelta(minutes=index)
            for index in range(len(trajectories))
        )
        request = RuntimeRequest(
            logical_query_id=self._logical_query_id(query),
            query=query.strip(),
            sessions=tuple(
                (trajectory.trajectory_id, trajectory.rendered)
                for trajectory in trajectories
            ),
            observed_at=observed,
            question_at=_SYNTHETIC_TIME_ORIGIN
            + timedelta(minutes=len(trajectories) + 1),
            env_file=self.env_file,
            recall_limit=self.recall_limit,
        )
        result, attempts = self._invoke_backend(request)
        by_id = {trajectory.trajectory_id: trajectory for trajectory in trajectories}
        selected_ids: list[str] = []
        for trajectory_id in result.retrieved_trajectory_ids:
            if trajectory_id not in by_id:
                raise LMEV2AdapterError(
                    "MiLAi Runtime returned an unknown trajectory identity"
                )
            if trajectory_id not in selected_ids:
                selected_ids.append(trajectory_id)
        if len(selected_ids) > self.recall_limit:
            raise LMEV2AdapterError("MiLAi Runtime exceeded the frozen recall limit")

        items: list[MemoryContextItem] = []
        if result.context.strip():
            items.append(
                {
                    "type": "text",
                    "value": (
                        "## MiLAi governed trajectory retrieval\n"
                        f"{result.context.strip()}"
                    ),
                }
            )
        screenshot_records: list[dict[str, Any]] = []
        for rank, trajectory_id in enumerate(
            selected_ids[: self.max_retrieved_screenshots], start=1
        ):
            trajectory = by_id[trajectory_id]
            state = _select_state(query, trajectory)
            screenshot_sha256 = _sha256_file(state.screenshot_path)
            items.append(
                {
                    "type": "text",
                    "value": (
                        f"### Retrieved trajectory state {rank}\n"
                        f"Trajectory: {trajectory_id}\n"
                        f"Goal: {trajectory.goal}\n"
                        f"Outcome: {trajectory.outcome}\n"
                        f"State index: {state.state_index}\n"
                        f"Step: {state.step}\n"
                        f"URL: {state.url}\n"
                        f"Action: {state.action or '<none>'}\n"
                        f"Thought: {state.thought or '<none>'}\n"
                        f"Screenshot ref: {state.screenshot_ref}\n"
                        f"Screenshot sha256: {screenshot_sha256}\n"
                        "Accessibility tree:\n"
                        f"{state.accessibility_tree}\n"
                        "The next image is the exact screenshot for this state."
                    ),
                }
            )
            items.append({"type": "image", "value": str(state.screenshot_path)})
            screenshot_records.append(
                {
                    "bytes": state.screenshot_path.stat().st_size,
                    "path": str(state.screenshot_path),
                    "rank": rank,
                    "sha256": screenshot_sha256,
                    "state_index": state.state_index,
                    "trajectory_id": trajectory_id,
                }
            )

        indexed_text_bytes = sum(
            len(trajectory.rendered.encode("utf-8")) for trajectory in trajectories
        )
        referenced_image_bytes = sum(
            state.screenshot_path.stat().st_size
            for trajectory in trajectories
            for state in trajectory.states
        )
        metadata = {
            "adapter_schema": "milai.dg11.lme-v2-memory-query.v1",
            "attempts": attempts,
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "context_status": result.context_status,
            "image_retrieval": "TEXT_SELECTED_TRAJECTORY_THEN_DETERMINISTIC_STATE",
            "indexed_text_bytes": indexed_text_bytes,
            "labels_accessed": False,
            "modality_lossiness": {
                "question_image_passed_to_memory_query": query_image_path is not None,
                "question_image_used_for_visual_retrieval": False,
                "reader_receives_question_image_independently": query_image_path
                is not None,
                "retrieved_screenshot_pixels_preserved": True,
                "visual_only_retrieval_supported": False,
            },
            "paper_question_rows_read_by_adapter": 0,
            "query_image": (
                {
                    "bytes": query_image_path.stat().st_size,
                    "path": str(query_image_path),
                    "sha256": _sha256_file(query_image_path),
                }
                if query_image_path is not None
                else None
            ),
            "referenced_image_bytes": referenced_image_bytes,
            "retrieved_screenshots": screenshot_records,
            "retrieved_trajectory_ids": selected_ids,
            "runtime_serialization": "PROCESS_GLOBAL_LOCK",
            "runtime_usage": dict(result.usage),
            "synthetic_time_policy": "INSERTION_ORDER_FROM_2000-01-01T00:00:00Z",
            "trajectory_count": len(trajectories),
        }
        self._runtime_metadata_local.value = metadata
        return items

    def post_query_hook(
        self,
        *,
        query: str,
        query_image: str | None,
        memory_context: list[MemoryContextItem],
    ) -> dict[str, object] | None:
        value = getattr(self._runtime_metadata_local, "value", None)
        if not isinstance(value, dict):
            raise LMEV2AdapterError("MiLAi query metadata is unavailable")
        return deepcopy(value)

    def save_memory(self, output_dir: str | Path) -> None:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / "memory_config.json").write_text(
            json.dumps(self.memory_config, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        self._save_backend(path)

    def _save_backend(self, output_dir: Path) -> None:
        trajectories = self._snapshot()
        payload = {
            "schema": "milai.dg11.lme-v2-memory-state.v1",
            "trajectory_ids": [item.trajectory_id for item in trajectories],
            "trajectory_rendered": [item.rendered for item in trajectories],
            "trajectory_rendered_sha256": [
                hashlib.sha256(item.rendered.encode("utf-8")).hexdigest()
                for item in trajectories
            ],
        }
        (output_dir / "milai_state.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )

    def _load_backend(self, input_dir: Path) -> None:
        # The frozen adapter stores an integrity receipt, not canonical evidence.
        # Official runs rebuild from the immutable trajectory dataset.
        raise LMEV2AdapterError(
            "MiLAi PE06 saved receipts are verification-only; rebuild from trajectories"
        )


def memory_context_identity(items: Sequence[MemoryContextItem]) -> dict[str, Any]:
    """Return a byte-stable, image-aware identity without embedding image bytes."""

    records: list[dict[str, Any]] = []
    for item in items:
        if item["type"] == "text":
            records.append(
                {
                    "bytes": len(item["value"].encode("utf-8")),
                    "sha256": hashlib.sha256(item["value"].encode("utf-8")).hexdigest(),
                    "type": "text",
                }
            )
        else:
            path = Path(item["value"])
            records.append(
                {
                    "bytes": path.stat().st_size,
                    "path": str(path.resolve()),
                    "sha256": _sha256_file(path),
                    "type": "image",
                }
            )
    return {
        "items": records,
        "root_sha256": hashlib.sha256(_canonical(records)).hexdigest(),
    }


__all__ = [
    "LMEV2AdapterError",
    "MemoryContextItem",
    "MiLAiLMEV2Memory",
    "RuntimeRequest",
    "RuntimeResult",
    "memory_context_identity",
    "official_contract_identity",
    "register_with_official_harness",
]
