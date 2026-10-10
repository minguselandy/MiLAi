"""Native backends assembled around the existing online benchmark and Reader.

This module owns experiment scheduling, not another memory formation pipeline.
The backend sees ObservedSession only; gold remains in the inherited evaluator.
"""

from __future__ import annotations

import copy
import os
import pwd
import socket
import sqlite3
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from milai_lab.baselines.langmem_sqlite_store import TransactionalSqliteStore as SqliteStore
from milai_lab.contracts.memory_backend import MemoryBackend, MemorySession
from milai_lab.datasets.edit_benchmarks import (
    ObservedSession,
    halumem_time,
    halumem_users,
    history_components,
    longmemeval_cases,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.integrations.memory.hindsight import (
    HindsightIngestionIncomplete,
    HindsightModelBridge,
)
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun, reader_messages

BACKENDS = ("RawRAG-local", "Hindsight-native-local-recall", "MiLAi-memory-only")
BENCHMARKS = ("halumem", "longmemeval")

# The official env factory omits OpenAIEmbeddings.max_retries in 0.10.3.
# Its public constructor supplies that option without altering native retrieval.
NATIVE_SERVICE_SCRIPT = """
import asyncio, os, sys
import uvicorn
from hindsight_api import MemoryEngine
from hindsight_api.api import create_app
from hindsight_api.config import HindsightConfig
from hindsight_api.engine.embeddings import OpenAIEmbeddings

async def serve():
    config = HindsightConfig.from_env()
    config.validate()
    config.configure_logging()
    embeddings = OpenAIEmbeddings(
        api_key=os.environ['HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY'],
        model=config.embeddings_openai_model,
        base_url=config.embeddings_openai_base_url,
        dimensions=config.embeddings_openai_dimensions,
        batch_size=config.embeddings_openai_batch_size,
        query_prefix=config.embeddings_query_prefix,
        passage_prefix=config.embeddings_passage_prefix,
        max_retries=0,
    )
    embeddings.max_concurrent_requests = config.embeddings_max_concurrent_requests
    memory = MemoryEngine(embeddings=embeddings, skip_llm_verification=True,
                          run_migrations=config.run_migrations_on_startup)
    app = create_app(memory=memory, http_api_enabled=True,
                     mcp_api_enabled=False, initialize_memory=True)
    server = uvicorn.Server(uvicorn.Config(
        app, host='127.0.0.1', port=int(sys.argv[1]), workers=1,
        loop='asyncio', ws='wsproto', timeout_keep_alive=30,
        timeout_graceful_shutdown=5,
    ))
    try:
        await server.serve()
    except BaseException as primary:
        try:
            await memory.close()
        except BaseException as cleanup:
            primary.add_note(f'Native cleanup also failed: {cleanup}')
        raise
    if not server.started:
        await memory.close()

asyncio.run(serve())
"""


def _native_uid_processes(uid: int) -> list[int]:
    """Include detached PostgreSQL children of the dedicated service user."""
    active = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                rows = (entry / "status").read_text().splitlines()
                fields = {row.partition(":")[0]: row.partition(":")[2].strip()
                          for row in rows if row.startswith(("Uid:", "State:"))}
                if int(fields["Uid"].split()[0]) == uid and not fields["State"].startswith("Z"):
                    active.append(int(entry.name))
            except FileNotFoundError:
                pass
    return active


def alignment_settings(config: dict[str, Any], backend: str) -> dict[str, Any]:
    """One explicit configuration per arm, retaining the ordinary maintenance recipe."""
    if backend not in config["alignment"]["backends"] or backend not in BACKENDS:
        raise ValueError("Unknown declared alignment backend")
    settings = cast(dict[str, Any], copy.deepcopy(config["entrypoints"]["benchmark"]))
    settings.pop("arms", None)
    arm = settings.get("arm", "M") if backend == "MiLAi-memory-only" else "M"
    if arm not in ("B0", "B1", "B2", "M", "Append-only"):
        raise ValueError("Unknown declared MiLAi maintenance arm")
    settings.update(arm=arm, alignment_backend=backend, alignment=config["alignment"])
    # Maintenance retains its original candidate limit. QA passes its separate
    # explicit limit to the backend; aligning answers must not change writing.
    settings["memory_view_mode"] = config["alignment"]["delivery"]
    return settings


def prepare_alignment(
    config: dict[str, Any], root: Path, *, benchmark: str = "halumem",
) -> dict[str, Any]:
    """Declare actual development opportunities without banks or model clients."""
    if benchmark not in BENCHMARKS:
        raise ValueError("Unknown declared alignment benchmark")
    path = root / "alignment-prepared.json"
    if path.exists():
        manifest = read_json(path)
        if manifest["configuration"] != config:
            raise ValueError("Prepared comparison changed; use a distinct output root")
        if manifest.get("benchmark", "halumem") != benchmark:
            raise ValueError("Prepared comparison benchmark differs; use a distinct output root")
        return dict(manifest)
    alignment = config["alignment"]
    protocol = ("halumem-online-prefix" if benchmark == "halumem"
                else "longmemeval-complete-history")
    if alignment["source_policy"] != "source-only" or alignment["history_protocol"] != protocol:
        if benchmark == "halumem":
            raise ValueError("First comparison requires the declared source-only online prefix")
        raise ValueError("LongMemEval requires the declared source-only complete-history protocol")
    if alignment["delivery"] not in {"direct", "staged", "state_driven"}:
        raise ValueError("Unknown declared delivery")
    if alignment["qa_top_k"] != 20 or alignment["update_top_k"] != 10:
        raise ValueError("First comparison declares QA20 and evaluator-only update10")
    settings = config["entrypoints"]["benchmark"]
    opportunities: dict[str, Any] = {}
    cases: list[dict[str, Any]] = []
    fields: tuple[str, ...]
    if benchmark == "halumem":
        selection = settings["halumem"]
        users = halumem_users(Path(selection["path"]), selection["users"])
        for user in users:
            ordered = sorted(enumerate(user["sessions"]), key=lambda pair: (
                halumem_time(pair[1]["start_time"]), pair[0],
            ))[:selection["session_prefix"]]
            opportunities[user["uuid"]] = {
                "session_ordinals": [ordinal for ordinal, _ in ordered],
                "sessions": len(ordered),
                "qa": sum(len(session.get("questions", [])) for _, session in ordered
                          if not session.get("is_generated_qa_session", False)),
                "native_updates": sum(
                    memory["is_update"] == "True" for _, session in ordered
                    if not session.get("is_generated_qa_session", False)
                    for memory in session.get("memory_points", [])),
            }
        scope, fields = "per_user_opportunities", ("sessions", "qa", "native_updates")
    else:
        selection = settings["longmemeval"]
        cases = longmemeval_cases(Path(selection["path"]), selection["questions"])
        for case in cases:
            history = longmemeval_history(case)
            opportunities[case["question_id"]] = {
                "session_ids": [observed.session_id for observed in history],
                "sessions": len(history), "qa": 1,
            }
        scope, fields = "per_case_opportunities", ("sessions", "qa")
    manifest = {
        "status": "PREPARED_ZERO_MODEL", "benchmark": benchmark, "protocol": alignment,
        "configuration": config, scope: opportunities,
        "per_backend_opportunities": {
            field: sum(row[field] for row in opportunities.values())
            for field in fields
        },
        "native_and_common_answers": "separate",
        "bank_ids": {
            backend: {owner: f"milai-local-{uuid.uuid4().hex}" for owner in opportunities}
            for backend in alignment["backends"]
        },
        "runtime_method_inputs": "ObservedSession only; current query after completed ingestion",
        "reference_queries": "evaluator-only isolated view or N/A",
        "repetitions": 1, "models_called": 0,
    }
    if benchmark == "longmemeval":
        manifest.update(history_components=history_components(cases),
                        native_update_evaluation="N/A")
    if root.exists() and any(root.iterdir()):
        raise ValueError("New comparison requires an empty output root")
    write_json(path, manifest)
    return manifest


class AlignmentRun(BenchmarkRun):
    """Reuse original prefix, receipts, actual request accounting and official labels."""

    @property
    def session_output_supported(self) -> bool:
        return str(self.settings["alignment_backend"]) == "MiLAi-memory-only"

    @property
    def reference_retrieval_supported(self) -> bool:
        # Raw source retrieval is not an exported semantic memory state. Native
        # Hindsight recall is not declared to be side-effect-free or cloneable.
        return str(self.settings["alignment_backend"]) == "MiLAi-memory-only"

    def __init__(self, settings: dict[str, Any], root: Path, *, phase: str) -> None:
        super().__init__(settings, root, phase=phase)
        self.backends: dict[str, MemoryBackend] = {}
        self._resources_settled = False
        self._native_bridge: HindsightModelBridge | None = None
        self._native_process: subprocess.Popen[bytes] | None = None
        self._native_uid: int | None = None

    @staticmethod
    def _uid_processes(uid: int) -> list[int]:
        return _native_uid_processes(uid)

    def _check_native_transport(self) -> None:
        bridge = getattr(self, "_native_bridge", None)
        if bridge is not None and bridge.failure is not None:
            raise HindsightIngestionIncomplete(
                f"native_model_bridge:{bridge.failure['reason']}",
                resources_settled=bridge.failure["resources_settled"] is True,
            )

    def _native_listener_is_owned(self, port: int) -> bool:
        assert self._native_process is not None
        sockets = set()
        try:
            for path in (Path("/proc") / str(self._native_process.pid) / "fd").iterdir():
                try:
                    sockets.add(path.readlink().name)
                except FileNotFoundError:
                    pass
        except FileNotFoundError:
            return False
        for row in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = row.split()
            if (fields[1] == f"0100007F:{port:04X}" and fields[3] == "0A"
                    and int(fields[7]) == self._native_uid
                    and f"socket:[{fields[9]}]" in sockets):
                return True
        return False

    def _native_database_url(self, identity: str, uid: int, gid: int) -> str:
        """pg0's public GUC route keeps socket locks off the full system /tmp."""
        socket_root = Path(self.settings["alignment"]["hindsight_service"]["socket_root"])
        if not socket_root.is_absolute():
            raise ValueError("Native PostgreSQL socket root must be absolute")
        socket_root = socket_root.resolve()
        directory = socket_root / uuid.uuid4().hex[:16]
        # Linux sockaddr_un.sun_path includes its terminating byte. Use the
        # maximum port spelling before creating any directories or service.
        if len(os.fsencode(str(directory))) + len(b"/.s.PGSQL.65535") >= 108:
            raise ValueError("Native PostgreSQL Unix socket path is too long")
        if socket_root.exists():
            if not socket_root.is_dir() or socket_root.stat().st_uid != uid:
                raise ValueError("Native PostgreSQL socket root has a different owner")
        else:
            socket_root.mkdir(mode=0o700, parents=True)
            os.chown(socket_root, uid, gid)
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, gid)
        return f"pg0://{identity}?{urlencode({'unix_socket_directories': str(directory)})}"

    def _restored_native_database(
        self, previous: Path, uid: int, home: Path,
    ) -> tuple[str, str]:
        """Reopen a successfully closed deployment without replaying ingestion."""
        terminal = read_json(previous.parent / "terminal-predict.json")
        closed = read_json(previous / "closed.json")
        deployment = read_json(previous / "configuration.json")
        native = self.settings["alignment"]["hindsight_service"]
        if (terminal.get("status") != "PREDICTIONS_SAVED"
                or terminal.get("resources_settled") is not True
                or closed.get("processes_closed") is not True
                or closed.get("remaining_uid_processes") != []):
            raise ValueError("Native persistence requires confirmed predictions and closure")
        if (deployment.get("uid") != uid or deployment.get("home") != str(home)
                or deployment.get("version") != native["version"]
                or deployment.get("distribution") != native["distribution"]):
            raise ValueError("Native persistence deployment owner or version changed")
        environment = deployment["environment"]
        if (environment.get("HINDSIGHT_API_LLM_MODEL") != self.settings["model"]["model"]
                or environment.get("HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL")
                != self.settings["embedding"]["model"]):
            raise ValueError("Native persistence model changed")
        runtime_keys = {"HINDSIGHT_API_DATABASE_URL", "HINDSIGHT_API_DATABASE_SCHEMA",
                        "HINDSIGHT_API_LLM_MODEL", "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL",
                        "HINDSIGHT_API_LLM_BASE_URL", "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL"}
        declared = {key: value for key, value in environment.items()
                    if key.startswith("HINDSIGHT_API_") and key not in runtime_keys}
        if declared != native["environment"]:
            raise ValueError("Native persistence configuration changed")
        identity = str(read_json(previous / "started.json")["instance"])
        database_url = str(environment["HINDSIGHT_API_DATABASE_URL"])
        if (environment["HINDSIGHT_API_DATABASE_SCHEMA"] != identity
                or database_url.partition("?")[0] != f"pg0://{identity}"):
            raise ValueError("Native persistence instance and schema disagree")
        return identity, database_url

    def _start_native_service(self, *, restore_from: Path | None = None) -> None:
        """Start the isolated public native application behind the owned ledger."""
        if self._native_process is not None:
            self._check_native_transport()
            if self._native_process.poll() is not None:
                raise HindsightIngestionIncomplete("native_service_exited")
            return
        native = self.settings["alignment"]["hindsight_service"]
        url = httpx.URL(self.settings["alignment"]["hindsight"]["base_url"])
        if (url.scheme != "http" or url.host != "127.0.0.1" or url.port is None
                or url.path != "/"):
            raise ValueError("Native service requires its explicit loopback API port")
        with socket.socket() as availability:
            availability.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            availability.bind(("127.0.0.1", url.port))
        executable = Path(native["executable"]).resolve(strict=True)
        if executable.name != "hindsight-api":
            raise ValueError("Native service requires its declared official CLI executable")
        account = pwd.getpwnam(native["unix_user"])
        home = Path(account.pw_dir).resolve(strict=True)
        if (account.pw_uid == 0 or home != Path(native["home"]).resolve(strict=True)
                or home.stat().st_uid != account.pw_uid or self._uid_processes(account.pw_uid)):
            raise ValueError("Native service needs its idle dedicated nonroot user and actual home")
        if self.retrieval_embedding_client is None:
            raise ValueError("Native service requires the existing metered embedding client")
        if restore_from is None:
            identity = f"milai_{uuid.uuid4().hex}"
            database_url = self._native_database_url(identity, account.pw_uid, account.pw_gid)
        else:
            identity, database_url = self._restored_native_database(
                restore_from, account.pw_uid, home,
            )
        folder = self.root / "native-service"
        folder.mkdir(mode=0o700)
        os.chown(folder, account.pw_uid, account.pw_gid)
        (folder / ".env").write_text("")
        os.chown(folder / ".env", account.pw_uid, account.pw_gid)
        temporary = folder / "tmp"
        temporary.mkdir(mode=0o700)
        os.chown(temporary, account.pw_uid, account.pw_gid)
        env = {"PATH": f"{executable.parent}:{os.defpath}", "LANG": "C.UTF-8",
               "TMPDIR": str(temporary.resolve()), "SQLITE_TMPDIR": str(temporary.resolve())}
        # Root declares the frozen local executable; no shell or user-source arguments.
        installed = subprocess.run(  # noqa: S603
            [str(executable.parent / "python"), "-c",
             "from importlib.metadata import version; print(version('hindsight-api-slim'))"],
            env=env, cwd=folder, user=account.pw_uid, group=account.pw_gid, extra_groups=[],
            check=True, capture_output=True, timeout=15,
        ).stdout.decode().strip()
        if installed != native["version"]:
            raise ValueError("Native service distribution differs from the declared version")
        bridge = HindsightModelBridge(
            folder / "model-http", generation_client=self.client,
            embedding_client=self.retrieval_embedding_client,
            generation_output_bound=self.settings["context_tokens"],
        ).start()
        self._native_bridge = bridge
        env.update(native["environment"])
        env.update({
            "HINDSIGHT_API_DATABASE_URL": database_url,
            "HINDSIGHT_API_DATABASE_SCHEMA": identity,
            "HINDSIGHT_API_LLM_MODEL": self.settings["model"]["model"],
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL": self.settings["embedding"]["model"],
            "HINDSIGHT_API_LLM_BASE_URL": bridge.base_url,
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL": bridge.base_url,
            "HINDSIGHT_API_LLM_API_KEY": bridge.api_key,
            "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": bridge.api_key,
        })
        write_json(folder / "configuration.json", {
            "distribution": native["distribution"], "version": installed,
            "executable": str(executable),
            "entrypoint": "official MemoryEngine/create_app; explicit native embedding retries=0",
            "unix_user": account.pw_name, "uid": account.pw_uid, "home": str(home),
            "environment": {key: value for key, value in env.items() if "API_KEY" not in key},
            "dot_env": "program entrypoint uses explicit environment; no dotenv loading",
            "phase": self.phase,
            "restored_from": str(restore_from) if restore_from is not None else None,
            "models": "original clients and shared continuous ledger; no independent budget",
        })
        (folder / "service.py").write_text(NATIVE_SERVICE_SCRIPT)
        os.chown(folder / "service.py", account.pw_uid, account.pw_gid)
        with (folder / "service.log").open("ab") as log:
            self._native_process = subprocess.Popen(  # noqa: S603
                [str(executable.parent / "python"), str((folder / "service.py").resolve()),
                 str(url.port)],
                cwd=folder, env=env, user=account.pw_uid, group=account.pw_gid,
                extra_groups=[], start_new_session=True, stdout=log, stderr=subprocess.STDOUT,
            )
        self._native_uid = account.pw_uid
        write_json(folder / "started.json", {"pid": self._native_process.pid,
                                               "uid": account.pw_uid, "instance": identity})
        deadline = time.monotonic() + native["startup_timeout"]
        with httpx.Client(timeout=2, trust_env=False) as probe:
            while time.monotonic() < deadline:
                self._check_native_transport()
                if self._native_process.poll() is not None:
                    raise HindsightIngestionIncomplete("native_service_startup_failed")
                try:
                    response = probe.get(str(url.join("/health")))
                    if (response.is_success and response.json().get("status") == "healthy"
                            and self._native_listener_is_owned(url.port)):
                        write_json(folder / "ready.json", response.json())
                        return
                except (httpx.TransportError, ValueError):
                    pass
                time.sleep(0.25)
        raise HindsightIngestionIncomplete("native_service_startup_timeout")

    def _close_native_service(self) -> None:
        process = getattr(self, "_native_process", None)
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=90)
            except subprocess.TimeoutExpired as error:
                raise HindsightIngestionIncomplete("native_service_close_timeout") from error
            assert self._native_uid is not None
            remaining = self._uid_processes(self._native_uid)
            write_json(self.root / "native-service/closed.json", {
                "returncode": process.returncode, "remaining_uid_processes": remaining,
                "processes_closed": not remaining,
            })
            if remaining:
                raise HindsightIngestionIncomplete("native_database_processes_still_running")
        bridge = getattr(self, "_native_bridge", None)
        if bridge is not None:
            bridge.close()

    def _backend(self, service: MemoryService) -> MemoryBackend:
        owner = service.owner
        if owner in self.backends:
            return self.backends[owner]
        backend = self.settings["alignment_backend"]
        location = self.root / "native-banks" / owner
        if backend == "RawRAG-local":
            from milai_lab.baselines.rawrag_local import RawRAGLocal

            value: MemoryBackend = RawRAGLocal(
                location, bank_id=self.settings["alignment_bank_ids"][owner],
                granularity=self.settings["alignment"]["rawrag"]["granularity"],
            )
        elif backend == "Hindsight-native-local-recall":
            from milai_lab.integrations.memory.hindsight import HindsightBackend

            self._start_native_service()
            value = HindsightBackend(
                location, bank_id=self.settings["alignment_bank_ids"][owner],
                **self.settings["alignment"]["hindsight"],
            )
        else:
            from milai_lab.methods.milai_memory_only import MiLAiMemoryBackend

            def maintain(session: MemorySession, key: str) -> list[str]:
                observed = ObservedSession(session.session_id, session.date, session.turns)
                return super(AlignmentRun, self).maintain(service, observed, key)

            def retrieve(question: str, date: str, key: str, limit: int) -> list[dict[str, Any]]:
                return self.retrieve_material(service, question, date, key, limit=limit)

            value = MiLAiMemoryBackend(
                maintain=maintain, retrieve=retrieve,
                maintenance_result=lambda key: read_json(
                    self.root / "maintenance" / key / "complete.json"),
                retrieval_native=lambda key: read_json(
                    self.root / "http" / key / "retrieval-native.json"),
                usage=lambda: dict(self.budget.state),
            )
        self.backends[owner] = value
        return value

    def maintain(self, service: MemoryService, observed: ObservedSession, key: str) -> list[str]:
        self._evaluation_key = key
        receipt = self._backend(service).ingest(observed, key=key)
        write_json(self.root / "native" / key / "ingestion.json", receipt)
        self._check_native_transport()
        if (not receipt["completed"]
                and self.settings["alignment_backend"] != "MiLAi-memory-only"):
            raise RuntimeError("Native ingestion not completed; current QA cannot proceed")
        # Existing MiLAi known partial maintenance has settled receipts and keeps
        # its natural history. Unknown writes/Store failures propagate before a
        # return; a recorded gap is neither retried nor called semantic success.
        return receipt["session_output"] or []

    def answer(self, service: MemoryService, question: str, date: str, key: str) -> str:
        path = self.root / "native" / key / "retrieval.json"
        if path.exists():
            retrieval = read_json(path)
        else:
            retrieval = self._backend(service).retrieve(
                question, date, key=key, limit=self.settings["alignment"]["qa_top_k"],
            )
            write_json(path, retrieval)
        self._check_native_transport()
        # The actual return is retained intact. The common Reader resolves only
        # read-only positions in this saved pool, without a new retrieval.
        cached_response = (self.root / "http" / key / "response.json").exists()
        answer, used = self.answer_material(
            question, date, key, retrieval["materials"],
            snapshot_id=str(path.relative_to(self.root)),
        )
        if (self.settings["alignment_backend"] == "MiLAi-memory-only"
                and service.memory_profile == "unified_v1"):
            from milai_lab.memory.activation import ActivationIndex

            index = ActivationIndex(service)
            for material in used:
                if "record_id" in material:
                    index.record_use(material["record_id"], request_id=key, cached=cached_response)
        return answer

    def _score_retrieval(self, service: MemoryService, query: str) -> list[str]:
        if not self.reference_retrieval_supported:
            return []
        # Reference text can issue handles and populate search caches. Preserve
        # the actual session state once and perform these evaluator-only reads
        # in its own Store; none of those effects re-enter the method bank.
        folder = self.root / "evaluation-views" / self._evaluation_key
        folder.mkdir(parents=True, exist_ok=True)
        database = folder / "memory.sqlite"
        if not database.exists():
            with sqlite3.connect(database) as destination:
                service.store.conn.backup(destination)
            write_json(folder / "view.json", {
                "session_key": self._evaluation_key, "owner": service.owner,
                "namespace": list(service.namespace), "purpose": "evaluator-only-update-K10",
                "source": "actual session state after current predictions; no future ingestion",
            })
        with SqliteStore.from_conn_string(str(database)) as store:
            isolated = MemoryService(
                store, service.namespace, service.owner, folder / "memory.lock",
                mutation_contract=service.mutation_contract,
                candidate_contract=service.candidate_contract,
                semantic_retriever=self._semantic_retriever(),
                memory_profile=service.memory_profile, memory_ranking=service.memory_ranking,
            )
            return super()._score_retrieval(isolated, query)

    def _reader_messages(
        self, question: str, date: str, memories: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        return reader_messages(
            question, date, memories,
            memory_view=("source_history" if self.settings["alignment_backend"] == "RawRAG-local"
                         else "retained_state"),
            projection=self.settings.get("reader_projection", "legacy"),
        )

    def halumem(self, phase: str = "all") -> dict[str, Any]:
        result = super().halumem(phase)
        if phase == "predict":
            return result
        result["backend_capabilities"] = {
            "session_output": "supported" if self.session_output_supported else "N/A",
            "reference_update_state": (
                "supported-isolated-view" if self.reference_retrieval_supported else "N/A"
            ),
        }
        if not self.session_output_supported:
            for name in ("memory_integrity", "memory_accuracy", "memory_extraction_f1"):
                result["overall_score"][name] = None
        if not self.reference_retrieval_supported:
            result["overall_score"]["memory_update"] = None
            result["overall_score"]["memory_type_accuracy"] = None
        rows = result["question_answering_records"]
        labels = Counter(row["result_type"] or "invalid" for row in rows
                         if row["system_response"] is not None)
        per_user = {}
        for owner in self.settings["halumem"]["users"]:
            actual = [row for row in rows if row["uuid"] == owner]
            per_user[owner] = {
                "correct": sum(row["result_type"] == "Correct" for row in actual),
                "opportunities": len(actual),
                "missing": sum(row["system_response"] is None for row in actual),
                "invalid": sum(row["system_response"] is not None
                               and row["result_type"] is None for row in actual),
            }
        common = {
            "status": "SCORED_SAVED_PREDICTIONS", "backend": self.settings["alignment_backend"],
            "protocol": self.settings["alignment"],
            "correct": sum(row["result_type"] == "Correct" for row in rows),
            "opportunities": len(rows),
            "missing": sum(row["system_response"] is None for row in rows),
            "labels": dict(labels), "per_user": per_user,
            "backend_capabilities": result["backend_capabilities"],
            "official_labels": "unchanged; source conflicts require separate evidence review",
            "semantic_advantage": "unchecked", "native_answer_result": None,
        }
        write_json(self.root / "common-qa-results.json", common)
        write_json(self.root / "halumem-official-results.json", result)
        return common

    def close(self) -> None:
        self._resources_settled = False
        failures: list[tuple[str, BaseException]] = []
        for owner, backend in self.backends.items():
            try:
                backend.close()
            except BaseException as error:
                failures.append((owner, error))
        try:
            self._close_native_service()
        except BaseException as error:
            failures.append(("native-service", error))
        if failures:
            if all(isinstance(error, HindsightIngestionIncomplete) and error.resources_settled
                   for _, error in failures):
                super().close()
                self._resources_settled = True
                raise failures[0][1]
            write_json(self.root / "resource-unsettled.json", {
                "status": "RESOURCE_UNSETTLED",
                "backend_errors": [
                    {"owner": owner, "type": type(error).__name__, "message": str(error)}
                    for owner, error in failures
                ],
                "original_lease_released": False,
                "next_dispatch": "Root must confirm native work has stopped or completed",
                "process_exit": "The OS may release the lease; this is not native completion",
            })
            raise failures[0][1]
        super().close()
        self._resources_settled = True


def run_alignment_arm(
    config: dict[str, Any], root: Path, backend: str, phase: str, *, benchmark: str = "halumem",
) -> None:
    """One explicit arm/phase dispatch; no automatic scoring or retries."""
    if benchmark not in BENCHMARKS:
        raise ValueError("Unknown declared alignment benchmark")
    if phase not in {"predict", "score"}:
        raise ValueError("Predict and score require separate explicit dispatch")
    settings = alignment_settings(config, backend)
    prepared = read_json(root / "alignment-prepared.json")
    if prepared["configuration"] != config:
        raise ValueError("Comparison configuration differs from its preparation")
    if prepared.get("benchmark", "halumem") != benchmark:
        raise ValueError("Comparison benchmark differs from its preparation")
    # Scoring consumes this backend's saved predictions. Unfinished peer arms
    # do not change its Judge policy or authorize a cross-backend comparison.
    resource_backends = config["alignment"]["backends"] if phase == "predict" else [backend]
    for selected in resource_backends:
        if (root / selected / "resource-unsettled.json").exists():
            raise ValueError("Native resource closure is unconfirmed; Root must resolve it first")
        native_root = root / selected / "native-service"
        if (native_root / "started.json").exists():
            closed = native_root / "closed.json"
            if not closed.exists() or read_json(closed).get("processes_closed") is not True:
                raise ValueError("Previous native service closure is unconfirmed; Root must inspect"
                                 " before dispatch")
    try:
        native_uid = pwd.getpwnam(config["alignment"]["hindsight_service"]["unix_user"]).pw_uid
    except KeyError:
        native_uid = None
    if native_uid is not None and _native_uid_processes(native_uid):
        raise ValueError("Dedicated native service processes still exist; Root must resolve them")
    settings["alignment_bank_ids"] = prepared["bank_ids"][backend]
    settings["alignment_benchmark"] = benchmark
    output = root / backend
    terminal = output / f"terminal-{phase}.json"
    if terminal.exists():
        raise ValueError("Closed arm/phase already exists; do not repeat")
    if phase == "score":
        prior = output / "terminal-predict.json"
        prediction = read_json(prior) if prior.exists() else {}
        if prediction.get("status") != "PREDICTIONS_SAVED":
            raise ValueError("Selected backend must close predictions before scoring")
        if prediction.get("resources_settled") is not True:
            raise ValueError("Selected backend resource closure is unconfirmed; do not score")
    execution = AlignmentRun(settings, output, phase=phase)
    result: dict[str, Any] | None = None
    run_error: BaseException | None = None
    close_error: BaseException | None = None
    try:
        if benchmark == "halumem":
            result = execution.halumem(phase)
        else:
            predictions = execution.longmemeval(phase)
            result = {
                "benchmark": benchmark, "cases": len(predictions),
                "complete_answers": sum(isinstance(row["hypothesis"], str) for row in predictions),
                "missing_answers": sum(row["hypothesis"] is None for row in predictions),
                "judge_calls": sum(isinstance(row.get("official_verdict"), str)
                                   for row in predictions),
            }
            if phase == "score":
                result.update(correct=sum(row["autoeval_label"] is True for row in predictions),
                              opportunities=len(predictions))
    except BaseException as error:
        run_error = error
    try:
        execution.close()
    except BaseException as error:
        close_error = error
        if (not getattr(execution, "_resources_settled", False)
                and not (output / "resource-unsettled.json").exists()):
            write_json(output / "resource-unsettled.json", {
                "status": "RESOURCE_UNSETTLED",
                "error": {"type": type(error).__name__, "message": str(error)},
                "next_dispatch": "Root must confirm resource closure before another dispatch",
            })
    if run_error is not None or close_error is not None:
        resources_settled = bool(getattr(execution, "_resources_settled", False))
        write_json(terminal, {
            "status": ("RESOURCE_UNSETTLED"
                       if close_error is not None and not resources_settled else "FAILED"),
            "phase": phase, "backend": backend,
            "benchmark": benchmark,
            "resources_settled": resources_settled,
            "error": ({"type": type(run_error).__name__, "message": str(run_error)}
                      if run_error is not None else None),
            "close_error": ({"type": type(close_error).__name__, "message": str(close_error)}
                            if close_error is not None else None),
            "saved_outputs": result,
            "no_automatic_retry": True,
        })
        if run_error is not None:
            if close_error is not None:
                run_error.add_note(f"Resource closure also failed: {close_error}")
            raise run_error
        assert close_error is not None
        raise close_error
    write_json(terminal, {
        "status": "PREDICTIONS_SAVED" if phase == "predict" else "SCORED",
        "phase": phase, "backend": backend, "benchmark": benchmark,
        "result": result, "resources_settled": True,
    })
