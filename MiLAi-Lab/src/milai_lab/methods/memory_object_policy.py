"""Object-level embeddings and a finite-menu latent pointer, independent of an LLM family."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from milai_lab.methods.control_numeric import ACTION_WIDTH, STATE_WIDTH
from milai_lab.methods.control_observation import control_texts

OBJECT_COLLECTIONS = (
    "pending_candidates", "visible_evidence", "observed_evidence", "observed_materials",
    "retrieved_scopes", "views", "new_events",
)


def object_control_texts(online: dict[str, Any], *, view_unit_context: bool = False,
                         ) -> tuple[list[str], list[str]]:
    """Only the online observation; every actual collection item is retained.

    Task/global context occupy the first two tokens. Other tokens are objects,
    with explicit observed/selected collection roles. No positional embeddings,
    menu IDs, offline outcomes, root IDs or split identifiers are encoded.
    """
    observation = copy.deepcopy(online["observation"])
    observation.pop("action_bindings", None)
    observation.pop("navigation_upgrades", None)
    last = observation.get("last_result")
    if last is not None and "action" in last:
        last["action"].pop("id", None)

    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    objects = []
    for collection in OBJECT_COLLECTIONS:
        for item in observation.pop(collection, []) or []:
            objects.append(dumps({"collection": collection, "object": item}))
    task = observation.pop("task")
    _, actions = control_texts(online, delivery_context=True, view_unit_context=view_unit_context)
    return [dumps({"task": task}), dumps({"context": observation}), *objects], actions


def object_semantic_texts(objects: list[str], actions: list[str], *, navigation_v2: bool = False,
                          ) -> tuple[list[str], list[str]]:
    """A supplementary text view; complete raw objects/bindings stay in the first lane.

    This resolves no external references. Text absent from the supplied projection
    remains absent; arbitrary schemas and all metadata still have their raw lane.
    """
    text_fields = {"content", "excerpt", "text", "statement", "claim", "summary"}

    def text(value: Any) -> str:
        pieces: list[str] = []

        def collect(item: Any) -> None:
            if isinstance(item, dict):
                if navigation_v2 and (
                    item.get("navigation_only") is True
                    or item.get("requested_span_role") in {"focus", "context"}
                ):
                    requested = item.get("requested_span_role")
                    if requested is not None:
                        pieces.append(f"Requested span: {requested}")
                    for role in ("focus", "expansion_only"):
                        fragment = item.get("navigation", {}).get(role, {})
                        if fragment.get("status") == "available":
                            pieces.append(f"{role}: {fragment['text']}")
                if item.get("body_delivered") is False:
                    return
                for key, child in item.items():
                    if navigation_v2 and key == "navigation":
                        continue
                    if key in text_fields and isinstance(child, str):
                        pieces.append(child)
                    else:
                        collect(child)
            elif isinstance(item, list):
                for child in item:
                    collect(child)

        collect(value)
        return "\n".join(pieces)

    task = json.loads(objects[0])["task"]
    query = task.get("request", task.get("query"))
    memories = [query if isinstance(query, str) else "", "",
                *(text(json.loads(item)["object"]) for item in objects[2:])]
    return memories, [text(json.loads(item)) for item in actions]


@dataclass(frozen=True)
class ControlPredictions:
    quality_logits: Any
    cost_units: Any
    evidence_logits: Any


def build_object_head(embedding_width: int, *, architecture: str = "latent_pointer",
                      width: int = 384, heads: int = 6, slots: int = 16,
                      blocks: int = 4, ffn_width: int = 1024, dropout: float = .1,
                      numeric: bool = False, quality_cost: bool = False) -> Any:
    """Two heads on exactly the same independent object/action encodings.

    The independent MLP pools objects. The latent head recomputes a small
    query-conditioned workspace, then points to a complete action embedding.
    This is computation over already supplied information, never a source read.
    """
    import torch  # type: ignore[import-not-found]
    from torch import nn

    if architecture not in {"object_mlp", "latent_pointer"}:
        raise ValueError("Unknown memory object architecture")
    if min(embedding_width, width, heads, slots, blocks, ffn_width) < 1 or width % heads:
        raise ValueError("Positive object dimensions and a head-divisible width are required")

    class ObjectHead(nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.memory_projection = nn.Linear(embedding_width, width)
            self.action_projection = nn.Linear(embedding_width, width)
            self.context_projection = nn.Linear(embedding_width * 2, width)
            if architecture == "latent_pointer":
                self.slots = nn.Parameter(torch.randn(slots, width) * .02)
                self.cross = nn.ModuleList([nn.MultiheadAttention(
                    width, heads, dropout=dropout, batch_first=True) for _ in range(blocks)])
                self.self_blocks = nn.ModuleList([nn.TransformerEncoderLayer(
                    width, heads, ffn_width, dropout, activation="gelu", batch_first=True,
                    norm_first=True) for _ in range(blocks)])
                self.cross_norms = nn.ModuleList([nn.LayerNorm(width) for _ in range(blocks)])
                self.pointer = nn.MultiheadAttention(width, heads, dropout=dropout,
                                                     batch_first=True)
            self.output = nn.Sequential(nn.Linear(width * 4, ffn_width), nn.GELU(),
                                        nn.Dropout(dropout), nn.Linear(ffn_width, 1))
            if numeric:
                self.state_numeric = nn.Linear(STATE_WIDTH, width)
                self.action_numeric = nn.Linear(ACTION_WIDTH, width)
            if quality_cost:
                self.cost_output = nn.Linear(ffn_width, 1)
                self.evidence_output = nn.Linear(ffn_width, 1)

        def forward(
            self, state: Any, actions: Any, owners: Any, numerics: tuple[Any, Any] | None = None,
        ) -> Any:
            if state.ndim != 3 or state.shape[1] < 2:
                raise ValueError("Object head requires task, context and optional memory tokens")
            mask = state.abs().sum(-1) == 0
            if mask[:, :2].any():
                raise ValueError("Actual task and global context must be encoded")
            memory = self.memory_projection(state)
            context = self.context_projection(state[:, :2].flatten(1))
            action = self.action_projection(actions)
            if numeric:
                if (numerics is None or len(numerics[0]) != len(state)
                        or len(numerics[1]) != len(actions)):
                    raise ValueError("Numeric observations must align with states and actions")
                context = context + self.state_numeric(numerics[0])
                action = action + self.action_numeric(numerics[1])
            if architecture == "object_mlp":
                valid = (~mask).to(memory.dtype)[..., None]
                pooled = (memory * valid).sum(1) / valid.sum(1)
                conditioned = (pooled + context)[owners]
            else:
                workspace = self.slots[None].expand(len(state), -1, -1) + context[:, None]
                for cross, norm, block in zip(self.cross, self.cross_norms,
                                               self.self_blocks, strict=True):
                    query = norm(workspace)
                    delta, _ = cross(query, memory, memory, key_padding_mask=mask,
                                     need_weights=False)
                    workspace = block(workspace + delta)
                # Ragged menus stay separate: an action can attend only its own workspace.
                pieces = []
                for index in range(len(state)):
                    selected = action[owners == index][None]
                    value, _ = self.pointer(selected, workspace[index:index + 1],
                                            workspace[index:index + 1], need_weights=False)
                    pieces.append(value[0])
                # Owners are state-major in the common features/training interface.
                if not torch.equal(owners, owners.sort().values):
                    raise ValueError("Object pointer requires state-major action owners")
                conditioned = torch.cat(pieces)
            features = torch.cat((action, conditioned, action * conditioned,
                                  action - conditioned), dim=-1)
            if not quality_cost:
                return self.output(features).squeeze(-1)
            embedding = self.output[2](self.output[1](self.output[0](features)))
            cost = self.cost_output(embedding).squeeze(-1).float()
            return ControlPredictions(
                quality_logits=self.output[3](embedding).squeeze(-1),
                cost_units=torch.nn.functional.softplus(cost),
                evidence_logits=self.evidence_output(embedding).squeeze(-1),
            )

    return ObjectHead()
