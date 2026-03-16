#!/usr/bin/env python3
"""Deterministic matching pass: match fields by caDSR ID and exact normalized name.

This handles ~60-70% of mappings cheaply and deterministically before
handing off remaining fields to semantic (LLM) matching.

Usage:
    python deterministic_match.py --source source.json --target target.json --output matches/
"""

import argparse
import json
import sys
from pathlib import Path


def load_model(path: str) -> dict:
    """Load a normalized model JSON file."""
    return json.loads(Path(path).read_text())


def build_field_index(model: dict) -> dict:
    """Build lookup indices for a model's fields.

    Returns dict with:
        by_cadsr: {cadsr_id: [(class_name, field)]}
        by_normalized_name: {normalized_name: [(class_name, field)]}
        all_fields: [(class_name, field)]
    """
    by_cadsr: dict[str, list[tuple[str, dict]]] = {}
    by_normalized_name: dict[str, list[tuple[str, dict]]] = {}
    all_fields: list[tuple[str, dict]] = []

    for cls in model.get("classes", []):
        cls_name = cls["name"]
        for field in cls.get("fields", []):
            entry = (cls_name, field)
            all_fields.append(entry)

            cadsr_id = field.get("cadsr_id")
            if cadsr_id:
                by_cadsr.setdefault(cadsr_id, []).append(entry)

            norm_name = field.get("normalized_name", "")
            if norm_name:
                by_normalized_name.setdefault(norm_name, []).append(entry)

    return {
        "by_cadsr": by_cadsr,
        "by_normalized_name": by_normalized_name,
        "all_fields": all_fields,
    }


def make_field_id(model_id: str, class_name: str, field_name: str) -> str:
    """Create a CURIE-style field identifier."""
    # Use a simple prefix based on the model
    prefix = model_id.split("/")[-1].split("@")[0].replace("-", "_")
    return f"{prefix}:{class_name}/{field_name}"


def deterministic_match(source: dict, target: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Run deterministic matching between source and target models.

    Returns:
        matched: List of SSSOM-style mapping dicts
        unmatched_source: Source fields with no match
        unmatched_target: Target fields not mapped to
    """
    source_index = build_field_index(source)
    target_index = build_field_index(target)

    matched = []
    matched_source_keys = set()
    matched_target_keys = set()

    # Pass 1: Match by caDSR ID (highest confidence)
    for cadsr_id, source_entries in source_index["by_cadsr"].items():
        target_entries = target_index["by_cadsr"].get(cadsr_id, [])
        if not target_entries:
            continue

        for s_cls, s_field in source_entries:
            for t_cls, t_field in target_entries:
                s_key = (s_cls, s_field["name"])
                t_key = (t_cls, t_field["name"])
                if s_key in matched_source_keys:
                    continue

                matched.append({
                    "subject_id": make_field_id(source["model_id"], s_cls, s_field["name"]),
                    "subject_label": s_field["name"],
                    "subject_class": s_cls,
                    "predicate_id": "skos:exactMatch",
                    "object_id": make_field_id(target["model_id"], t_cls, t_field["name"]),
                    "object_label": t_field["name"],
                    "object_class": t_cls,
                    "mapping_justification": "semapv:DatabaseCrossReference",
                    "confidence": 1.0,
                    "comment": f"Matched by caDSR ID: {cadsr_id}",
                })
                matched_source_keys.add(s_key)
                matched_target_keys.add(t_key)
                break  # One match per source field

    # Pass 2: Match by exact normalized name (slightly lower confidence)
    for norm_name, source_entries in source_index["by_normalized_name"].items():
        target_entries = target_index["by_normalized_name"].get(norm_name, [])
        if not target_entries:
            continue

        for s_cls, s_field in source_entries:
            s_key = (s_cls, s_field["name"])
            if s_key in matched_source_keys:
                continue

            for t_cls, t_field in target_entries:
                t_key = (t_cls, t_field["name"])
                if t_key in matched_target_keys:
                    continue

                matched.append({
                    "subject_id": make_field_id(source["model_id"], s_cls, s_field["name"]),
                    "subject_label": s_field["name"],
                    "subject_class": s_cls,
                    "predicate_id": "skos:exactMatch",
                    "object_id": make_field_id(target["model_id"], t_cls, t_field["name"]),
                    "object_label": t_field["name"],
                    "object_class": t_cls,
                    "mapping_justification": "semapv:LexicalMatching",
                    "confidence": 0.9,
                    "comment": f"Matched by normalized name: {norm_name}",
                })
                matched_source_keys.add(s_key)
                matched_target_keys.add(t_key)
                break

    # Collect unmatched fields
    unmatched_source = []
    for s_cls, s_field in source_index["all_fields"]:
        if (s_cls, s_field["name"]) not in matched_source_keys:
            unmatched_source.append({
                "class": s_cls,
                "field": s_field,
                "field_id": make_field_id(source["model_id"], s_cls, s_field["name"]),
            })

    unmatched_target = []
    for t_cls, t_field in target_index["all_fields"]:
        if (t_cls, t_field["name"]) not in matched_target_keys:
            unmatched_target.append({
                "class": t_cls,
                "field": t_field,
                "field_id": make_field_id(target["model_id"], t_cls, t_field["name"]),
            })

    return matched, unmatched_source, unmatched_target


def main():
    parser = argparse.ArgumentParser(description="Deterministic field matching between two models")
    parser.add_argument("--source", required=True, help="Path to normalized source model JSON")
    parser.add_argument("--target", required=True, help="Path to normalized target model JSON")
    parser.add_argument("--output", required=True, help="Output directory for match results")
    args = parser.parse_args()

    source = load_model(args.source)
    target = load_model(args.target)

    matched, unmatched_source, unmatched_target = deterministic_match(source, target)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "matched_fields.json").write_text(json.dumps(matched, indent=2))
    (output_dir / "unmatched_source.json").write_text(json.dumps(unmatched_source, indent=2))
    (output_dir / "unmatched_target.json").write_text(json.dumps(unmatched_target, indent=2))

    print(f"Deterministic matching complete:")
    print(f"  Matched:          {len(matched)}")
    print(f"  Unmatched source: {len(unmatched_source)}")
    print(f"  Unmatched target: {len(unmatched_target)}")
    print(f"  Match rate:       {len(matched) / max(len(source_idx_all := [f for c in source.get('classes', []) for f in c.get('fields', [])]), 1) * 100:.1f}%")
    print(f"  Output:           {output_dir}")


if __name__ == "__main__":
    main()
