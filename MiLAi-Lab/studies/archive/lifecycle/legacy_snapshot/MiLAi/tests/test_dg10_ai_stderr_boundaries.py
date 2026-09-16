from __future__ import annotations

import pytest

from scripts import dg10_authorization as authorization
from scripts import import_dg10_ai_test_access as test_access
from scripts import import_dg10_candidate4_ai_audits as r0_r2
from scripts import import_dg10_r3_ai_review as r3

KNOWN = (
    b"2026-08-22T10:56:05.429515Z ERROR codex_models_manager::manager: "
    b"failed to refresh available models: timeout waiting for child process to exit\n"
)


@pytest.mark.parametrize(
    ("validator", "error_type"),
    [
        (r0_r2._require_nonfatal_ai_stderr, r0_r2.AuditImportError),
        (authorization._require_nonfatal_ai_stderr, authorization.AuthorizationError),
        (test_access._require_nonfatal_ai_stderr, test_access.TestAccessImportError),
        (r3._require_nonfatal_ai_stderr, r3.R3ImportError),
    ],
    ids=["r0-r2-import", "authorization", "test-access-import", "r3-import"],
)
def test_ai_stderr_boundaries_reject_duplicate_known_diagnostics(
    validator: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type, match="stderr contains an unclassified error"):
        validator(KNOWN + KNOWN)  # type: ignore[operator]


@pytest.mark.parametrize(
    "validator",
    [
        r0_r2._require_nonfatal_ai_stderr,
        authorization._require_nonfatal_ai_stderr,
        test_access._require_nonfatal_ai_stderr,
        r3._require_nonfatal_ai_stderr,
    ],
    ids=["r0-r2-import", "authorization", "test-access-import", "r3-import"],
)
def test_ai_stderr_boundaries_accept_one_exact_known_diagnostic(validator: object) -> None:
    validator(KNOWN)  # type: ignore[operator]
