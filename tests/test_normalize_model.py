"""Tests for normalize_model.py."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from normalize_model import (
    detect_format,
    extract_cadsr_id,
    normalize_name,
    parse_linkml_yaml,
    parse_schematic_csv,
    parse_json_schema,
    merge_normalized_models,
)


def test_normalize_name():
    assert normalize_name("Ethnicity") == "ethnicity"
    assert normalize_name("Age at Diagnosis") == "age_at_diagnosis"
    assert normalize_name("ETHNIC_GROUP") == "ethnic_group"
    assert normalize_name("PRIMARY_DIAGNOSIS") == "primary_diagnosis"
    assert normalize_name("Days to Birth") == "days_to_birth"
    assert normalize_name("camelCase") == "camel_case"


def test_extract_cadsr_id():
    assert extract_cadsr_id("https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=2192217") == "2192217"
    assert extract_cadsr_id("caDSR:2192217") == "2192217"
    assert extract_cadsr_id("") is None
    assert extract_cadsr_id(None) is None
    assert extract_cadsr_id("no match here") is None


def test_parse_schematic_csv():
    csv_content = """Attribute,Description,Valid Values,DependsOn,Properties,Required,Parent,DependsOn Component,Source,Validation Rules
Ethnicity,Self-reported ethnicity,"hispanic or latino,not hispanic or latino,unknown",,,,Demographics,,https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=2192217,
Race,Self-reported race,"white,black or african american,asian",,,,Demographics,,https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=2192199,
"""
    result = parse_schematic_csv(csv_content, "ncihtan/data-models@v25.2.1")
    assert result["format"] == "schematic-csv"
    assert len(result["classes"]) == 1
    assert result["classes"][0]["name"] == "Demographics"
    assert len(result["classes"][0]["fields"]) == 2

    eth = result["classes"][0]["fields"][0]
    assert eth["name"] == "Ethnicity"
    assert eth["normalized_name"] == "ethnicity"
    assert eth["cadsr_id"] == "2192217"
    assert "hispanic or latino" in eth["valid_values"]


def test_parse_linkml_yaml():
    yaml_content = """
classes:
  Demographics:
    attributes:
      ETHNIC_GROUP:
        description: Self-reported ethnicity
        slot_uri: caDSR:2192217
        range: EthnicGroupEnum
        required: true
      RACE:
        description: Self-reported race
        slot_uri: caDSR:2192199
        range: RaceEnum
enums:
  EthnicGroupEnum:
    permissible_values:
      Hispanic or Latino:
        description: Hispanic or Latino
      Not Hispanic or Latino:
        description: Not Hispanic or Latino
  RaceEnum:
    permissible_values:
      White:
        description: White
      Black or African American:
        description: Black or African American
"""
    result = parse_linkml_yaml(yaml_content, "ncihtan/htan2-data-model@v1.3.0")
    assert result["format"] == "linkml"
    assert len(result["classes"]) == 1

    demo = result["classes"][0]
    assert demo["name"] == "Demographics"
    assert len(demo["fields"]) == 2

    eg = demo["fields"][0]
    assert eg["name"] == "ETHNIC_GROUP"
    assert eg["cadsr_id"] == "2192217"
    assert "Hispanic or Latino" in eg["valid_values"]


def test_parse_json_schema():
    json_content = json.dumps({
        "title": "Demographics",
        "properties": {
            "ethnicity": {
                "description": "Self-reported ethnicity",
                "enum": ["hispanic or latino", "not hispanic or latino"]
            }
        },
        "required": ["ethnicity"]
    })
    result = parse_json_schema(json_content, "gdc/model@v1.0")
    assert result["format"] == "json-schema"
    assert len(result["classes"]) == 1
    assert result["classes"][0]["fields"][0]["required"] is True


def test_detect_format():
    assert detect_format("", "HTAN.model.csv") == "schematic-csv"
    assert detect_format("", "schema.yaml") == "linkml"
    assert detect_format("", "model.json") == "json-schema"
    assert detect_format("Attribute,Description,Parent", "data.txt") == "schematic-csv"
    assert detect_format("classes:\n  Foo:", "data.txt") == "linkml"


def test_merge_normalized_models():
    m1 = {"model_id": "test", "format": "linkml", "classes": [
        {"name": "A", "fields": [{"name": "f1", "normalized_name": "f1"}]}
    ]}
    m2 = {"model_id": "test", "format": "linkml", "classes": [
        {"name": "A", "fields": [{"name": "f2", "normalized_name": "f2"}]},
        {"name": "B", "fields": [{"name": "f3", "normalized_name": "f3"}]}
    ]}
    merged = merge_normalized_models([m1, m2])
    assert len(merged["classes"]) == 2
    class_a = next(c for c in merged["classes"] if c["name"] == "A")
    assert len(class_a["fields"]) == 2
