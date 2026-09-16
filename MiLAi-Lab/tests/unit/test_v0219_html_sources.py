"""No semantic selection, network access or hidden-script execution in HTML extraction."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0219_html_sources import complete_html_text


def test_full_text_order_table_boundaries_entities_and_no_execution():
    value = complete_html_text(
        '<html><head><title>metadata</title><script>bad()</script></head>'
        '<body><p>Old &amp; new</p><table><tr><td>Revenue</td><td>9.24</td>'
        '<td>BUSD</td></tr></table><p>Contradictory evidence retained</p>'
        '<style>.hide{}</style><script>fetch("secret")</script></body></html>'
    )
    assert value == "Old & new\nRevenue\n9.24\nBUSD\nContradictory evidence retained"


def test_no_relevance_selection_or_external_image_caption():
    assert complete_html_text('<p>unrelated</p><img src="remote"><p>important</p>') == (
        "unrelated\nimportant"
    )


def test_unterminated_suppressed_section_not_silent_truncation():
    with pytest.raises(ValueError, match="UNTERMINATED"):
        complete_html_text("<p>start</p><script>unclosed")
