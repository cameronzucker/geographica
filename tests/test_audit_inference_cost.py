from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from audit_inference_cost import aggregate_directory, price_totals, PRICING

FIXTURES = Path(__file__).parent / "fixtures" / "audit_inference_cost"


def test_aggregate_single_opus_turn():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl")
    assert totals["opus"]["input"] == 10
    assert totals["opus"]["cache_w_5m"] == 200
    assert totals["opus"]["cache_w_1h"] == 800
    assert totals["opus"]["cache_r"] == 5000
    assert totals["opus"]["output"] == 50
    assert totals["opus"]["turns"] == 1
    assert "sonnet" not in totals
    assert "haiku" not in totals


def test_empty_file_does_not_crash():
    totals = aggregate_directory(FIXTURES, parent_glob="empty.jsonl")
    # Empty file → no turns recorded but no exception
    assert totals == {} or all(t.get("turns", 0) == 0 for t in totals.values())


def test_subagent_transcripts_are_picked_up():
    """Subagent dir lives at <project>/<sessid>/subagents/*.jsonl."""
    totals = aggregate_directory(FIXTURES, parent_glob="parent_with_subagent_ref.jsonl")
    # Parent contributed Opus
    assert totals["opus"]["turns"] >= 1
    # Subagent dir abc123/ contributed Sonnet + Haiku
    assert totals["sonnet"]["turns"] == 1
    assert totals["haiku"]["turns"] == 1


def test_price_totals_opus_known_values():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl")
    priced = price_totals(totals)
    expected_full = (
        10 / 1e6 * 15
      + 200 / 1e6 * 15 * 1.25
      + 800 / 1e6 * 15 * 2.0
      + 5000 / 1e6 * 15 * 0.10
      + 50 / 1e6 * 75
    )
    assert abs(priced["opus"]["full"] - expected_full) < 1e-6
    expected_uncached = 10 / 1e6 * 15 + 50 / 1e6 * 75
    assert abs(priced["opus"]["uncached"] - expected_uncached) < 1e-6
