"""Explicit DEV correctness delta shared by both K2 arms, not a speed candidate.

Keep the original SQLite statements, ordering and commit/rollback boundaries.
An active failure retains identity; failed cleanup is secondary evidence. A
close failure after successful commit still fails and does not undo that commit.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

import v0221_http_batch as original_batch

_PREFIXES = ("v0221_", "run_v0221_", "v0222_", "run_v0222_", "v0223_", "run_v0223_")


@contextmanager
def corrected_transaction(self):
    db = original_batch.sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5)
    db.row_factory = original_batch.sqlite3.Row
    primary = None
    try:
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        if (
            db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0]
            != self.binding_sha
        ):
            raise original_batch.ProviderStop("COORDINATOR_BINDING_DRIFT")
        yield db
        db.commit()
    except BaseException as exc:
        primary = exc
        try:
            db.rollback()
        except BaseException as cleanup:
            primary.add_note("SECONDARY_TRANSACTION_ROLLBACK_FAILURE: " + repr(cleanup))
        raise
    finally:
        try:
            db.close()
        except BaseException as cleanup:
            if primary is None:
                raise
            primary.add_note("SECONDARY_TRANSACTION_CLOSE_FAILURE: " + repr(cleanup))


def _targets():
    """Named module aliases and explicitly stored class methods, not inherited copies."""
    yielded = set()
    for name, module in tuple(sys.modules.items()):
        if module is None or not name.startswith(_PREFIXES):
            continue
        for alias, value in tuple(vars(module).items()):
            key = (id(module), alias)
            if key not in yielded:
                yielded.add(key)
                yield module, alias, value
            if isinstance(value, type) and value.__module__.startswith(_PREFIXES):
                for member, method in tuple(vars(value).items()):
                    key = (id(value), member)
                    if key not in yielded:
                        yielded.add(key)
                        yield value, member, method


@contextmanager
def installed_transaction_fix():
    """Patch inherited Batch.transaction and named loaded aliases; restore on exit.

    Install before constructing workers. Previously captured bound methods are
    outside this API; the runner must use the installed named class stack.
    """
    original = original_batch.Batch.transaction
    if original is corrected_transaction:
        raise RuntimeError("TRANSACTION_FIX_INSTALL_MUST_NOT_BE_NESTED")
    targets = tuple(_targets())
    existing = {(id(owner), key) for owner, key, value in targets if value is corrected_transaction}
    changes = []
    try:
        for owner, key, value in targets:
            if value is original:
                changes.append((owner, key, value))
                setattr(owner, key, corrected_transaction)
        yield
    finally:
        for owner, key, value in reversed(changes):
            setattr(owner, key, value)
        for owner, key, value in _targets():
            if value is corrected_transaction and (id(owner), key) not in existing:
                setattr(owner, key, original)
