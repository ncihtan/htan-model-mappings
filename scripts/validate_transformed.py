#!/usr/bin/env python3
"""Validate transformed data against HTAN2 JSON Schema or LinkML definitions.

Supports:
- JSON Schema validation (preferred for HTAN2 — uses generated schemas)
- LinkML SchemaView validation (fallback)
- Basic structural validation (no schema)

Usage:
    # Validate against JSON Schema (recommended)
    python validate_transformed.py \
        --input output/htan1_to_htan2/htan1_Demographics.tsv \
        --json-schema /tmp/htan2_json_schemas/Demographics.json \
        --report validation_report.json

    # Validate a directory of outputs against a directory of schemas
    python validate_transformed.py \
        --input-dir output/htan1_to_htan2/ \
        --schema-dir /tmp/htan2_json_schemas/ \
        --report validation_report.json

    # Validate against LinkML
    python validate_transformed.py \
        --input output.tsv \
        --target-class Demographics \
        --schema /path/to/schema.yaml
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from io import StringIO
from pathlib import Path

try:
    import jsonschema

    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

try:
    from linkml_runtime.utils.schemaview import SchemaView

    HAS_LINKML = True
except ImportError:
    HAS_LINKML = False


def validate_with_json_schema(
    rows: list[dict],
    schema: dict,
    ignore_patterns: bool = False,
) -> dict:
    """Validate rows against a JSON Schema.

    Args:
        rows: List of row dicts
        schema: Parsed JSON Schema dict
        ignore_patterns: If True, skip pattern validation (useful for HTAN1 IDs)

    Returns validation report dict.
    """
    report = {
        "schema_type": "json-schema",
        "rows_total": len(rows),
        "rows_valid": 0,
        "rows_invalid": 0,
        "error_summary": {},
        "errors": [],
    }

    error_counts = Counter()
    sample_errors = {}

    for i, row in enumerate(rows):
        # Build instance: skip empty values, convert types
        instance = {}
        for k, v in row.items():
            if v and v.strip():
                prop_schema = schema.get("properties", {}).get(k, {})
                if prop_schema.get("type") == "integer":
                    try:
                        instance[k] = int(float(v))
                    except (ValueError, TypeError):
                        instance[k] = v
                elif prop_schema.get("type") == "array":
                    # Parse JSON arrays from TSV cells
                    try:
                        parsed = json.loads(v)
                        if isinstance(parsed, list):
                            instance[k] = parsed
                        else:
                            instance[k] = v
                    except (json.JSONDecodeError, ValueError):
                        instance[k] = v
                else:
                    instance[k] = v

        errors = list(jsonschema.Draft7Validator(schema).iter_errors(instance))
        if ignore_patterns:
            errors = [e for e in errors if e.validator != "pattern"]

        if errors:
            report["rows_invalid"] += 1
            for e in errors:
                if e.validator == "enum":
                    path = list(e.absolute_path)
                    field = path[-1] if path else "?"
                    key = f"{field}: not in enum"
                    if key not in sample_errors:
                        sample_errors[key] = str(e.instance)[:50]
                elif e.validator == "required":
                    word = e.message.split(" ")[0].strip("'")
                    key = f"missing: {word}"
                elif e.validator == "pattern":
                    key = "pattern (HTAN ID)"
                elif e.validator == "type":
                    path = list(e.absolute_path)
                    field = path[-1] if path else "?"
                    key = f"{field}: wrong type"
                    if key not in sample_errors:
                        sample_errors[key] = str(e.instance)[:50]
                else:
                    key = f"{e.validator}: {str(e.message)[:60]}"
                error_counts[key] += 1
                if len(report["errors"]) < 100:
                    report["errors"].append(
                        f"Row {i + 1}: {e.validator} - {str(e.message)[:120]}"
                    )
        else:
            report["rows_valid"] += 1

    report["error_summary"] = {
        k: {"count": v, "sample": sample_errors.get(k, "")}
        for k, v in error_counts.most_common()
    }

    return report


def validate_with_schemaview(
    rows: list[dict],
    schema_path: str,
    target_class: str,
) -> dict:
    """Validate rows against a LinkML schema using SchemaView."""
    sv = SchemaView(schema_path)

    report = {
        "schema_type": "linkml",
        "schema": schema_path,
        "target_class": target_class,
        "rows_total": len(rows),
        "rows_valid": 0,
        "rows_invalid": 0,
        "error_summary": {},
        "errors": [],
    }

    cls_def = sv.get_class(target_class)
    if cls_def is None:
        report["errors"].append(f"Class '{target_class}' not found in schema")
        return report

    class_slots = {}
    for slot_name in sv.class_slots(target_class):
        slot = sv.get_slot(slot_name)
        if slot:
            class_slots[slot_name] = slot

    required_slots = {n for n, s in class_slots.items() if s.required}
    enum_values = {}
    for slot_name, slot in class_slots.items():
        if slot.range and sv.get_enum(slot.range):
            enum_def = sv.get_enum(slot.range)
            if enum_def and enum_def.permissible_values:
                enum_values[slot_name] = set(enum_def.permissible_values.keys())

    error_counts = Counter()
    for i, row in enumerate(rows):
        row_errors = []
        for req in required_slots:
            if req not in row or not row[req] or row[req].strip() == "":
                row_errors.append(f"missing: {req}")
                error_counts[f"missing: {req}"] += 1
        for slot_name, valid_vals in enum_values.items():
            if slot_name in row and row[slot_name]:
                val = row[slot_name].strip()
                if val and val not in valid_vals:
                    key = f"{slot_name}: not in enum"
                    row_errors.append(key)
                    error_counts[key] += 1
        if row_errors:
            report["rows_invalid"] += 1
        else:
            report["rows_valid"] += 1

    report["error_summary"] = {k: {"count": v} for k, v in error_counts.most_common()}
    return report


def validate_basic(rows: list[dict]) -> dict:
    """Basic validation: check for empty rows."""
    report = {
        "schema_type": "basic",
        "rows_total": len(rows),
        "rows_valid": 0,
        "rows_invalid": 0,
        "error_summary": {},
        "errors": [],
    }
    for i, row in enumerate(rows):
        if all(not v or v.strip() == "" for v in row.values()):
            report["errors"].append(f"Row {i + 1}: All fields are empty")
            report["rows_invalid"] += 1
        else:
            report["rows_valid"] += 1
    return report


def validate_file(
    input_path: str,
    target_class: str = "",
    schema_path: str | None = None,
    json_schema_path: str | None = None,
    ignore_patterns: bool = False,
) -> dict:
    """Validate a transformed TSV file."""
    content = Path(input_path).read_text()
    reader = csv.DictReader(StringIO(content), delimiter="\t")
    rows = list(reader)

    if json_schema_path and HAS_JSONSCHEMA:
        schema = json.loads(Path(json_schema_path).read_text())
        report = validate_with_json_schema(rows, schema, ignore_patterns)
        report["input"] = input_path
        report["json_schema"] = json_schema_path
        return report

    if schema_path and HAS_LINKML:
        report = validate_with_schemaview(rows, schema_path, target_class)
        report["input"] = input_path
        return report

    report = validate_basic(rows)
    report["input"] = input_path
    return report


def validate_directory(
    input_dir: str,
    schema_dir: str,
    ignore_patterns: bool = False,
) -> list[dict]:
    """Validate all TSV files in a directory against matching JSON schemas.

    Matches files by class name: htan1_Demographics.tsv → Demographics.json
    """
    reports = []
    input_path = Path(input_dir)
    schema_path = Path(schema_dir)

    for tsv_file in sorted(input_path.glob("*.tsv")):
        # Extract class name: htan1_Demographics.tsv → Demographics
        stem = tsv_file.stem
        parts = stem.split("_", 1)
        cls_name = parts[1] if len(parts) > 1 else parts[0]

        json_schema = schema_path / f"{cls_name}.json"
        if not json_schema.exists():
            continue

        report = validate_file(
            str(tsv_file),
            json_schema_path=str(json_schema),
            ignore_patterns=ignore_patterns,
        )
        report["target_class"] = cls_name
        reports.append(report)

    return reports


def print_report(reports: list[dict]):
    """Print validation summary."""
    total_valid = 0
    total_rows = 0

    for report in reports:
        n = report["rows_total"]
        v = report["rows_valid"]
        total_valid += v
        total_rows += n
        pct = v / n * 100 if n else 0
        cls = report.get("target_class", report.get("input", "?"))

        print(f"\n{cls}: {v}/{n} valid ({pct:.1f}%)")

        summaries = report.get("error_summary", {})
        if summaries:
            for err, detail in list(summaries.items())[:10]:
                count = detail["count"]
                sample = detail.get("sample", "")
                suffix = f"  ('{sample}')" if sample else ""
                print(f"  {count:>5}x  {err}{suffix}")

    if len(reports) > 1:
        pct = total_valid / total_rows * 100 if total_rows else 0
        print(f"\nTotal: {total_valid}/{total_rows} valid ({pct:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Validate transformed HTAN2 data")
    parser.add_argument("--input", help="Transformed TSV file")
    parser.add_argument("--input-dir", help="Directory of transformed TSV files")
    parser.add_argument("--target-class", help="Target class name (for LinkML)")
    parser.add_argument("--schema", help="Path to LinkML schema YAML")
    parser.add_argument("--json-schema", help="Path to JSON Schema file")
    parser.add_argument("--schema-dir", help="Directory of JSON Schema files")
    parser.add_argument("--ignore-patterns", action="store_true",
                        help="Skip pattern validation (useful for HTAN1 IDs)")
    parser.add_argument("--report", help="Output validation report JSON")
    args = parser.parse_args()

    if args.input_dir and args.schema_dir:
        reports = validate_directory(args.input_dir, args.schema_dir, args.ignore_patterns)
    elif args.input:
        report = validate_file(
            args.input,
            target_class=args.target_class or "",
            schema_path=args.schema,
            json_schema_path=args.json_schema,
            ignore_patterns=args.ignore_patterns,
        )
        reports = [report]
    else:
        parser.error("Provide --input or --input-dir")
        return

    if not reports:
        print("No files to validate.", file=sys.stderr)
        sys.exit(1)

    print_report(reports)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(reports, indent=2))
        print(f"\nReport: {args.report}")

    all_valid = all(r["rows_invalid"] == 0 for r in reports)
    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
