from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from audit_inference_cost import (
    aggregate_directory, price_totals, normalize_model,
    PRICING_BY_MODEL, CACHE_WRITE_5M_MULTIPLIER, CACHE_WRITE_1H_MULTIPLIER,
    CACHE_READ_MULTIPLIER,
)

FIXTURES = Path(__file__).parent / "fixtures" / "audit_inference_cost"


def test_normalize_model_strips_context_suffix():
    assert normalize_model("claude-opus-4-7[1m]") == "claude-opus-4-7"


def test_normalize_model_strips_date_suffix():
    assert normalize_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5"


def test_normalize_model_exact_match():
    assert normalize_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_normalize_model_none_for_unknown():
    assert normalize_model("claude-some-future-model-99-9") is None
    assert normalize_model(None) is None
    assert normalize_model("") is None


def test_aggregate_single_opus_response():
    totals, unknown = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl", subagent_glob="")
    assert "claude-opus-4-7" in totals
    assert totals["claude-opus-4-7"]["input"] == 10
    assert totals["claude-opus-4-7"]["cache_w_5m"] == 200
    assert totals["claude-opus-4-7"]["cache_w_1h"] == 800
    assert totals["claude-opus-4-7"]["cache_r"] == 5000
    assert totals["claude-opus-4-7"]["output"] == 50
    assert totals["claude-opus-4-7"]["responses"] == 1
    assert "claude-sonnet-4-6" not in totals
    assert "claude-haiku-4-5" not in totals
    assert unknown == []


def test_empty_file_does_not_crash():
    totals, unknown = aggregate_directory(FIXTURES, parent_glob="empty.jsonl", subagent_glob="")
    # Empty file → no responses recorded but no exception
    assert totals == {} or all(t.get("responses", 0) == 0 for t in totals.values())


def test_subagent_transcripts_are_picked_up():
    """Subagent dir lives at <project>/<sessid>/subagents/*.jsonl.

    This test uses the DEFAULT subagent_glob (the flat */subagents/*.jsonl pattern
    that matches production behavior), not stem-correlated. The fixture
    abc123/subagents/sub_sonnet.jsonl is set up so the flat glob picks it up.
    """
    totals, unknown = aggregate_directory(FIXTURES, parent_glob="parent_with_subagent_ref.jsonl")
    # Parent contributed Opus (claude-opus-4-7)
    assert totals["claude-opus-4-7"]["responses"] >= 1
    # Subagent dir abc123/ contributed Sonnet + Haiku (picked up by flat glob)
    assert totals["claude-sonnet-4-6"]["responses"] == 1
    assert totals["claude-haiku-4-5"]["responses"] == 1


def test_price_totals_opus_known_values():
    totals, _ = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl", subagent_glob="")
    priced = price_totals(totals)
    p = PRICING_BY_MODEL["claude-opus-4-7"]
    expected_full = (
        10   / 1e6 * p["input"]
      + 200  / 1e6 * p["input"] * CACHE_WRITE_5M_MULTIPLIER
      + 800  / 1e6 * p["input"] * CACHE_WRITE_1H_MULTIPLIER
      + 5000 / 1e6 * p["input"] * CACHE_READ_MULTIPLIER
      + 50   / 1e6 * p["output"]
    )
    assert abs(priced["claude-opus-4-7"]["full"] - expected_full) < 1e-6
    expected_uncached = 10 / 1e6 * p["input"] + 50 / 1e6 * p["output"]
    assert abs(priced["claude-opus-4-7"]["uncached"] - expected_uncached) < 1e-6


def test_dedup_by_message_id():
    """Multiple JSONL lines with same message.id and same usage = one response."""
    totals, _ = aggregate_directory(FIXTURES, parent_glob="parent_multi_fragment.jsonl", subagent_glob="")
    # 3 lines with same msg_id and identical usage → counted ONCE
    assert totals["claude-opus-4-7"]["responses"] == 1
    assert totals["claude-opus-4-7"]["input"] == 10
    assert totals["claude-opus-4-7"]["output"] == 50
    assert totals["claude-opus-4-7"]["cache_r"] == 1000
