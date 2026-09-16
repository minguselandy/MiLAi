"""Original preflight parity and contract closure; no real fixture or HTTP."""

import ast
import inspect
import sys
import textwrap
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import preflight_v0222_scoped_cpu as old
import preflight_v0224_k3_cpu as new


def tree(fn):
    return ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]


def test_complete_original_body_with_explicit_authority_and_efficiency_delta():
    original = textwrap.dedent(inspect.getsource(old.preflight))
    original = original.replace(
        "    batch = None\n", "    preflight_started = time.monotonic()\n    batch = None\n", 1
    )
    original = original.replace(
        "deadline = time.monotonic() + PREFLIGHT_SECONDS[stage]",
        'deadline = time.monotonic() + (batch.auth["expires_unix"] - time.time())',
    )
    original = original.replace(
        '"preflight_window_seconds": PREFLIGHT_SECONDS[stage],',
        "\n".join(
            [
                '"historical_preflight_window_seconds": PREFLIGHT_SECONDS[stage],',
                '            "cpu_efficiency_window_enforced": False,',
                '            "authorization_expires_unix": batch.auth["expires_unix"],',
                '            "elapsed_before_report_seconds": '
                'time.monotonic() - preflight_started,',
            ]
        ),
    )
    before, after = ast.parse(original).body[0], tree(new.preflight)
    after.args.kwonlyargs = []
    after.args.kw_defaults = []
    after.body = [n for n in after.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    for node in ast.walk(after):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Batch"
        ):
            assert len(node.keywords) == 1 and node.keywords[0].arg == "static_authority"
            node.keywords = []
    assert ast.dump(before) == ast.dump(after)


def test_guard_before_business_imports_and_no_caller_transport():
    body = tree(new.preflight).body
    assert isinstance(body[0], ast.ImportFrom) and body[0].module == "v0222_scoped_cpu_guard"
    assert ast.unparse(body[1]) == "require_cpu_network_guard()"
    assert list(inspect.signature(new.preflight).parameters) == [
        "root",
        "binding",
        "stage",
        "static_authority",
    ]
    main = tree(new.main).body
    assert ast.unparse(main[1]) == "enable_cpu_network_guard()"
    with pytest.raises(RuntimeError, match="FRESH_CPU_PROCESS_NETWORK_GUARD_REQUIRED"):
        new.preflight(Path("/nonexistent"), "0" * 64, "P3", static_authority=object())


@pytest.mark.parametrize("failure", [None, "recheck", "body_and_recheck"])
def test_main_rechecks_contract_and_preserves_body_primary(monkeypatch, tmp_path, failure):
    import run_v0224_k3_cpu as runner
    import v0222_scoped_cpu_guard as guard
    import v0223_transaction_primary_fix as fix

    monkeypatch.setattr(guard, "enable_cpu_network_guard", lambda: None)
    monkeypatch.setattr(fix, "installed_transaction_fix", nullcontext)
    contract = {"root": str(tmp_path / "absent"), "binding_sha256": "a" * 64}
    authority = object()
    calls, stopped = [], []
    primary = RuntimeError("business-primary")

    def load(path, digest):
        calls.append((path, digest))
        if len(calls) == 2 and failure:
            raise ValueError("final-pin-drift")
        return contract, authority

    def preflight(root, binding, stage, *, static_authority):
        assert root == Path(contract["root"]) and binding == contract["binding_sha256"]
        assert stage == "P4" and static_authority is authority
        if failure == "body_and_recheck":
            raise primary
        return {"status": "G_PREFLIGHT_PASS"}

    monkeypatch.setattr(runner, "load_contract", load)
    monkeypatch.setattr(runner, "stop_batch", lambda *args: stopped.append(args))
    monkeypatch.setattr(new, "preflight", preflight)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "preflight",
            "--contract-path",
            str(tmp_path / "contract"),
            "--contract-sha256",
            "b" * 64,
            "--stage",
            "P4",
        ],
    )
    if failure:
        with pytest.raises((RuntimeError, ValueError)) as exc:
            new.main()
        if failure == "body_and_recheck":
            assert (
                exc.value is primary
                and "SECONDARY_PREFLIGHT_CONTRACT_RECHECK" in primary.__notes__[0]
            )
        else:
            assert str(exc.value) == "final-pin-drift"
        assert len(stopped) == 1
    else:
        assert new.main() == 0 and not stopped
    assert len(calls) == 2 and calls[0] == calls[1]
    assert not Path(contract["root"]).exists()
