from __future__ import annotations

from milai.domain.retrieval_projection import derive_projection_fragments


def test_projection_fragments_preserve_turns_windows_and_parent_order() -> None:
    fragments = derive_projection_fragments(
        "user: I prefer blue trail shoes.\nassistant: I recommend the Alpine model."
    )

    assert [fragment.ordinal for fragment in fragments] == list(range(len(fragments)))
    assert [fragment.kind for fragment in fragments] == ["turn", "turn", "window"]
    assert fragments[0].roles == ("user",)
    assert fragments[1].roles == ("assistant",)
    assert fragments[2].roles == ("user", "assistant")


def test_projection_fragment_chunks_keep_late_turn_content_searchable() -> None:
    words = [f"word-{index}" for index in range(310)]
    fragments = derive_projection_fragments("assistant: " + " ".join(words))

    assert len(fragments) == 3
    assert "word-0" in fragments[0].content_text
    assert "word-309" in fragments[-1].content_text
    assert all(fragment.turn_start == fragment.turn_end == 0 for fragment in fragments)
