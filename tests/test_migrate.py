"""Tests for migrate.py."""

import csv
import json
import sys
import tempfile
from io import StringIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from migrate import MigrationEngine

PROJECT_ROOT = Path(__file__).parent.parent


def _write_temp_tsv(rows: list[dict], fieldnames: list[str]) -> str:
    """Write rows to a temp TSV file and return path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".tsv", delete=False)
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    f.close()
    return f.name


def _make_minimal_config(
    tmp_dir: Path,
    field_sssom_content: str = "",
    value_sssom_content: str = "",
    conversions: list | None = None,
    structural: list | None = None,
    defaults: list | None = None,
) -> str:
    """Create a minimal transform config and supporting files, return config path."""
    configs_dir = tmp_dir / "configs" / "htan1_to_htan2"
    configs_dir.mkdir(parents=True, exist_ok=True)
    mappings_dir = tmp_dir / "mappings" / "htan1_to_htan2"
    mappings_dir.mkdir(parents=True, exist_ok=True)

    # Write field SSSOM
    field_sssom_path = mappings_dir / "test_fields.sssom.tsv"
    field_sssom_path.write_text(field_sssom_content)

    # Write value SSSOM
    value_sssom_path = mappings_dir / "test_values.sssom.tsv"
    value_sssom_path.write_text(value_sssom_content)

    config = {
        "source_model": "source/model@v1",
        "target_model": "target/model@v1",
        "domain": "test",
        "field_mappings": "mappings/htan1_to_htan2/test_fields.sssom.tsv",
        "value_mappings": "mappings/htan1_to_htan2/test_values.sssom.tsv",
        "min_confidence": 0.9,
        "conversions": conversions or [],
        "structural": structural or [],
        "defaults": defaults or [],
    }

    config_path = configs_dir / "test.transform.yaml"
    import yaml
    config_path.write_text(yaml.dump(config))
    return str(config_path)


# Minimal SSSOM header for test files
SSSOM_HEADER = """#curie_map:
#  skos: http://www.w3.org/2004/02/skos/core#
"""


class TestTier1FieldRenaming:
    def test_renames_field(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
            "model:Demo/Ethnicity\tEthnicity\tskos:exactMatch\t"
            "model:Demo/ETHNIC_GROUP\tETHNIC_GROUP\tsemapv:LexicalMatching\t1.0\ttest\n"
        )
        config_path = _make_minimal_config(tmp_path, field_sssom_content=field_sssom)

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Ethnicity": "Hispanic or Latino"},
            "Demo",
        )
        assert result.get("ETHNIC_GROUP") == "Hispanic or Latino"

    def test_skips_low_confidence(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
            "model:Demo/Foo\tFoo\tskos:closeMatch\t"
            "model:Demo/BAR\tBAR\tsemapv:LogicalReasoning\t0.5\tlow conf\n"
        )
        config_path = _make_minimal_config(tmp_path, field_sssom_content=field_sssom)

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row({"Foo": "val"}, "Demo")
        assert "BAR" not in result


class TestTier2ValueRemapping:
    def test_remaps_value(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
            "model:Demo/Status\tStatus\tskos:exactMatch\t"
            "model:Demo/STATUS\tSTATUS\tsemapv:LexicalMatching\t1.0\ttest\n"
        )
        value_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tsubject_match_field\tpredicate_id\t"
            "object_id\tobject_label\tobject_match_field\t"
            "mapping_justification\tconfidence\tcomment\n"
            "model:Demo/Status/alive\tAlive\tmodel:Demo/Status\tskos:exactMatch\t"
            "model:Demo/STATUS/living\tLiving\tmodel:Demo/STATUS\t"
            "semapv:LexicalMatching\t1.0\ttest\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            value_sssom_content=value_sssom,
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row({"Status": "Alive"}, "Demo")
        assert result.get("STATUS") == "Living"


class TestTier3Conversions:
    def test_years_to_days(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            conversions=[
                {
                    "source": {"class": "Diagnosis", "field": "Age at Diagnosis"},
                    "target": {"class": "Diagnosis", "field": "AGE_IN_DAYS_AT_DIAGNOSIS"},
                    "type": "years_to_days",
                    "multiplier": 365.25,
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Age at Diagnosis": "50"},
            "Diagnosis",
        )
        assert result.get("AGE_IN_DAYS_AT_DIAGNOSIS") == "18262"  # 50 * 365.25 = 18262.5, rounds to 18262

    def test_age_days_auto_already_days(self, tmp_path):
        """BQ data with age already in days should pass through."""
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            conversions=[
                {
                    "source": {"class": "Diagnosis", "field": "Age at Diagnosis"},
                    "target": {"class": "Diagnosis", "field": "AGE_IN_DAYS_AT_DIAGNOSIS"},
                    "type": "age_days_auto",
                    "years_threshold": 200,
                    "multiplier": 365.25,
                }
            ],
        )

        engine = MigrationEngine(config_path)
        # BQ value: 20257 days (~55.5 years) - should pass through
        result, warnings = engine.transform_row(
            {"Age at Diagnosis": "20257"},
            "Diagnosis",
        )
        assert result.get("AGE_IN_DAYS_AT_DIAGNOSIS") == "20257"

    def test_age_days_auto_converts_years(self, tmp_path):
        """Value in years (< threshold) should be converted to days."""
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            conversions=[
                {
                    "source": {"class": "Diagnosis", "field": "Age at Diagnosis"},
                    "target": {"class": "Diagnosis", "field": "AGE_IN_DAYS_AT_DIAGNOSIS"},
                    "type": "age_days_auto",
                    "years_threshold": 200,
                    "multiplier": 365.25,
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Age at Diagnosis": "50"},
            "Diagnosis",
        )
        assert result.get("AGE_IN_DAYS_AT_DIAGNOSIS") == "18262"

    def test_text_to_ontology(self, tmp_path):
        # Create lookup table
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        lookup = {"breast": "UBERON:0000310", "lung": "UBERON:0002048"}
        (lookups_dir / "uberon_labels_to_codes.json").write_text(json.dumps(lookup))

        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            conversions=[
                {
                    "source": {"class": "Diagnosis", "field": "Tissue or Organ of Origin"},
                    "target": {"class": "Diagnosis", "field": "TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE"},
                    "type": "text_to_ontology",
                    "lookup": "lookups/uberon_labels_to_codes.json",
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Tissue or Organ of Origin": "Breast"},
            "Diagnosis",
        )
        assert result.get("TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE") == "UBERON:0000310"

    def test_text_to_ontology_missing(self, tmp_path):
        lookups_dir = tmp_path / "lookups"
        lookups_dir.mkdir()
        (lookups_dir / "test_lookup.json").write_text(json.dumps({}))

        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            conversions=[
                {
                    "source": {"class": "Diagnosis", "field": "Test Field"},
                    "target": {"class": "Diagnosis", "field": "TEST_CODE"},
                    "type": "text_to_ontology",
                    "lookup": "lookups/test_lookup.json",
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Test Field": "Unknown Tissue"},
            "Diagnosis",
        )
        # Falls back to original value
        assert result.get("TEST_CODE") == "Unknown Tissue"
        assert any("No ontology code" in w for w in warnings)


class TestTier4Structural:
    def test_field_split(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            structural=[
                {
                    "type": "field_split",
                    "source": {"class": "Demographics", "field": "Gender"},
                    "targets": [
                        {"class": "Demographics", "field": "GENDER_IDENTITY"},
                        {"class": "Demographics", "field": "SEX"},
                    ],
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Gender": "Female"},
            "Demographics",
        )
        assert result.get("GENDER_IDENTITY") == "Female"
        assert result.get("SEX") == "Female"

    def test_class_relocation(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            structural=[
                {
                    "type": "class_relocation",
                    "source": {"class": "Diagnosis", "field": "Progression or Recurrence"},
                    "target": {"class": "FollowUp", "field": "PROGRESSION_OR_RECURRENCE"},
                }
            ],
        )

        engine = MigrationEngine(config_path)
        result, warnings = engine.transform_row(
            {"Progression or Recurrence": "Yes"},
            "Diagnosis",
        )
        # Value should be in __relocated__ dict
        assert "__relocated__" in result
        assert result["__relocated__"]["FollowUp/PROGRESSION_OR_RECURRENCE"] == "Yes"


class TestTier5Defaults:
    def test_fills_defaults(self, tmp_path):
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
            "model:Demo/Name\tName\tskos:exactMatch\t"
            "model:Demo/NAME\tNAME\tsemapv:LexicalMatching\t1.0\ttest\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            defaults=[
                {"class": "Demo", "field": "TIMEPOINT", "default": "Baseline", "required": False},
            ],
        )

        # Test via migrate_file which applies defaults
        input_path = _write_temp_tsv(
            [{"Name": "Alice"}],
            ["Name"],
        )
        output_dir = str(tmp_path / "out")

        engine = MigrationEngine(config_path)
        report = engine.migrate_file(input_path, "Demo", output_dir)

        # Read output from report's output_files
        main_file = list(report["output_files"].values())[0]
        output_content = Path(main_file).read_text()
        reader = csv.DictReader(StringIO(output_content), delimiter="\t")
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0].get("TIMEPOINT") == "Baseline"


class TestMigrateFile:
    def test_end_to_end(self, tmp_path):
        """Full pipeline: rename + value remap + default."""
        field_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tpredicate_id\tobject_id\t"
            "object_label\tmapping_justification\tconfidence\tcomment\n"
            "model:Demo/Race\tRace\tskos:exactMatch\t"
            "model:Demo/RACE\tRACE\tsemapv:LexicalMatching\t1.0\ttest\n"
            "model:Demo/Ethnicity\tEthnicity\tskos:exactMatch\t"
            "model:Demo/ETHNIC_GROUP\tETHNIC_GROUP\tsemapv:LexicalMatching\t1.0\ttest\n"
        )
        value_sssom = SSSOM_HEADER + (
            "subject_id\tsubject_label\tsubject_match_field\tpredicate_id\t"
            "object_id\tobject_label\tobject_match_field\t"
            "mapping_justification\tconfidence\tcomment\n"
            "model:Demo/Race/white\tWhite\tmodel:Demo/Race\tskos:exactMatch\t"
            "model:Demo/RACE/white\tWhite\tmodel:Demo/RACE\t"
            "semapv:LexicalMatching\t1.0\ttest\n"
        )
        config_path = _make_minimal_config(
            tmp_path,
            field_sssom_content=field_sssom,
            value_sssom_content=value_sssom,
            defaults=[
                {"class": "Demo", "field": "SITE", "default": "HTAN", "required": False},
            ],
        )

        input_path = _write_temp_tsv(
            [
                {"Race": "White", "Ethnicity": "Not Hispanic or Latino"},
                {"Race": "Asian", "Ethnicity": "Unknown"},
            ],
            ["Race", "Ethnicity"],
        )
        output_dir = str(tmp_path / "out")

        engine = MigrationEngine(config_path)
        report = engine.migrate_file(input_path, "Demo", output_dir)

        assert report["rows_processed"] == 2
        assert report["rows_succeeded"] == 2

        main_file = list(report["output_files"].values())[0]
        output_content = Path(main_file).read_text()
        reader = csv.DictReader(StringIO(output_content), delimiter="\t")
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["RACE"] == "White"
        assert rows[0]["ETHNIC_GROUP"] == "Not Hispanic or Latino"
        assert rows[0]["SITE"] == "HTAN"
