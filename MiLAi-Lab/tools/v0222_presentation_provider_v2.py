"""Wire the scoped Transport into unchanged B1/D11 full acceptance methods.

Only construction and secondary stop-error preservation are versioned here.
Request reconstruction, full Schema/CAS/intent, public receipt and World checks,
release evidence and close behavior are inherited from the frozen Provider.
This module never changes that Provider's globals or starts a model service.
"""

from __future__ import annotations

import copy
from pathlib import Path

from v0218_world import digest
from v0220_provider_hardened import ProviderStop
from v0220_session import SessionContract
from v0222_presentation_provider import FullProvider as OriginalAcceptance


class FullProvider(OriginalAcceptance):
    def __init__(self, root: Path, *, batch, episode: str, world=None, transport=None):
        self.root, self.batch, self.episode = root, batch, episode
        self.world, self.turn, self.writes, self.readback = world, 0, 0, False
        self.stopped, self.closed, self.pending_wire_hash = False, False, None
        self.outputs, self.actions, self.receipt_hashes = [], [], []
        try:
            from v0222_presentation_transport_v2 import Transport

            claim = batch.admit(episode)
            self.spec = copy.deepcopy(batch.spec(episode))
            if (
                claim["stage"] not in {"P3", "P4"}
                or self.spec["stage"] != claim["stage"]
                or self.spec["id"] != episode
                or batch.plan.get("selected_decoder") != "D11"
                or batch.plan.get("selected_presentation") != "B1"
            ):
                raise ProviderStop("ONLY_SELECTED_PRESENTATION_FULL_STAGES")
            if self.spec["stage"] == "P4":
                if (
                    world is None
                    or world.path.resolve() != batch.root / "worlds" / (episode + ".sqlite")
                    or world.scope != self.spec["scope"]
                ):
                    raise ProviderStop("FROZEN_INTENT_AND_WORLD_BINDING_REQUIRED")
                self.initial = world.snapshot()
                if (
                    digest(self.initial) != self.spec["initial_state_sha256"]
                    or self.initial["version"] != 0
                    or self.initial["records"]
                    or world.ledger()
                ):
                    raise ProviderStop("P4_REQUIRES_FROZEN_EMPTY_INITIAL_WORLD")
                self.contract = SessionContract.from_public(self.initial)
            elif world is not None:
                raise ProviderStop("P3_VALIDATE_ONLY_NO_WORLD")
            self.provider = Transport(
                root,
                batch=batch,
                episode=episode,
                preflight=self._wire_preflight,
                transport=transport,
            )
        except BaseException as exc:
            self._stop(exc)
            raise

    def _stop(self, exc: BaseException) -> None:
        self.stopped = True
        code = str(exc) if isinstance(exc, ProviderStop) else type(exc).__name__
        try:
            self.batch.stop(code)
        except BaseException as secondary:
            # A failed stop cannot replace the original acceptance/I/O failure.
            exc.add_note("SECONDARY_STOP_FAILURE: " + type(secondary).__name__)
