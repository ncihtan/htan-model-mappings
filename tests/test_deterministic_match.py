"""Tests for deterministic_match.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from deterministic_match import deterministic_match, build_field_index, make_field_id


def _make_model(model_id, classes):
    return {"model_id": model_id, "format": "test", "classes": classes}


def _make_field(name, cadsr_id=None, normalized_name=None):
    if normalized_name is None:
        normalized_name = name.lower().replace(" ", "_")
    return {
        "name": name,
        "normalized_name": normalized_name,
        "description": "",
        "cadsr_id": cadsr_id,
        "source_uri": None,
        "valid_values": [],
        "required": False,
    }


def test_cadsr_match():
    source = _make_model("source/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("Ethnicity", cadsr_id="2192217"),
        ]}
    ])
    target = _make_model("target/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("ETHNIC_GROUP", cadsr_id="2192217", normalized_name="ethnic_group"),
        ]}
    ])
    matched, unmatched_s, unmatched_t = deterministic_match(source, target)
    assert len(matched) == 1
    assert matched[0]["predicate_id"] == "skos:exactMatch"
    assert matched[0]["confidence"] == 1.0
    assert "caDSR" in matched[0]["comment"]
    assert len(unmatched_s) == 0
    assert len(unmatched_t) == 0


def test_name_match():
    source = _make_model("source/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("gender", normalized_name="gender"),
        ]}
    ])
    target = _make_model("target/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("GENDER", normalized_name="gender"),
        ]}
    ])
    matched, unmatched_s, unmatched_t = deterministic_match(source, target)
    assert len(matched) == 1
    assert matched[0]["confidence"] == 0.9
    assert matched[0]["mapping_justification"] == "semapv:LexicalMatching"


def test_no_match():
    source = _make_model("source/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("Days to Birth"),
        ]}
    ])
    target = _make_model("target/model@v1", [
        {"name": "Demographics", "fields": [
            _make_field("AGE_IN_DAYS", normalized_name="age_in_days"),
        ]}
    ])
    matched, unmatched_s, unmatched_t = deterministic_match(source, target)
    assert len(matched) == 0
    assert len(unmatched_s) == 1
    assert len(unmatched_t) == 1


def test_cadsr_takes_priority_over_name():
    """If a field matches by caDSR, it shouldn't also match by name."""
    source = _make_model("source/model@v1", [
        {"name": "Demo", "fields": [
            _make_field("race", cadsr_id="2192199", normalized_name="race"),
        ]}
    ])
    target = _make_model("target/model@v1", [
        {"name": "Demo", "fields": [
            _make_field("RACE", cadsr_id="2192199", normalized_name="race"),
        ]}
    ])
    matched, _, _ = deterministic_match(source, target)
    assert len(matched) == 1
    assert matched[0]["confidence"] == 1.0  # caDSR match, not name match


def test_make_field_id():
    assert make_field_id("ncihtan/data-models@v25.2.1", "Demographics", "Ethnicity") == "data_models:Demographics/Ethnicity"
