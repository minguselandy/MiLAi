"""Independent material/storage opt-ins through actual public SDK and runner wiring."""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_v13_2_compact_material import capacity as capacity
from test_v13_2_compact_material import expand, state_clear
from test_v13_2_history_discovery import history, public_turn
from test_v13_2_packet import Embeddings, bound

from milai_lab.methods.grounded_memory import GroundedMemoryRecipe
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.runners import v13_1_d0 as runner


@pytest.mark.parametrize("material", ["full_v1", "compact_v1"])
@pytest.mark.parametrize("storage", ["bank_prefix", "owner_bank_v1"])
def test_public_runner_retains_both_independent_options_and_default_policy(
    tmp_path: Path,
    capacity: HostCapacity,
    monkeypatch: pytest.MonkeyPatch,
    material: str,
    storage: str,
) -> None:
    settings = json.loads(Path("configs/v13-2-e0-normal.json").read_text())
    settings.update(memory_material_profile=material, memory_derived_index_storage=storage)
    policy = runner._recipe_settings(settings)
    assert (
        policy.get("material_profile", "full_v1"),
        policy.get("raw_index_storage", "bank_prefix"),
    ) == (material, storage)
    if material == "full_v1":
        assert "material_profile" not in policy
    if storage == "bank_prefix":
        assert "raw_index_storage" not in policy

    class LocalClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> LocalClient:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr(runner, "VLLMClient", LocalClient)
    with bound.opened(tmp_path) as service, ExitStack() as stack:
        recipe = runner._make_recipe(
            service,
            settings,
            SimpleNamespace(client=SimpleNamespace(capacity=capacity)),
            None,
            lambda event: None,
            stack,
        )
        assert recipe.material_profile == material and recipe.raw_index_storage == storage
        assert (recipe.index_namespace == recipe.namespace) == (storage == "bank_prefix")
        assert recipe.policy.get("material_profile", "full_v1") == material
        assert recipe.policy.get("raw_index_storage", "bank_prefix") == storage


def test_compact_with_detached_store_has_identical_selection_packet_and_paid_cas(
    tmp_path: Path,
    capacity: HostCapacity,
) -> None:
    with bound.opened(tmp_path) as service:
        service.source_backlinks = "enabled"
        memory_id, _ = history(service)
        public_turn(service)
        inline = GroundedMemoryRecipe(
            service, capacity.text_tokens, embeddings=Embeddings(), material_profile="compact_v1"
        )
        first = inline.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        original_index = service.store.get(inline.namespace, "raw_index").value
        state_clear(service, inline)
        embeddings = Embeddings()
        detached = GroundedMemoryRecipe(
            service,
            capacity.text_tokens,
            embeddings=embeddings,
            material_profile="compact_v1",
            raw_index_storage="owner_bank_v1",
        )
        second = detached.prepare_context(
            "PINE_TOKEN", owner="alice", session="s1", turn_id="query"
        )
        assert second["selected"] == first["selected"]
        assert second["packet"] == first["packet"] and second["material"] == first["material"]
        assert second["material_tokens"] <= 2048
        assert service.store.get(inline.namespace, "raw_index").value == original_index
        envelope = service.store.get(detached.index_namespace, "raw_index").value
        assert envelope["status"] == "complete" and envelope["bank_namespace"] == list(
            service.namespace
        )
        assert envelope["index"]["chunks"] == original_index["chunks"]
        assert detached.policy["material_profile"] == "compact_v1"
        assert detached.policy["raw_index_storage"] == "owner_bank_v1"
        current = next(
            unit["record"] for unit in expand(second["packet"]) if unit["type"] == "record"
        )
        assert current["id"] == memory_id
        assert current["candidate_handle"] == service.read(memory_id)["candidate_handle"]
        again = detached.prepare_context("PINE_TOKEN", owner="alice", session="s1", turn_id="query")
        assert again["retrieval_calls"] == 0 and len(embeddings.queries) == 1
        assert again["material"] == second["material"]


@pytest.mark.parametrize("option", ["memory_material_profile", "memory_derived_index_storage"])
def test_each_invalid_opt_in_is_rejected_while_the_other_is_enabled(option: str) -> None:
    settings = json.loads(Path("configs/v13-2-e0-normal.json").read_text())
    settings.update(
        memory_material_profile="compact_v1", memory_derived_index_storage="owner_bank_v1"
    )
    settings[option] = "invalid"
    with pytest.raises(ValueError, match="INVALID"):
        runner._recipe_settings(settings)
