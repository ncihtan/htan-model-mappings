#!/usr/bin/env python3
"""Validate transformed HTAN2 data against LinkML schema definitions.

Uses linkml-runtime's SchemaView to check:
- Required fields are present
- Values are within enum ranges
- Patterns match
- Numeric ranges are satisfied

Usage:
    python validate_transformed.py \
        --input htan2_demographics.tsv \
        --schema /path/to/htan2_schema.yaml \
        --target-class Demographics \
        --report validation_report.json
"""

import argparse
import csv
import json
import sys
from io import StringIO
from pathlib import Path

try:
    from linkml_runtime.utils.schemaview import SchemaView

    HAS_LINKML = True
except ImportError:
    HAS_LINKML = False


def validate_with_schemaview(
    rows: list[dict],
    schema_path: str,
    target_class: str,
) -> dict:
    """Validate rows against a LinkML schema using SchemaView.

    Returns validation report dict.
    """
    sv = SchemaView(schema_path)

    report = {
        "schema": schema_path,
        "target_class": target_class,
        "rows_total": len(rows),
        "rows_valid": 0,
        "rows_invalid": 0,
        "errors": [],
        "warnings": [],
    }

    cls_def = sv.get_class(target_class)
    if cls_def is None:
        report["errors"].append(f"Class '{target_class}' not found in schema")
        return report

    # Get class attributes
    class_slots = {}
    for slot_name in sv.class_slots(target_class):
        slot = sv.get_slot(slot_name)
        if slot:
            class_slots[slot_name] = slot

    # Get required slots
    required_slots = set()
    for slot_name, slot in class_slots.items():
        if slot.required:
            required_slots.add(slot_name)

    # Get enum ranges
    enum_values: dict[str, set[str]] = {}
    for slot_name, slot in class_slots.items():
        if slot.range and sv.get_enum(slot.range):
            enum_def = sv.get_enum(slot.range)
            if enum_def and enum_def.permissible_values:
                enum_values[slot_name] = set(enum_def.permissible_values.keys())

    for i, row in enumerate(rows):
        row_errors = []
        row_num = i + 1

        # Check required fields
        for req in required_slots:
            if req not in row or not row[req] or row[req].strip() == "":
                row_errors.append(f"Row {row_num}: Missing required field '{req}'")

        # Check enum values
        for slot_name, valid_vals in enum_values.items():
            if slot_name in row and row[slot_name]:
                val = row[slot_name].strip()
                if val and val not in valid_vals:
                    row_errors.append(
                        f"Row {row_num}: Value '{val}' not in enum for '{slot_name}'"
                    )

        # Check patterns
        for slot_name, slot in class_slots.items():
            if slot.pattern and slot_name in row and row[slot_name]:
                import re
                val = row[slot_name].strip()
                if val and not re.match(slot.pattern, val):
                    row_errors.append(
                        f"Row {row_num}: Value '{val}' doesn't match pattern "
                        f"'{slot.pattern}' for '{slot_name}'"
                    )

        # Check numeric ranges
        for slot_name, slot in class_slots.items():
            if slot_name in row and row[slot_name]:
                val_str = row[slot_name].strip()
                if not val_str:
                    continue
                if slot.minimum_value is not None or slot.maximum_value is not None:
                    try:
                        val = float(val_str)
                        if slot.minimum_value is not None and val < float(slot.minimum_value):
                            row_errors.append(
                                f"Row {row_num}: Value {val} below minimum "
                                f"{slot.minimum_value} for '{slot_name}'"
                            )
                        if slot.maximum_value is not None and val > float(slot.maximum_value):
                            row_errors.append(
                                f"Row {row_num}: Value {val} above maximum "
                                f"{slot.maximum_value} for '{slot_name}'"
                            )
                    except ValueError:
                        pass

        if row_errors:
            report["rows_invalid"] += 1
            report["errors"].extend(row_errors)
        else:
            report["rows_valid"] += 1

    return report


def validate_basic(rows: list[dict], target_class: str) -> dict:
    """Basic validation without linkml-runtime (structural checks only)."""
    report = {
        "schema": "none (basic validation)",
        "target_class": target_class,
        "rows_total": len(rows),
        "rows_valid": 0,
        "rows_invalid": 0,
        "errors": [],
        "warnings": [],
    }

    for i, row in enumerate(rows):
        row_num = i + 1
        # Check for completely empty rows
        if all(not v or v.strip() == "" for v in row.values()):
            report["errors"].append(f"Row {row_num}: All fields are empty")
            report["rows_invalid"] += 1
        else:
            report["rows_valid"] += 1

    return report


def validate_file(
    input_path: str,
    target_class: str,
    schema_path: str | None = None,
) -> dict:
    """Validate a transformed TSV file.

    Args:
        input_path: Path to transformed HTAN2 TSV
        target_class: Target class name
        schema_path: Optional path to LinkML schema YAML

    Returns:
        Validation report dict
    """
    content = Path(input_path).read_text()
    reader = csv.DictReader(StringIO(content), delimiter="\t")
    rows = list(reader)

    if schema_path and HAS_LINKML:
        return validate_with_schemaview(rows, schema_path, target_class)
    else:
        if schema_path and not HAS_LINKML:
            print(
                "Warning: linkml-runtime not available, falling back to basic validation",
                file=sys.stderr,
            )
        return validate_basic(rows, target_class)


def main():
    parser = argparse.ArgumentParser(description="Validate transformed HTAN2 data")
    parser.add_argument("--input", required=True, help="Transformed HTAN2 TSV file")
    parser.add_argument("--target-class", required=True, help="Target class name")
    parser.add_argument("--schema", help="Path to LinkML schema YAML")
    parser.add_argument("--report", help="Output validation report JSON")
    args = parser.parse_args()

    report = validate_file(args.input, args.target_class, args.schema)

    # Print summary
    print(f"Validation: {args.target_class}")
    print(f"  Rows total:   {report['rows_total']}")
    print(f"  Rows valid:   {report['rows_valid']}")
    print(f"  Rows invalid: {report['rows_invalid']}")
    print(f"  Errors:       {len(report['errors'])}")

    if report["errors"]:
        for err in report["errors"][:20]:
            print(f"    {err}")
        if len(report["errors"]) > 20:
            print(f"    ... and {len(report['errors']) - 20} more")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        print(f"  Report: {args.report}")

    sys.exit(0 if report["rows_invalid"] == 0 else 1)


if __name__ == "__main__":
    main()
