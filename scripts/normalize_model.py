#!/usr/bin/env python3
"""Normalize any supported data model format into a common JSON structure.

Supports:
- Schematic CSV (HTAN Phase 1): *.model.csv with Attribute/Parent/Source columns
- LinkML (HTAN Phase 2): YAML with classes/slots/enums
- JSON Schema (GDC-style): JSON with properties/$ref

Usage:
    python normalize_model.py --repo owner/repo --tag v1.0.0 --format auto --output normalized.json
    python normalize_model.py --path /local/path/to/model --format linkml --output normalized.json
"""

import argparse
import csv
import json
import re
import sys
from io import StringIO
from pathlib import Path

import yaml


def normalize_name(name: str) -> str:
    """Convert any field name to lowercase_underscore form."""
    # Handle UPPER_SNAKE_CASE
    if name.isupper() or "_" in name:
        return name.lower().strip()
    # Handle Title Case / camelCase → snake_case
    s = re.sub(r"([A-Z])", r"_\1", name).strip("_").lower()
    # Collapse multiple underscores and spaces
    s = re.sub(r"[\s_]+", "_", s)
    return s


def extract_cadsr_id(source_str: str) -> str | None:
    """Extract caDSR ID from a Source URL string."""
    if not source_str:
        return None
    match = re.search(r"CDEDD\.ITEM_ID=(\d+)", source_str)
    if match:
        return match.group(1)
    # Also handle slot_uri format: caDSR:2192217
    match = re.search(r"caDSR:(\d+)", source_str)
    if match:
        return match.group(1)
    return None


def parse_schematic_csv(content: str, model_id: str) -> dict:
    """Parse a Schematic-style CSV model file."""
    reader = csv.DictReader(StringIO(content))
    classes: dict[str, list[dict]] = {}

    for row in reader:
        attr = row.get("Attribute", "").strip()
        if not attr:
            continue

        parent = row.get("Parent", "").strip()
        if not parent:
            continue

        # Build field entry
        source = row.get("Source", "")
        valid_values_str = row.get("Valid Values", "")
        valid_values = (
            [v.strip() for v in valid_values_str.split(",") if v.strip()]
            if valid_values_str
            else []
        )

        field = {
            "name": attr,
            "normalized_name": normalize_name(attr),
            "description": row.get("Description", "").strip(),
            "cadsr_id": extract_cadsr_id(source),
            "source_uri": source.strip() if source else None,
            "valid_values": valid_values,
            "required": row.get("Required", "").strip().lower() == "true",
        }

        classes.setdefault(parent, []).append(field)

    return {
        "model_id": model_id,
        "format": "schematic-csv",
        "classes": [
            {"name": cls_name, "fields": fields}
            for cls_name, fields in sorted(classes.items())
        ],
    }


def parse_linkml_yaml(yaml_content: str, model_id: str, file_path: str = "") -> dict:
    """Parse a LinkML YAML schema file."""
    data = yaml.safe_load(yaml_content)
    if not data:
        return {"model_id": model_id, "format": "linkml", "classes": []}

    classes = []

    # Handle schemas with classes and slots
    schema_classes = data.get("classes", {})
    schema_slots = data.get("slots", {})
    schema_enums = data.get("enums", {})

    for cls_name, cls_def in (schema_classes or {}).items():
        if not isinstance(cls_def, dict):
            continue
        fields = []
        slot_names = cls_def.get("attributes", {}) or cls_def.get("slots", [])

        if isinstance(slot_names, dict):
            # Inline attributes
            for slot_name, slot_def in slot_names.items():
                if not isinstance(slot_def, dict):
                    slot_def = {}
                fields.append(_linkml_slot_to_field(slot_name, slot_def, schema_enums))
        elif isinstance(slot_names, list):
            # References to top-level slots
            for slot_name in slot_names:
                slot_def = schema_slots.get(slot_name, {})
                if not isinstance(slot_def, dict):
                    slot_def = {}
                fields.append(_linkml_slot_to_field(slot_name, slot_def, schema_enums))

        if fields:
            classes.append({"name": cls_name, "fields": fields})

    return {
        "model_id": model_id,
        "format": "linkml",
        "classes": classes,
    }


def _linkml_slot_to_field(
    slot_name: str, slot_def: dict, enums: dict | None = None
) -> dict:
    """Convert a LinkML slot definition to our normalized field format."""
    # Extract caDSR ID from slot_uri
    slot_uri = slot_def.get("slot_uri", "")
    cadsr_id = extract_cadsr_id(str(slot_uri))

    # Get valid values from enum reference
    valid_values = []
    enum_range = slot_def.get("range", "")
    if enums and enum_range in enums:
        enum_def = enums[enum_range]
        if isinstance(enum_def, dict):
            pvs = enum_def.get("permissible_values", {})
            if isinstance(pvs, dict):
                valid_values = list(pvs.keys())

    return {
        "name": slot_name,
        "normalized_name": normalize_name(slot_name),
        "description": slot_def.get("description", ""),
        "cadsr_id": cadsr_id,
        "source_uri": slot_uri if slot_uri else None,
        "valid_values": valid_values,
        "required": slot_def.get("required", False),
    }


def parse_json_schema(content: str, model_id: str) -> dict:
    """Parse a JSON Schema model file (GDC-style)."""
    data = json.loads(content)
    classes = []

    # Top-level properties become a single class
    title = data.get("title", "Root")
    properties = data.get("properties", {})
    required_fields = set(data.get("required", []))

    if properties:
        fields = []
        for prop_name, prop_def in properties.items():
            if not isinstance(prop_def, dict):
                continue
            valid_values = prop_def.get("enum", [])
            fields.append(
                {
                    "name": prop_name,
                    "normalized_name": normalize_name(prop_name),
                    "description": prop_def.get("description", ""),
                    "cadsr_id": None,
                    "source_uri": None,
                    "valid_values": valid_values if valid_values else [],
                    "required": prop_name in required_fields,
                }
            )
        classes.append({"name": title, "fields": fields})

    return {
        "model_id": model_id,
        "format": "json-schema",
        "classes": classes,
    }


def detect_format(content: str, filename: str) -> str:
    """Auto-detect model format from file content and name."""
    if filename.endswith(".csv"):
        return "schematic-csv"
    if filename.endswith(".yaml") or filename.endswith(".yml"):
        return "linkml"
    if filename.endswith(".json"):
        return "json-schema"

    # Content-based detection
    if "Attribute" in content[:500] and "Parent" in content[:500]:
        return "schematic-csv"
    if "classes:" in content[:1000] or "slots:" in content[:1000]:
        return "linkml"
    if '"properties"' in content[:1000]:
        return "json-schema"

    return "unknown"


def normalize_model(
    content: str, model_id: str, fmt: str = "auto", filename: str = ""
) -> dict:
    """Normalize a model from any supported format to common JSON."""
    if fmt == "auto":
        fmt = detect_format(content, filename)

    if fmt == "schematic-csv":
        return parse_schematic_csv(content, model_id)
    elif fmt == "linkml":
        return parse_linkml_yaml(content, model_id)
    elif fmt == "json-schema":
        return parse_json_schema(content, model_id)
    else:
        raise ValueError(f"Unknown model format: {fmt}")


def merge_normalized_models(models: list[dict]) -> dict:
    """Merge multiple normalized model files into a single model.

    Useful for LinkML schemas split across multiple YAML files.
    """
    if not models:
        raise ValueError("No models to merge")
    if len(models) == 1:
        return models[0]

    merged = {
        "model_id": models[0]["model_id"],
        "format": models[0]["format"],
        "classes": [],
    }

    seen_classes: dict[str, dict] = {}
    for model in models:
        for cls in model.get("classes", []):
            cls_name = cls["name"]
            if cls_name in seen_classes:
                # Merge fields
                existing_names = {f["name"] for f in seen_classes[cls_name]["fields"]}
                for field in cls["fields"]:
                    if field["name"] not in existing_names:
                        seen_classes[cls_name]["fields"].append(field)
            else:
                seen_classes[cls_name] = {
                    "name": cls_name,
                    "fields": list(cls["fields"]),
                }

    merged["classes"] = list(seen_classes.values())
    return merged


def main():
    parser = argparse.ArgumentParser(description="Normalize a data model to common JSON format")
    parser.add_argument("--path", required=True, help="Path to model file or directory")
    parser.add_argument("--model-id", required=True, help="Model identifier (owner/repo@tag)")
    parser.add_argument("--format", default="auto", choices=["auto", "schematic-csv", "linkml", "json-schema"])
    parser.add_argument("--output", required=True, help="Output JSON file path")
    args = parser.parse_args()

    path = Path(args.path)

    if path.is_file():
        content = path.read_text()
        result = normalize_model(content, args.model_id, args.format, path.name)
    elif path.is_dir():
        # Collect all model files in directory
        models = []
        for f in sorted(path.rglob("*")):
            if f.suffix in (".csv", ".yaml", ".yml", ".json") and f.is_file():
                content = f.read_text()
                fmt = args.format if args.format != "auto" else detect_format(content, f.name)
                if fmt != "unknown":
                    models.append(normalize_model(content, args.model_id, fmt, f.name))
        if not models:
            print(f"No model files found in {path}", file=sys.stderr)
            sys.exit(1)
        result = merge_normalized_models(models)
    else:
        print(f"Path not found: {path}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    print(f"Wrote normalized model to {args.output} ({len(result['classes'])} classes)")


if __name__ == "__main__":
    main()
