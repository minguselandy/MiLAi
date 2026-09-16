from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from scripts import dg13u_u1_resource_registry as resources


@dataclass
class FakeRecoveryPlan:
    replacements: list[tuple[str, int, str, int, str]] = field(default_factory=list)
    fail_replacement: bool = False
    plan_path: str = "/tmp/fake-plan.json"
    sha256: str | None = "a" * 64

    def replace_process(
        self,
        role: str,
        expected_pid: int,
        expected_marker: str,
        new_pid: int,
        new_marker: str,
    ) -> None:
        if self.fail_replacement:
            raise RuntimeError("synthetic durable CAS failure")
        self.replacements.append(
            (role, expected_pid, expected_marker, new_pid, new_marker)
        )

    def binding(self) -> dict[str, str]:
        return {
            "schema": "milai.dg13u.u1-recovery-resource-plan.v1",
            "path": self.plan_path,
            "sha256": str(self.sha256),
        }


def test_generic_resources_keep_snapshot_reverse_cleanup_and_external_contract() -> (
    None
):
    events: list[str] = []
    present = {"first", "second"}
    registry = resources.ResourceRegistry("dg13u-u1-resource-helper")
    registry.register(
        resources.ResourceHandle(
            "external_vllm",
            "127.0.0.1:7860",
            resources.ResourceOwnership.PRESERVED_EXTERNAL,
        )
    )
    for name in ("first", "second"):
        registry.register(
            resources.ResourceHandle(
                "synthetic",
                f"resource/{name}",
                resources.ResourceOwnership.RUN_OWNED,
                cleanup=lambda name=name: (
                    events.append(name),
                    present.remove(name),
                ),
                absent=lambda name=name: name not in present,
            )
        )

    snapshot = registry.snapshot()
    assert isinstance(snapshot, tuple)
    assert [handle.identity for handle in snapshot] == [
        "127.0.0.1:7860",
        "resource/first",
        "resource/second",
    ]

    receipt = registry.cleanup_all()

    assert receipt["status"] == "PASS"
    assert events == ["second", "first"]
    assert [row["state"] for row in receipt["items"]] == [
        "removed",
        "removed",
        "preserved_external",
    ]
    with pytest.raises(
        resources.ResourceRegistryError, match="cleanup is not repeatable"
    ):
        registry.cleanup_all()


def test_replace_process_freezes_identity_and_stale_cleanup_cannot_touch_new() -> None:
    present = {("mcp-broker", 101, "9001")}
    cleanup_calls: list[resources.ProcessGeneration] = []

    def cleanup(generation: resources.ProcessGeneration) -> None:
        cleanup_calls.append(generation)
        present.discard((generation.role, generation.pid, generation.marker))

    def absent(generation: resources.ProcessGeneration) -> bool:
        return (generation.role, generation.pid, generation.marker) not in present

    registry = resources.ResourceRegistry("dg13u-u1-generation")
    old = registry.register_process("mcp-broker", 101, "9001", cleanup, absent)
    stale_handle = registry.snapshot()[0]
    present.remove((old.role, old.pid, old.marker))
    present.add(("mcp-broker", 202, "9002"))

    new = registry.replace_process(
        "mcp-broker",
        expected_pid=101,
        expected_marker="9001",
        new_pid=202,
        new_marker="9002",
        cleanup=cleanup,
        absent=absent,
    )

    assert new == resources.ProcessGeneration("mcp-broker", 202, "9002", 2)
    assert resources.process_snapshot_by_role(registry.snapshot()) == {
        "mcp-broker": new
    }
    assert stale_handle.cleanup is not None
    stale_handle.cleanup()
    assert cleanup_calls == []
    assert ("mcp-broker", 202, "9002") in present

    receipt = registry.cleanup_all()

    assert cleanup_calls == [new]
    assert present == set()
    assert receipt["status"] == "PASS"
    assert [row["identity"] for row in receipt["items"]] == ["process/mcp-broker:202"]


@pytest.mark.parametrize(
    ("role", "expected_pid", "expected_marker", "message"),
    [
        ("host-adapter", 301, "7001", "not registered"),
        ("mcp-broker", 999, "7001", "CAS mismatch"),
        ("mcp-broker", 301, "9999", "CAS mismatch"),
    ],
)
def test_replace_process_rejects_missing_or_wrong_generation(
    role: str,
    expected_pid: int,
    expected_marker: str,
    message: str,
) -> None:
    present: set[tuple[str, int, str]] = set()
    registry = resources.ResourceRegistry("dg13u-u1-negative-twin")
    registry.register_process(
        "mcp-broker",
        301,
        "7001",
        lambda generation: present.discard(
            (generation.role, generation.pid, generation.marker)
        ),
        lambda generation: (
            (
                generation.role,
                generation.pid,
                generation.marker,
            )
            not in present
        ),
    )

    with pytest.raises(resources.ResourceRegistryError, match=message):
        registry.replace_process(
            role,
            expected_pid,
            expected_marker,
            302,
            "7002",
            lambda _generation: None,
            lambda _generation: True,
        )

    current = resources.process_snapshot_by_role(registry.snapshot())
    assert current["mcp-broker"] == resources.ProcessGeneration(
        "mcp-broker", 301, "7001", 1
    )


def test_replace_process_rejects_live_old_generation_without_mutation() -> None:
    old_key = ("host-adapter", 401, "8001")
    present = {old_key}
    registry = resources.ResourceRegistry("dg13u-u1-live-old")
    registry.register_process(
        *old_key,
        cleanup=lambda generation: present.discard(
            (generation.role, generation.pid, generation.marker)
        ),
        absent=lambda generation: (
            (
                generation.role,
                generation.pid,
                generation.marker,
            )
            not in present
        ),
    )

    with pytest.raises(resources.ResourceRegistryError, match="must be absent"):
        registry.replace_process(
            "host-adapter",
            401,
            "8001",
            402,
            "8002",
            lambda _generation: None,
            lambda _generation: True,
        )

    assert (
        resources.process_snapshot_by_role(registry.snapshot())[
            "host-adapter"
        ].generation
        == 1
    )


def test_repeated_process_replacement_fails_closed_on_stale_expectation() -> None:
    registry = resources.ResourceRegistry("dg13u-u1-repeat-cas")
    registry.register_process(
        "host-adapter",
        501,
        "8101",
        lambda _generation: None,
        lambda _generation: True,
    )
    registry.replace_process(
        "host-adapter",
        501,
        "8101",
        502,
        "8102",
        lambda _generation: None,
        lambda _generation: True,
    )

    with pytest.raises(resources.ResourceRegistryError, match="CAS mismatch"):
        registry.replace_process(
            "host-adapter",
            501,
            "8101",
            503,
            "8103",
            lambda _generation: None,
            lambda _generation: True,
        )

    assert resources.process_snapshot_by_role(registry.snapshot())[
        "host-adapter"
    ] == resources.ProcessGeneration("host-adapter", 502, "8102", 2)


def test_recovery_plan_cas_precedes_in_memory_process_replacement() -> None:
    recovery = FakeRecoveryPlan()
    registry = resources.ResourceRegistry("dg13u-u1-recovery-cas", recovery)
    registry.register_process(
        "mcp-broker",
        601,
        "8201",
        lambda _generation: None,
        lambda _generation: True,
    )

    replacement = registry.replace_process(
        "mcp-broker",
        601,
        "8201",
        602,
        "8202",
        lambda _generation: None,
        lambda _generation: True,
    )

    assert recovery.replacements == [("mcp-broker", 601, "8201", 602, "8202")]
    assert replacement.generation == 2
    assert registry.cleanup_all()["recovery_plan"]["status"] == "PASS"


def test_recovery_plan_failure_leaves_old_in_memory_generation_current() -> None:
    recovery = FakeRecoveryPlan(fail_replacement=True)
    registry = resources.ResourceRegistry("dg13u-u1-recovery-fail", recovery)
    old = registry.register_process(
        "host-adapter",
        701,
        "8301",
        lambda _generation: None,
        lambda _generation: True,
    )

    with pytest.raises(
        resources.ResourceRegistryError, match="recovery process replacement failed"
    ):
        registry.replace_process(
            "host-adapter",
            701,
            "8301",
            702,
            "8302",
            lambda _generation: None,
            lambda _generation: True,
        )

    assert resources.process_snapshot_by_role(registry.snapshot()) == {
        "host-adapter": old
    }


def test_generic_registration_negative_twins_remain_fail_closed() -> None:
    registry = resources.ResourceRegistry("dg13u-u1-register-negative")
    with pytest.raises(resources.ResourceRegistryError, match="requires cleanup"):
        registry.register(
            resources.ResourceHandle(
                "process",
                "process/no-cleanup",
                resources.ResourceOwnership.RUN_OWNED,
            )
        )
    with pytest.raises(resources.ResourceRegistryError, match="external resource"):
        registry.register(
            resources.ResourceHandle(
                "external_vllm",
                "127.0.0.1:7860",
                resources.ResourceOwnership.PRESERVED_EXTERNAL,
                cleanup=lambda: None,
                absent=lambda: True,
            )
        )
