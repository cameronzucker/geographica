"""Tests for the STT backend interface."""

from dataclasses import fields

from backends import TranscribeResult


def test_transcribe_result_is_dataclass():
    """TranscribeResult must be a dataclass with text and duration_ms fields."""
    field_names = {f.name for f in fields(TranscribeResult)}
    assert "text" in field_names
    assert "duration_ms" in field_names


def test_transcribe_result_construction():
    """TranscribeResult can be constructed with text and duration_ms."""
    result = TranscribeResult(text="hello world", duration_ms=1234)
    assert result.text == "hello world"
    assert result.duration_ms == 1234


def test_transcribe_result_types():
    """TranscribeResult field types are str and int."""
    field_types = {f.name: f.type for f in fields(TranscribeResult)}
    # Handle both Python 3.11 (string annotations) and 3.13+ (class annotations)
    assert field_types["text"] in ("str", str)
    assert field_types["duration_ms"] in ("int", int)
