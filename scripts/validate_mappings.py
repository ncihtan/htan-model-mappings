#!/usr/bin/env python3
"""Validate SSSOM mapping files and report summary statistics.

Usage:
    python validate_mappings.py mappings/htan1_to_htan2/
    python validate_mappings.py mappings/htan1_to_htan2/fields.sssom.tsv
"""

import argparse
import sys
from pathlib import Path

try:
    from sssom.parsers import parse_sssom_table
    from sssom.validators import validate

    HAS_SSSOM = True
except (ImportError, AttributeError):
    HAS_SSSOM = False


def parse_sssom_tsv_basic(filepath: Path) -> dict:
    """Basic SSSOM TSV parser for when sssom-py is not available.

    Parses the YAML metadata header and TSV body.
    """
    content = filepath.read_text()
    lines = content.strip().split("\n")

    # Separate metadata (lines starting with #) from data
    metadata_lines = []
    data_lines = []
    for line in lines:
        if line.startswith("#"):
            metadata_lines.append(line.lstrip("#").strip())
        else:
            data_lines.append(line)

    # Parse TSV body
    if not data_lines:
        return {"metadata": metadata_lines, "mappings": [], "header": []}

    header = data_lines[0].split("\t")
    mappings = []
    for line in data_lines[1:]:
        if not line.strip():
            continue
        values = line.split("\t")
        row = dict(zip(header, values))
        mappings.append(row)

    return {"metadata": metadata_lines, "mappings": mappings, "header": header}


def validate_file(filepath: Path) -> dict:
    """Validate a single SSSOM TSV file. Returns a report dict."""
    report = {
        "file": str(filepath),
        "valid": True,
        "errors": [],
        "warnings": [],
        "stats": {},
    }

    if not filepath.exists():
        report["valid"] = False
        report["errors"].append(f"File not found: {filepath}")
        return report

    # Basic structural validation
    parsed = parse_sssom_tsv_basic(filepath)
    mappings = parsed["mappings"]
    header = parsed["header"]

    # Check required columns
    required_cols = [
        "subject_id",
        "subject_label",
        "predicate_id",
        "object_id",
        "object_label",
        "mapping_justification",
        "confidence",
    ]
    missing_cols = [col for col in required_cols if col not in header]
    if missing_cols:
        report["errors"].append(f"Missing required columns: {missing_cols}")
        report["valid"] = False

    # Check valid predicates
    valid_predicates = {
        "skos:exactMatch",
        "skos:closeMatch",
        "skos:narrowMatch",
        "skos:broadMatch",
        "skos:relatedMatch",
        "skos:noMappingFound",
    }
    for i, m in enumerate(mappings):
        pred = m.get("predicate_id", "")
        if pred and pred not in valid_predicates:
            report["warnings"].append(
                f"Row {i + 1}: Unknown predicate '{pred}'"
            )

        # Check confidence is a valid float
        conf = m.get("confidence", "")
        if conf:
            try:
                c = float(conf)
                if not 0.0 <= c <= 1.0:
                    report["warnings"].append(
                        f"Row {i + 1}: Confidence {c} outside [0,1]"
                    )
            except ValueError:
                report["errors"].append(
                    f"Row {i + 1}: Invalid confidence value '{conf}'"
                )
                report["valid"] = False

    # Compute statistics
    predicate_counts = {}
    confidence_values = []
    for m in mappings:
        pred = m.get("predicate_id", "unknown")
        predicate_counts[pred] = predicate_counts.get(pred, 0) + 1
        try:
            confidence_values.append(float(m.get("confidence", 0)))
        except ValueError:
            pass

    report["stats"] = {
        "total_mappings": len(mappings),
        "predicate_distribution": predicate_counts,
        "avg_confidence": (
            sum(confidence_values) / len(confidence_values)
            if confidence_values
            else 0.0
        ),
        "min_confidence": min(confidence_values) if confidence_values else 0.0,
        "max_confidence": max(confidence_values) if confidence_values else 0.0,
    }

    # Use sssom-py validation if available
    if HAS_SSSOM:
        try:
            msdf = parse_sssom_table(str(filepath))
            validation_results = validate(msdf)
            if validation_results:
                for vr in validation_results:
                    report["warnings"].append(f"sssom-py: {vr}")
        except Exception as e:
            report["warnings"].append(f"sssom-py validation error: {e}")

    return report


def validate_directory(dirpath: Path) -> list[dict]:
    """Validate all SSSOM TSV files in a directory."""
    reports = []
    sssom_files = sorted(dirpath.glob("*.sssom.tsv"))
    if not sssom_files:
        print(f"No *.sssom.tsv files found in {dirpath}", file=sys.stderr)
        return reports

    for f in sssom_files:
        reports.append(validate_file(f))
    return reports


def print_report(reports: list[dict]):
    """Print validation reports to console."""
    all_valid = True
    total_mappings = 0

    for report in reports:
        filepath = report["file"]
        stats = report.get("stats", {})
        n = stats.get("total_mappings", 0)
        total_mappings += n

        status = "PASS" if report["valid"] else "FAIL"
        if not report["valid"]:
            all_valid = False

        print(f"\n{'=' * 60}")
        print(f"  {filepath}")
        print(f"  Status: {status}")
        print(f"  Mappings: {n}")

        if stats.get("predicate_distribution"):
            print(f"  Predicates:")
            for pred, count in sorted(stats["predicate_distribution"].items()):
                print(f"    {pred}: {count}")

        if n > 0:
            print(
                f"  Confidence: avg={stats['avg_confidence']:.2f}, "
                f"min={stats['min_confidence']:.2f}, "
                f"max={stats['max_confidence']:.2f}"
            )

        for err in report.get("errors", []):
            print(f"  ERROR: {err}")
        for warn in report.get("warnings", []):
            print(f"  WARN: {warn}")

    print(f"\n{'=' * 60}")
    print(f"  Total files: {len(reports)}")
    print(f"  Total mappings: {total_mappings}")
    print(f"  Overall: {'ALL PASSED' if all_valid else 'SOME FAILED'}")
    print(f"{'=' * 60}")

    return all_valid


def main():
    parser = argparse.ArgumentParser(description="Validate SSSOM mapping files")
    parser.add_argument(
        "path",
        help="Path to SSSOM TSV file or directory containing *.sssom.tsv files",
    )
    args = parser.parse_args()

    path = Path(args.path)
    if path.is_file():
        reports = [validate_file(path)]
    elif path.is_dir():
        reports = validate_directory(path)
    else:
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    if not reports:
        print("No files to validate.", file=sys.stderr)
        sys.exit(1)

    all_valid = print_report(reports)
    sys.exit(0 if all_valid else 1)


if __name__ == "__main__":
    main()
