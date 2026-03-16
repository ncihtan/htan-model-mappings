#!/usr/bin/env python3
"""Build static lookup tables from HTAN2 enum YAML files.

Extracts permissible_values from LinkML enum definitions and inverts them
to create {normalized_label: code} lookup tables for ontology-coded fields.

Usage:
    python build_lookup_tables.py \
        --enum-dir /tmp/htan2_enums/ \
        --output lookups/

    # Or fetch from GitHub directly:
    python build_lookup_tables.py \
        --repo ncihtan/htan2-data-model \
        --tag v1.3.0 \
        --output lookups/
"""

import argparse
import json
import sys
from pathlib import Path

import yaml


def parse_enum_yaml(content: str) -> dict[str, dict]:
    """Parse a LinkML enum YAML file and return {enum_name: {pv_key: description}}."""
    data = yaml.safe_load(content)
    if not data:
        return {}

    enums = data.get("enums", {})
    result = {}
    for enum_name, enum_def in enums.items():
        if not isinstance(enum_def, dict):
            continue
        pvs = enum_def.get("permissible_values", {})
        if not isinstance(pvs, dict):
            continue
        result[enum_name] = {}
        for pv_key, pv_def in pvs.items():
            desc = ""
            if isinstance(pv_def, dict):
                desc = pv_def.get("description", "") or pv_def.get("title", "") or ""
            result[enum_name][str(pv_key)] = str(desc)
    return result


def invert_enum_to_lookup(
    enum_values: dict[str, str],
    prefix: str = "",
) -> dict[str, str]:
    """Invert {code: description} to {normalized_description: code}.

    For ontology-coded enums like UBERON or NCI-T, the key is the code
    (e.g., "UBERON:0000310") and description is the label (e.g., "breast").
    We invert to {label: code} for text-to-ontology lookups.

    Also indexes by the code itself (lowercased) for direct code lookups.
    """
    lookup = {}
    for code, description in enum_values.items():
        code_str = str(code).strip()
        if prefix and not code_str.startswith(prefix):
            continue

        # Index by lowercased description
        if description:
            desc_key = description.strip().lower()
            if desc_key and desc_key not in lookup:
                lookup[desc_key] = code_str

        # Also index by the code's local part (after the colon)
        if ":" in code_str:
            local = code_str.split(":", 1)[1].strip().lower()
            if local and local not in lookup:
                lookup[local] = code_str

    return lookup


def build_lookup_from_enum_dir(
    enum_dir: Path,
    enum_name_pattern: str,
    code_prefix: str = "",
) -> dict[str, str]:
    """Scan a directory of enum YAMLs and build a lookup for a specific enum pattern."""
    lookup = {}
    for yaml_file in sorted(enum_dir.rglob("*.yaml")):
        try:
            content = yaml_file.read_text()
            enums = parse_enum_yaml(content)
        except Exception as e:
            print(f"Warning: Could not parse {yaml_file}: {e}", file=sys.stderr)
            continue

        for enum_name, enum_values in enums.items():
            name_lower = enum_name.lower()
            if enum_name_pattern.lower() in name_lower:
                inverted = invert_enum_to_lookup(enum_values, code_prefix)
                lookup.update(inverted)

    return lookup


def build_uberon_lookup(enum_dir: Path) -> dict[str, str]:
    """Build UBERON label-to-code lookup from HTAN2 enum files."""
    return build_lookup_from_enum_dir(enum_dir, "uberon", "UBERON:")


def build_ncit_diagnosis_lookup(enum_dir: Path) -> dict[str, str]:
    """Build NCI Thesaurus diagnosis label-to-code lookup from HTAN2 enum files."""
    # NCI-T codes use bare C-codes (e.g., "C100012") not prefixed with "ncit:"
    return build_lookup_from_enum_dir(enum_dir, "ncit", "")


def main():
    parser = argparse.ArgumentParser(description="Build lookup tables from HTAN2 enum YAMLs")
    parser.add_argument("--enum-dir", required=True, help="Directory containing enum YAML files")
    parser.add_argument("--output", required=True, help="Output directory for lookup JSON files")
    args = parser.parse_args()

    enum_dir = Path(args.enum_dir)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not enum_dir.exists():
        print(f"Enum directory not found: {enum_dir}", file=sys.stderr)
        sys.exit(1)

    # Build UBERON lookup
    uberon = build_uberon_lookup(enum_dir)
    uberon_path = output_dir / "uberon_labels_to_codes.json"
    uberon_path.write_text(json.dumps(uberon, indent=2, sort_keys=True))
    print(f"UBERON lookup: {len(uberon)} entries -> {uberon_path}")

    # Build NCI-T diagnosis lookup
    ncit = build_ncit_diagnosis_lookup(enum_dir)
    ncit_path = output_dir / "ncit_diagnosis_to_codes.json"
    ncit_path.write_text(json.dumps(ncit, indent=2, sort_keys=True))
    print(f"NCI-T diagnosis lookup: {len(ncit)} entries -> {ncit_path}")


if __name__ == "__main__":
    main()
