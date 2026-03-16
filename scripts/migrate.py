#!/usr/bin/env python3
"""Migration engine: transform HTAN Phase 1 data to Phase 2 format.

Reads YAML transform configs and applies a five-tier pipeline:
  1. Field renaming (from field-level SSSOM)
  2. Value remapping (from value-level SSSOM)
  3. Conversions (unit transforms, text-to-ontology lookups)
  4. Structural transforms (field splits, class relocations)
  5. Defaults (fill required fields not populated by tiers 1-4)

Usage:
    python migrate.py \
        --input htan1_demographics.tsv \
        --config configs/htan1_to_htan2/clinical.transform.yaml \
        --source-class Demographics \
        --output htan2_demographics.tsv \
        --validate \
        --report report.json
"""

import argparse
import csv
import json
import sys
from datetime import date
from io import StringIO
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from validate_mappings import parse_sssom_tsv_basic
from value_match import extract_class_field


def normalize_column_name(col: str | None) -> str:
    """Normalize a BQ-style column name to model-style.

    BQ uses underscores (Vital_Status), model uses spaces (Vital Status).
    Also handles HTAN_Participant_ID → HTAN Participant ID.
    """
    if col is None:
        return ""
    return col.replace("_", " ")


class MigrationEngine:
    """Config-driven transformer for HTAN1 → HTAN2 data migration."""

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        self.config = yaml.safe_load(self.config_path.read_text())
        self.base_dir = self.config_path.parent.parent.parent  # configs/htan1_to_htan2/ -> project root

        # Load field mappings
        self.field_map = self._load_field_mappings()

        # Load value mappings
        self.value_map = self._load_value_mappings()

        # Load conversion rules
        self.conversions = self._load_conversions()

        # Load structural transforms
        self.structural = self.config.get("structural", [])

        # Load defaults
        self.defaults = self.config.get("defaults", [])

        # Lookup table cache
        self._lookup_cache: dict[str, dict] = {}

    def _load_field_mappings(self) -> dict[str, dict]:
        """Load field-level SSSOM into {source_class/field: {target_class, target_field, confidence}}.

        Only includes mappings at or above min_confidence.
        """
        sssom_path = self.base_dir / self.config.get("field_mappings", "")
        if not sssom_path.exists():
            return {}

        min_conf = self.config.get("min_confidence", 0.9)
        parsed = parse_sssom_tsv_basic(sssom_path)
        field_map = {}

        for row in parsed["mappings"]:
            confidence = float(row.get("confidence", 0))
            if confidence < min_conf:
                continue
            predicate = row.get("predicate_id", "")
            if predicate == "skos:noMappingFound":
                continue

            source_class, source_field = extract_class_field(row["subject_id"])
            target_class, target_field = extract_class_field(row["object_id"])

            key = f"{source_class}/{source_field}"
            field_map[key] = {
                "target_class": target_class,
                "target_field": target_field,
                "confidence": confidence,
                "predicate": predicate,
            }

        return field_map

    def _load_value_mappings(self) -> dict[str, dict[str, str]]:
        """Load value-level SSSOM into {source_class/field: {source_value: target_value}}.

        Only includes mappings at or above min_confidence.
        """
        value_sssom_rel = self.config.get("value_mappings", "")
        if not value_sssom_rel:
            return {}

        sssom_path = self.base_dir / value_sssom_rel
        if not sssom_path.exists():
            return {}

        min_conf = self.config.get("min_confidence", 0.9)
        parsed = parse_sssom_tsv_basic(sssom_path)
        value_map: dict[str, dict[str, str]] = {}

        for row in parsed["mappings"]:
            confidence = float(row.get("confidence", 0))
            if confidence < min_conf:
                continue

            # Extract the source field from subject_match_field
            source_match_field = row.get("subject_match_field", "")
            if not source_match_field:
                continue

            source_class, source_field = extract_class_field(source_match_field)
            key = f"{source_class}/{source_field}"

            source_value = row.get("subject_label", "")
            target_value = row.get("object_label", "")

            if source_value and target_value:
                value_map.setdefault(key, {})[source_value] = target_value

        return value_map

    def _load_conversions(self) -> list[dict]:
        """Load conversion rules from config."""
        return self.config.get("conversions", [])

    def _get_lookup(self, lookup_path: str) -> dict:
        """Load a lookup table JSON, with caching."""
        if lookup_path in self._lookup_cache:
            return self._lookup_cache[lookup_path]

        full_path = self.base_dir / lookup_path
        if full_path.exists():
            data = json.loads(full_path.read_text())
        else:
            print(f"Warning: Lookup table not found: {full_path}", file=sys.stderr)
            data = {}

        self._lookup_cache[lookup_path] = data
        return data

    def migrate_file(
        self,
        input_path: str,
        source_class: str,
        output_path: str,
        context_rows: dict[str, list[dict]] | None = None,
        normalize_columns: bool = False,
    ) -> dict:
        """Migrate an entire TSV file.

        Args:
            input_path: Path to input HTAN1 TSV
            source_class: Source class name (e.g., "Demographics")
            output_path: Path to write output HTAN2 TSV
            context_rows: Optional {class_name: [rows]} for cross-class references
                         (e.g., Demographics rows needed for birth date conversion)
            normalize_columns: If True, convert BQ-style underscore column names
                              to model-style space names before processing

        Returns:
            Migration report dict
        """
        input_data = Path(input_path).read_text()
        reader = csv.DictReader(StringIO(input_data), delimiter="\t")
        source_columns = reader.fieldnames or []

        report = {
            "input": input_path,
            "output": output_path,
            "source_class": source_class,
            "date": date.today().isoformat(),
            "rows_processed": 0,
            "rows_succeeded": 0,
            "values_transformed": 0,
            "warnings": [],
            "errors": [],
            "unmapped_values": {},
            "field_coverage": {},
            "relocated_files": {},
        }

        output_rows = []
        all_target_columns = set()
        relocated_rows: dict[str, list[dict]] = {}  # {target_class: [rows]}

        for row in reader:
            # Normalize BQ column names if requested
            if normalize_columns:
                row = {normalize_column_name(k): v for k, v in row.items() if k is not None}

            transformed, warnings = self.transform_row(row, source_class, context_rows)
            report["rows_processed"] += 1
            report["warnings"].extend(warnings)

            if transformed:
                # Extract relocated fields into separate output
                relocated = transformed.pop("__relocated__", None)
                if relocated and isinstance(relocated, dict):
                    for target_key, value in relocated.items():
                        target_class, target_field = target_key.split("/", 1)
                        relocated_rows.setdefault(target_class, [])
                        # Find or create row for this target class
                        if not relocated_rows[target_class] or \
                                len(relocated_rows[target_class]) < report["rows_processed"]:
                            relocated_rows[target_class].append({})
                        relocated_rows[target_class][-1][target_field] = value

                output_rows.append(transformed)
                all_target_columns.update(transformed.keys())
                report["rows_succeeded"] += 1

        # Apply defaults for all rows
        target_columns = sorted(all_target_columns)
        for default in self.defaults:
            if default.get("class") == self._target_class_for(source_class):
                col = default["field"]
                if col not in target_columns:
                    target_columns.append(col)
                for row in output_rows:
                    if col not in row or row[col] == "":
                        row[col] = default.get("default", "")
                        if default.get("required") and not row[col]:
                            report["warnings"].append(
                                f"Row {output_rows.index(row) + 1}: "
                                f"Required field {col} has no value and no default"
                            )

        # Write main output TSV
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=target_columns, delimiter="\t", extrasaction="ignore")
            writer.writeheader()
            for row in output_rows:
                writer.writerow(row)

        # Write relocated class TSVs
        for target_class, rows in relocated_rows.items():
            relocated_cols = sorted({k for r in rows for k in r.keys()})
            relocated_path = output_file.parent / f"{output_file.stem}_{target_class}{output_file.suffix}"
            with open(relocated_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=relocated_cols, delimiter="\t", extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
            report["relocated_files"][target_class] = str(relocated_path)

        # Count transformed values
        report["values_transformed"] = sum(
            1 for row in output_rows for v in row.values() if v
        )

        # Field coverage
        mapped_fields = set()
        effective_columns = [normalize_column_name(c) for c in source_columns] if normalize_columns else source_columns
        for col in effective_columns:
            key = f"{source_class}/{col}"
            if key in self.field_map:
                mapped_fields.add(col)
        report["field_coverage"] = {
            "source_fields": len(effective_columns),
            "mapped_fields": len(mapped_fields),
            "unmapped_fields": [c for c in effective_columns if c not in mapped_fields],
        }

        return report

    def _target_class_for(self, source_class: str) -> str:
        """Find the target class for a source class from field mappings."""
        for key, mapping in self.field_map.items():
            if key.startswith(f"{source_class}/"):
                return mapping["target_class"]
        return source_class

    def transform_row(
        self,
        row: dict,
        source_class: str,
        context_rows: dict[str, list[dict]] | None = None,
    ) -> tuple[dict, list[str]]:
        """Apply all five tiers of transformation to a single row.

        Returns:
            (transformed_row, warnings)
        """
        warnings = []
        result = {}
        relocated = {}  # Fields that should go to a different output table

        # Tier 1: Field renaming
        for source_col, value in row.items():
            key = f"{source_class}/{source_col}"
            mapping = self.field_map.get(key)
            if mapping:
                target_field = mapping["target_field"]
                result[target_field] = value
            else:
                # Keep unmapped fields with a prefix for debugging
                warnings.append(f"Unmapped field: {source_col}")

        # Tier 2: Value remapping
        for source_col, value in row.items():
            key = f"{source_class}/{source_col}"
            value_mappings = self.value_map.get(key, {})
            mapping = self.field_map.get(key)
            if mapping and value in value_mappings:
                target_field = mapping["target_field"]
                result[target_field] = value_mappings[value]

        # Tier 3: Conversions
        for conv in self.conversions:
            src = conv.get("source", {})
            tgt = conv.get("target", {})
            if src.get("class") != source_class:
                continue

            source_field = src.get("field", "")
            target_field = tgt.get("field", "")
            source_value = row.get(source_field, "")

            if not source_value or source_value.strip() == "":
                continue

            conv_type = conv.get("type", "")

            if conv_type == "years_to_days":
                try:
                    years = float(source_value)
                    multiplier = conv.get("multiplier", 365.25)
                    result[target_field] = str(int(round(years * multiplier)))
                except (ValueError, TypeError):
                    warnings.append(
                        f"Could not convert '{source_value}' from years to days for {source_field}"
                    )

            elif conv_type == "age_days_auto":
                # Auto-detect: if value > threshold, assume already in days;
                # if <= threshold, assume years and convert.
                # BQ stores Age_at_Diagnosis in days; model spec says years.
                threshold = conv.get("years_threshold", 200)
                try:
                    val = float(source_value)
                    if val > threshold:
                        # Already in days
                        result[target_field] = str(int(round(val)))
                    else:
                        # Assume years, convert to days
                        multiplier = conv.get("multiplier", 365.25)
                        result[target_field] = str(int(round(val * multiplier)))
                except (ValueError, TypeError):
                    warnings.append(
                        f"Could not convert '{source_value}' for {source_field}"
                    )

            elif conv_type == "days_from_index_to_age":
                # Convert "days from index date" to "age in days"
                # Requires birth date reference from another class
                birth_ref = conv.get("birth_reference", {})
                birth_class = birth_ref.get("class", "")
                birth_field = birth_ref.get("field", "")
                birth_value = None

                if context_rows and birth_class in context_rows:
                    for ctx_row in context_rows[birth_class]:
                        if birth_field in ctx_row and ctx_row[birth_field]:
                            birth_value = ctx_row[birth_field]
                            break

                if birth_value is not None:
                    try:
                        days_from_index = float(source_value)
                        days_to_birth = float(birth_value)
                        # days_to_birth is typically negative (before index)
                        age_in_days = abs(days_to_birth) + days_from_index
                        result[target_field] = str(int(round(age_in_days)))
                    except (ValueError, TypeError):
                        warnings.append(
                            f"Could not compute age for {source_field}: "
                            f"value={source_value}, birth={birth_value}"
                        )
                else:
                    warnings.append(
                        f"No birth reference found for {source_field} conversion"
                    )

            elif conv_type == "text_to_ontology":
                lookup_path = conv.get("lookup", "")
                lookup = self._get_lookup(lookup_path)
                normalized_value = source_value.strip().lower()
                code = lookup.get(normalized_value)
                # Try stripping common ICD-O suffixes (NOS, NEC, etc.)
                if not code:
                    for suffix in [" nos", ", nos", " nec", ", nec", " not otherwise specified"]:
                        if normalized_value.endswith(suffix):
                            stripped = normalized_value[: -len(suffix)].strip()
                            code = lookup.get(stripped)
                            if code:
                                break
                if code:
                    result[target_field] = code
                else:
                    warnings.append(
                        f"No ontology code found for '{source_value}' in {lookup_path}"
                    )
                    # Keep the original text as fallback
                    result[target_field] = source_value

        # Tier 4: Structural transforms
        for struct in self.structural:
            struct_type = struct.get("type", "")
            src = struct.get("source", {})

            if src.get("class") != source_class:
                continue

            source_field = src.get("field", "")
            source_value = row.get(source_field, "")

            if struct_type == "field_split":
                targets = struct.get("targets", [])
                for target in targets:
                    target_field = target.get("field", "")
                    # For splits, copy the value to all targets
                    # Value remapping in tier 2 may have already differentiated them
                    if target_field not in result:
                        result[target_field] = source_value

            elif struct_type == "class_relocation":
                tgt = struct.get("target", {})
                target_class = tgt.get("class", "")
                target_field = tgt.get("field", "")
                relocated[f"{target_class}/{target_field}"] = source_value
                # Remove from current result if it was placed there by tier 1
                result.pop(target_field, None)

        # Store relocated fields in a special key for the caller to handle
        if relocated:
            result["__relocated__"] = relocated

        return result, warnings


def main():
    parser = argparse.ArgumentParser(description="Migrate HTAN Phase 1 data to Phase 2 format")
    parser.add_argument("--input", required=True, help="Input HTAN1 TSV file")
    parser.add_argument("--config", required=True, help="Transform config YAML")
    parser.add_argument("--source-class", required=True, help="Source class name (e.g., Demographics)")
    parser.add_argument("--output", required=True, help="Output HTAN2 TSV file")
    parser.add_argument("--context", action="append", default=[], help="Context TSV files as class:path pairs")
    parser.add_argument("--normalize-columns", action="store_true",
                        help="Normalize BQ-style column names (underscores to spaces)")
    parser.add_argument("--validate", action="store_true", help="Validate output against HTAN2 schema")
    parser.add_argument("--report", help="Path to write JSON migration report")
    args = parser.parse_args()

    # Parse context files
    context_rows = {}
    for ctx in args.context:
        if ":" in ctx:
            cls_name, ctx_path = ctx.split(":", 1)
            ctx_data = Path(ctx_path).read_text()
            reader = csv.DictReader(StringIO(ctx_data), delimiter="\t")
            context_rows[cls_name] = list(reader)

    engine = MigrationEngine(args.config)
    report = engine.migrate_file(
        args.input, args.source_class, args.output, context_rows,
        normalize_columns=args.normalize_columns,
    )

    # Print summary
    print(f"Migration complete: {args.source_class}")
    print(f"  Rows processed:    {report['rows_processed']}")
    print(f"  Rows succeeded:    {report['rows_succeeded']}")
    print(f"  Warnings:          {len(report['warnings'])}")
    print(f"  Errors:            {len(report['errors'])}")
    coverage = report.get("field_coverage", {})
    print(f"  Field coverage:    {coverage.get('mapped_fields', 0)}/{coverage.get('source_fields', 0)}")
    if coverage.get("unmapped_fields"):
        print(f"  Unmapped fields:   {', '.join(coverage['unmapped_fields'][:10])}")
    if report.get("relocated_files"):
        for cls, path in report["relocated_files"].items():
            print(f"  Relocated → {cls}: {path}")

    # Optionally validate
    if args.validate:
        try:
            from validate_transformed import validate_file
            validation = validate_file(args.output, engine._target_class_for(args.source_class))
            report["validation"] = validation
            if validation.get("errors"):
                print(f"  Validation errors: {len(validation['errors'])}")
            else:
                print(f"  Validation: PASSED ({validation.get('rows_valid', 0)} rows valid)")
        except ImportError:
            print("  Validation skipped (validate_transformed not available)")

    # Write report
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        print(f"  Report:            {args.report}")


if __name__ == "__main__":
    main()
