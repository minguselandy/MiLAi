"""Token quotas for the public full-episode controller observation."""

from __future__ import annotations

import json
from typing import Any


def compact(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def evidence_text(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        compact({"label": item.get("label"), "evidence": item.get("evidence", [])})
        for item in items
    )


def candidate_preview(item: dict[str, Any], navigation: dict[str, Any]) -> str:
    parts = [str(item.get("excerpt", ""))]
    nav = item.get("navigation", navigation)
    for name, part in nav.items():
        if isinstance(part, dict) and "text" in part:
            parts.append(f"{name}: {part['text']}")
    return "\n".join(parts)


def control_sequences(
    tokenizer: Any,
    online: dict[str, Any],
    limit: int,
    *,
    history: bool = True,
    diagnostic_evidence: dict[str, Any] | None = None,
):
    """Encode an object once for every offered level, and HANDOFF as its own object."""
    obs = online["observation"]
    actions = online["actions"]
    candidates = {x["item_index"]: x for x in obs["pending_candidates"]}
    upgrades = obs.get("navigation_upgrades") or {}
    indices, object_rows, levels, owner = {}, [], [], []
    previews = {}
    for action in actions:
        params = action["parameters"]
        if action["kind"] == "READ":
            index = params["index"]
            key = ("candidate", index)
            preview = candidate_preview(
                candidates.get(index, {}), upgrades.get(index, upgrades.get(str(index), {}))
            )
            previews[index] = preview
            level = int(bool(params.get("expand_context"))) + 1
        elif action["kind"] == "HANDOFF":
            key, preview, level = ("handoff", compact(params)), "HANDOFF " + compact(params), 0
        else:
            raise ValueError(f"Unsupported action after common initial search: {action['kind']}")
        if key not in indices:
            indices[key] = len(object_rows)
            object_rows.append(preview)
        owner.append(indices[key])
        levels.append(level)
    if limit < 128 or not actions:
        raise ValueError("Expected a nonempty legal menu and at least 128 tokens")
    # Every nonempty field has a reserved share; short fields donate unused capacity.
    special = tokenizer.num_special_tokens_to_add(pair=True)
    usable = limit - special
    fields = [
        ("Task", obs["task"], 18),
        (
            "Budget",
            {
                k: obs["budget"].get(k)
                for k in (
                    "remaining_control_steps",
                    "remaining_reader_material_tokens",
                    "reader_material_tokens",
                    "successful_reads",
                )
            },
            7,
        ),
        ("Acquired only", evidence_text(obs.get("observed_evidence") or []), 15),
        ("Delivered", evidence_text(obs["visible_evidence"]), 29),
        (
            "Prior operations",
            {"history": obs.get("action_history", []), "last": obs["last_result"]},
            6,
        )
        if history
        else ("Last operation", obs["last_result"], 6),
        ("Candidate menu", list(previews.values()), 7),
    ]

    def encode(name, value):
        return tokenizer.encode(
            f"{name}\n{compact(value)}",
            add_special_tokens=False,
            truncation=True,
            max_length=usable,
        )

    shared = [encode(name, value) for name, value, _ in fields]
    if diagnostic_evidence is not None:
        # Hold each evidence field's token quota fixed while exchanging the material of
        # two independently executed branches. The Host and the Reader still see the original.
        for index, key in ((2, "observed_evidence"), (3, "visible_evidence")):
            if not obs.get(key):
                continue
            if not diagnostic_evidence.get(key):
                raise ValueError("Swapped evidence roles require corresponding donor material")
            name = fields[index][0]
            header = encode(name, "")
            other = encode(name, evidence_text(diagnostic_evidence[key]))
            prefix = 0
            while prefix < min(len(header), len(other), len(shared[index])) and (
                header[prefix] == other[prefix] == shared[index][prefix]
            ):
                prefix += 1
            donor = other[prefix:]
            needed = len(shared[index]) - prefix
            if needed and not donor:
                raise ValueError("Diagnostic donor has no evidence tokens")
            if needed:
                shared[index] = (
                    shared[index][:prefix] + (donor * (1 + needed // len(donor)))[:needed]
                )
    sequences = []
    for preview in object_rows:
        pieces = [*shared, encode("Proposed object", preview)]
        sizes = [
            min(len(ids), max(1, usable * pct // 100))
            for ids, pct in zip(pieces, [*(f[2] for f in fields), 18], strict=True)
        ]
        spare = usable - sum(sizes)
        for i in (6, 0, 3, 2, 4, 5, 1):
            extra = min(spare, len(pieces[i]) - sizes[i])
            sizes[i] += extra
            spare -= extra
        state_ids = [
            token for ids, size in zip(shared, sizes[:-1], strict=True) for token in ids[:size]
        ]
        sequences.append(
            tokenizer.build_inputs_with_special_tokens(state_ids, pieces[-1][: sizes[-1]])
        )
    return sequences, owner, levels
