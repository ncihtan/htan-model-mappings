"""Tests for value_match.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from value_match import (
    normalize_value,
    match_values,
    extract_class_field,
    make_value_id,
    value_match_for_domain,
)


def test_normalize_value_basic():
    assert normalize_value("White") == "white"
    assert normalize_value("unknown") == "unknown"
    assert normalize_value("Not Reported") == "not_reported"


def test_normalize_value_strips_suffix():
    assert normalize_value("Tissue Biospecimen Type") == "tissue"
    assert normalize_value("Fresh Frozen") == "fresh_frozen"


def test_normalize_value_collapses_punctuation():
    assert normalize_value("G1 - Low Grade") == "g1_low_grade"
    assert normalize_value("Yes/No") == "yes_no"


def test_extract_class_field():
    cls, field = extract_class_field("data_models:Demographics/Ethnicity")
    assert cls == "Demographics"
    assert field == "Ethnicity"


def test_extract_class_field_with_slash_in_value():
    cls, field = extract_class_field("prefix:Class/Field Name")
    assert cls == "Class"
    assert field == "Field Name"


def test_make_value_id():
    vid = make_value_id(
        "ncihtan/data-models@v25.2.1",
        "Demographics",
        "Ethnicity",
        "Hispanic or Latino",
    )
    assert vid == "data_models:Demographics/Ethnicity/hispanic_or_latino"


def test_match_values_case_insensitive():
    """Case-insensitive exact match gets confidence 1.0."""
    matched, unmatched_s, unmatched_t = match_values(
        source_values=["White", "Black or African American", "unknown"],
        target_values=["white", "Black or African American", "Unknown"],
        source_model_id="source/model@v1",
        target_model_id="target/model@v1",
        source_class="Demographics",
        source_field="Race",
        target_class="Demographics",
        target_field="RACE",
    )
    assert len(matched) == 3
    # All should be exactMatch at confidence 1.0
    for m in matched:
        assert m["predicate_id"] == "skos:exactMatch"
        assert m["confidence"] == 1.0
    assert len(unmatched_s) == 0
    assert len(unmatched_t) == 0


def test_match_values_normalized():
    """Normalized match gets confidence 0.9."""
    matched, unmatched_s, unmatched_t = match_values(
        source_values=["Tissue Biospecimen Type"],
        target_values=["Tissue"],
        source_model_id="source/model@v1",
        target_model_id="target/model@v1",
        source_class="Biospecimen",
        source_field="Biospecimen Type",
        target_class="Biospecimen",
        target_field="BIOSPECIMEN_TYPE",
    )
    assert len(matched) == 1
    assert matched[0]["confidence"] == 0.9
    assert matched[0]["predicate_id"] == "skos:exactMatch"


def test_match_values_containment():
    """Containment match gets confidence 0.7."""
    matched, unmatched_s, unmatched_t = match_values(
        source_values=["G1"],
        target_values=["G1 Low Grade", "G2 Intermediate"],
        source_model_id="source/model@v1",
        target_model_id="target/model@v1",
        source_class="Diagnosis",
        source_field="Tumor Grade",
        target_class="Diagnosis",
        target_field="TUMOR_GRADE",
    )
    assert len(matched) == 1
    assert matched[0]["confidence"] == 0.7
    assert matched[0]["predicate_id"] == "skos:closeMatch"
    assert matched[0]["object_label"] == "G1 Low Grade"
    assert len(unmatched_t) == 1  # G2 Intermediate unmatched


def test_match_values_no_match():
    """Values with no match remain in unmatched lists."""
    matched, unmatched_s, unmatched_t = match_values(
        source_values=["Completely Different"],
        target_values=["Nothing Similar"],
        source_model_id="source/model@v1",
        target_model_id="target/model@v1",
        source_class="Test",
        source_field="Field",
        target_class="Test",
        target_field="FIELD",
    )
    assert len(matched) == 0
    assert len(unmatched_s) == 1
    assert len(unmatched_t) == 1


def test_match_values_ethnicity():
    """Real-world test: HTAN1 Ethnicity → HTAN2 ETHNIC_GROUP values."""
    matched, unmatched_s, unmatched_t = match_values(
        source_values=[
            "Hispanic or Latino",
            "Not Hispanic or Latino",
            "Unknown",
            "Not Reported",
        ],
        target_values=[
            "Hispanic or Latino",
            "Not Hispanic or Latino",
            "Unknown",
            "Not Reported",
            "Not Allowed to Collect",
        ],
        source_model_id="ncihtan/data-models@v25.2.1",
        target_model_id="ncihtan/htan2-data-model@v1.3.0",
        source_class="Demographics",
        source_field="Ethnicity",
        target_class="Demographics",
        target_field="ETHNIC_GROUP",
    )
    assert len(matched) == 4
    assert len(unmatched_s) == 0
    assert len(unmatched_t) == 1  # "Not Allowed to Collect" is new
    assert unmatched_t[0] == "Not Allowed to Collect"


def test_value_match_for_domain():
    """Integration test with model + SSSOM structures."""
    source_model = {
        "model_id": "source/model@v1",
        "format": "test",
        "classes": [
            {
                "name": "Demographics",
                "fields": [
                    {
                        "name": "Race",
                        "normalized_name": "race",
                        "description": "",
                        "cadsr_id": "2192199",
                        "source_uri": None,
                        "valid_values": ["White", "Black", "Asian"],
                        "required": False,
                    }
                ],
            }
        ],
    }
    target_model = {
        "model_id": "target/model@v1",
        "format": "test",
        "classes": [
            {
                "name": "Demographics",
                "fields": [
                    {
                        "name": "RACE",
                        "normalized_name": "race",
                        "description": "",
                        "cadsr_id": "2192199",
                        "source_uri": None,
                        "valid_values": ["White", "Black or African American", "Asian", "Unknown"],
                        "required": False,
                    }
                ],
            }
        ],
    }
    field_mappings = [
        {
            "subject_id": "model:Demographics/Race",
            "subject_label": "Race",
            "predicate_id": "skos:exactMatch",
            "object_id": "model:Demographics/RACE",
            "object_label": "RACE",
            "confidence": "1.0",
        }
    ]

    matched, unmatched_s, unmatched_t = value_match_for_domain(
        source_model, target_model, field_mappings
    )

    assert len(matched) >= 2  # White and Asian should match exactly
    assert any(m["subject_label"] == "White" for m in matched)
    assert any(m["subject_label"] == "Asian" for m in matched)
