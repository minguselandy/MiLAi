"""Typed Lab adapter over unchanged transactional World; no Product or scorer access."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from v0218_world import World, WorldError, digest
from v0220_action_contract import ActionContract, ContractError
from v0220_dispatch_journal import DispatchJournal, UnresolvedDispatch


class ActionAdapter:
    def __init__(self, world: World, contract: ActionContract):
        self.world, self.contract = world, contract
        self._verify_contract()
        self.journal = DispatchJournal(world)

    def _verify_contract(self) -> None:
        actual = ActionContract.from_public(
            self.world.snapshot(), enable_note=self.contract.enable_note
        )
        if actual.fingerprint != self.contract.fingerprint:
            raise ContractError("PUBLIC_CONTRACT_DRIFT")

    def read(self, resource: str) -> dict:
        self._verify_contract()
        return self.contract.validate_response(
            {
                **self.world.read(resource),
                "version_domain": "WORLD",
                "committed": False,
                "status": "PUBLIC_OBSERVATION",
                "business_effect": False,
            }
        )

    def operation_status(self, operation_id: str) -> dict:
        """Authorized durable query; absence is deliberately not an uncommitted claim."""
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ContractError("OPERATION_ID_REQUIRED")
        with sqlite3.connect(self.world.path) as db:
            db.execute("BEGIN")
            self.world._state(
                db
            )  # Same Lab authority check and transaction as the queried receipt.
            row = db.execute(
                "SELECT request_hash,receipt FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            rejected = db.execute(
                "SELECT receipt FROM v0220_dispatch WHERE id=?", (operation_id,)
            ).fetchone()
        if row is None:
            if rejected and rejected[0] is not None:
                return self.contract.validate_response(json.loads(rejected[0]))
            return self.contract.validate_response(
                {
                    "status": "NOT_OBSERVED",
                    "committed": None,
                    "operation_id": operation_id,
                    "version_domain": "WORLD",
                    "retry_requires": "QUERY_OR_EXACT_REPLAY_ONLY",
                }
            )
        return self._committed(json.loads(row[1]), row[0])

    def _committed(self, receipt: dict, request_hash: str) -> dict:
        return self.contract.validate_response(
            {
                **receipt,
                "committed": True,
                "version_domain": "WORLD",
                "request_sha256": request_hash,
                "business_effect": True,
                "retry_requires": "NONE",
            }
        )

    def rejected(
        self,
        code: str,
        *,
        operation_id: str | None,
        path: list | None = None,
        rule: str = "",
        expected_version: int | None = None,
    ) -> dict:
        conflict = code == "VERSION_CONFLICT"
        receipt = {
            "status": "ACTION_REJECTED",
            "code": code,
            "committed": False,
            "operation_id": operation_id,
            "version_domain": "WORLD",
            "path": path or [],
            "rule": rule,
            "retryable": code not in {"SCOPE_DENIED", "PUBLIC_CONTRACT_DRIFT"},
            "retry_requires": "READ_AND_REVALIDATE"
            if conflict
            else "CORRECT_REQUEST_NO_AUTO_RETRY",
            "business_effect": False,
        }
        if conflict:
            receipt.update(
                expected_version=expected_version, current_version=self.world.snapshot()["version"]
            )
        return self.contract.validate_response(receipt)

    def execute(self, action: dict, *, operation_id: str) -> dict:
        """Host owns operation_id; exact retry calls this with identical action and ID.

        Revalidation lives at this execution boundary, not just in model decoding.
        A previously committed identical operation returns its original receipt even
        after later business versions; a new logical action is never silently rebased.
        """
        dispatched = False
        try:
            self._verify_contract()
            value = self.contract.validate(action)
            if value["action"] not in {"put_record", "request_clarification"}:
                raise ContractError("BUSINESS_ACTION_REQUIRED")
            if not isinstance(operation_id, str) or not operation_id.strip():
                raise ContractError("HOST_OPERATION_ID_REQUIRED")
            args = value["arguments"]
            request = {
                "operation_id": operation_id,
                "expected_version": args["expected_version"],
                "action": value["action"],
                "object_id": args["object_id"],
                "data": args["data"],
                "scope": self.world.scope,
            }
            prior = self.journal.begin(operation_id, request)
            if prior is not None:
                return self.contract.validate_response(prior)
            dispatched = True
            receipt = self.world.act(operation_id=operation_id, action=value["action"], **args)
            result = self._committed(receipt, digest(request))
            self.journal.settle(operation_id, result)
            return result
        except ContractError as exc:
            if dispatched:
                return self.unknown(operation_id)
            return self.rejected(exc.code, operation_id=operation_id, path=exc.path, rule=exc.rule)
        except WorldError as exc:
            code = str(exc)
            if code == "VERSION_CONFLICT_RELOAD_CURRENT_STATE":
                code = "VERSION_CONFLICT"
            receipt = self.rejected(
                code,
                operation_id=operation_id,
                expected_version=action.get("arguments", {}).get("expected_version"),
            )
            if dispatched:
                try:
                    self.journal.settle(operation_id, receipt)
                except (ContractError, sqlite3.Error, OSError):
                    return self.unknown(operation_id)
            return receipt
        except UnresolvedDispatch:
            return self.contract.validate_response(
                {
                    **self.unknown(operation_id),
                    "code": "UNRESOLVED_PRIOR_OPERATION",
                    "dispatch_performed": False,
                }
            )
        except (sqlite3.Error, OSError):
            # The exception may follow a commit. Missing response does not prove non-execution.
            return self.unknown(operation_id)

    def unknown(self, operation_id: str) -> dict:
        return self.contract.validate_response(
            {
                "status": "COMMIT_UNKNOWN",
                "committed": None,
                "operation_id": operation_id,
                "version_domain": "WORLD",
                "retry_requires": "QUERY_OR_EXACT_REPLAY_ONLY",
                "stop_new_logical_writes": True,
            }
        )

    def acknowledge_committed_operation(self, operation_id: str) -> dict:
        """Trusted Host recovery: read real receipt, then journal its delivery acknowledgment.

        No model-supplied receipt or current-head inference. The public query itself
        is read-only; this updates only local dispatch metadata, never world/ledger.
        """
        receipt = self.operation_status(operation_id)
        if receipt["committed"] is True:
            self.journal.settle(operation_id, receipt)
        return receipt

    def clone(self, destination: Path, new_scope: str) -> ActionAdapter:
        if self.journal.unresolved():
            raise UnresolvedDispatch("CANNOT_CLONE_UNRESOLVED_WORLD")
        adapter = ActionAdapter(self.world.clone(destination, new_scope), self.contract)
        adapter.journal.clear_cloned_operation_ids()
        return adapter
