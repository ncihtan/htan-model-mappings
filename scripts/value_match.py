#!/usr/bin/env python3
"""Deterministic value matching within matched field pairs.

For every field pair in the field-level SSSOM where both sides have valid_values,
performs case-insensitive, normalized, and containment matching to produce
value-level SSSOM mappings.

Usage:
    python value_match.py \
        --source /tmp/htan1_clinical.json \
        --target /tmp/htan2_clinical.json \
        --field-sssom mappings/htan1_to_htan2/clinical_fields.sssom.tsv \
        --output mappings/htan1_to_htan2/ \
        --domain clinical
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Reuse from sibling modules
sys.path.insert(0, str(Path(__file__).parent))
from normalize_model import normalize_name
from validate_mappings import parse_sssom_tsv_basic
from deterministic_match import make_field_id


def normalize_value(value: str) -> str:
    """Normalize a value for matching: lowercase, strip, collapse whitespace/punct."""
    s = value.strip().lower()
    # Remove common suffixes that add no semantic content
    for suffix in ["biospecimen type", "type", "status"]:
        if s.endswith(suffix) and len(s) > len(suffix) + 1:
            candidate = s[: -len(suffix)].strip().rstrip("-_ ")
            if candidate:
                s = candidate
                break
    # Collapse whitespace and punctuation
    s = re.sub(r"[\s_\-/]+", "_", s)
    s = re.sub(r"[^\w]", "", s)
    return s


def load_field_sssom(filepath: Path) -> list[dict]:
    """Load field-level SSSOM TSV and return mapping rows."""
    parsed = parse_sssom_tsv_basic(filepath)
    return parsed["mappings"]


def build_value_index(model: dict) -> dict[str, dict[str, list[str]]]:
    """Build {class_name: {field_name: [valid_values]}} from normalized model."""
    index = {}
    for cls in model.get("classes", []):
        cls_name = cls["name"]
        for field in cls.get("fields", []):
            values = field.get("valid_values", [])
            if values:
                index.setdefault(cls_name, {})[field["name"]] = values
    return index


def extract_class_field(field_id: str) -> tuple[str, str]:
    """Extract (class_name, field_name) from a CURIE like 'prefix:Class/Field'."""
    # Split on first colon to get the local part
    local = field_id.split(":", 1)[-1]
    parts = local.split("/", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


def make_value_id(model_id: str, class_name: str, field_name: str, value: str) -> str:
    """Create a three-part CURIE: prefix:Class/Field/normalized_value."""
    prefix = model_id.split("/")[-1].split("@")[0].replace("-", "_")
    safe_value = normalize_name(value)
    return f"{prefix}:{class_name}/{field_name}/{safe_value}"


def match_values(
    source_values: list[str],
    target_values: list[str],
    source_model_id: str,
    target_model_id: str,
    source_class: str,
    source_field: str,
    target_class: str,
    target_field: str,
) -> tuple[list[dict], list[str], list[str]]:
    """Match values within a single field pair using three strategies.

    Returns:
        matched: List of value-level SSSOM mapping dicts
        unmatched_source: Source values with no match
        unmatched_target: Target values not matched to
    """
    matched = []
    matched_source = set()
    matched_target = set()

    # Build target lookup structures
    target_by_lower = {}
    target_by_normalized = {}
    for tv in target_values:
        lower = tv.strip().lower()
        target_by_lower.setdefault(lower, []).append(tv)
        norm = normalize_value(tv)
        target_by_normalized.setdefault(norm, []).append(tv)

    # Pass 1: Case-insensitive exact match
    for sv in source_values:
        if sv in matched_source:
            continue
        lower = sv.strip().lower()
        if lower in target_by_lower:
            tv = target_by_lower[lower][0]
            if tv not in matched_target:
                matched.append(_make_value_match(
                    sv, tv,
                    source_model_id, target_model_id,
                    source_class, source_field, target_class, target_field,
                    "skos:exactMatch", 1.0,
                    "semapv:LexicalMatching",
                    f"Case-insensitive exact match: '{sv}' = '{tv}'",
                ))
                matched_source.add(sv)
                matched_target.add(tv)

    # Pass 2: Normalized match
    for sv in source_values:
        if sv in matched_source:
            continue
        norm = normalize_value(sv)
        if norm in target_by_normalized:
            tv = target_by_normalized[norm][0]
            if tv not in matched_target:
                matched.append(_make_value_match(
                    sv, tv,
                    source_model_id, target_model_id,
                    source_class, source_field, target_class, target_field,
                    "skos:exactMatch", 0.9,
                    "semapv:LexicalMatching",
                    f"Normalized match: '{sv}' ~ '{tv}'",
                ))
                matched_source.add(sv)
                matched_target.add(tv)

    # Pass 3: Containment/substring match
    remaining_source = [sv for sv in source_values if sv not in matched_source]
    remaining_target = [tv for tv in target_values if tv not in matched_target]

    for sv in remaining_source:
        sv_lower = sv.strip().lower()
        if len(sv_lower) < 2:
            continue
        best_target = None
        best_len = 0
        for tv in remaining_target:
            if tv in matched_target:
                continue
            tv_lower = tv.strip().lower()
            if len(tv_lower) < 2:
                continue
            # Check if one contains the other
            if sv_lower in tv_lower or tv_lower in sv_lower:
                # Prefer longer match (more specific)
                match_len = min(len(sv_lower), len(tv_lower))
                if match_len > best_len:
                    best_target = tv
                    best_len = match_len
        if best_target is not None:
            matched.append(_make_value_match(
                sv, best_target,
                source_model_id, target_model_id,
                source_class, source_field, target_class, target_field,
                "skos:closeMatch", 0.7,
                "semapv:LexicalMatching",
                f"Containment match: '{sv}' ~ '{best_target}'",
            ))
            matched_source.add(sv)
            matched_target.add(best_target)

    unmatched_source = [sv for sv in source_values if sv not in matched_source]
    unmatched_target = [tv for tv in target_values if tv not in matched_target]

    return matched, unmatched_source, unmatched_target


def _make_value_match(
    source_value: str,
    target_value: str,
    source_model_id: str,
    target_model_id: str,
    source_class: str,
    source_field: str,
    target_class: str,
    target_field: str,
    predicate: str,
    confidence: float,
    justification: str,
    comment: str,
) -> dict:
    """Create a value-level SSSOM mapping dict."""
    return {
        "subject_id": make_value_id(source_model_id, source_class, source_field, source_value),
        "subject_label": source_value,
        "subject_match_field": make_field_id(source_model_id, source_class, source_field),
        "predicate_id": predicate,
        "object_id": make_value_id(target_model_id, target_class, target_field, target_value),
        "object_label": target_value,
        "object_match_field": make_field_id(target_model_id, target_class, target_field),
        "mapping_justification": justification,
        "confidence": confidence,
        "comment": comment,
    }


def value_match_for_domain(
    source_model: dict,
    target_model: dict,
    field_mappings: list[dict],
    min_field_confidence: float = 0.7,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Run value matching across all matched field pairs in a domain.

    Args:
        source_model: Normalized source model JSON
        target_model: Normalized target model JSON
        field_mappings: Field-level SSSOM mapping rows
        min_field_confidence: Only match values for field pairs above this confidence

    Returns:
        all_matched: All value-level matches
        all_unmatched_source: Per-field unmatched source values
        all_unmatched_target: Per-field unmatched target values
    """
    source_values = build_value_index(source_model)
    target_values = build_value_index(target_model)

    all_matched = []
    all_unmatched_source = []
    all_unmatched_target = []

    for mapping in field_mappings:
        confidence = float(mapping.get("confidence", 0))
        if confidence < min_field_confidence:
            continue

        # Skip noMappingFound entries
        predicate = mapping.get("predicate_id", "")
        if predicate == "skos:noMappingFound":
            continue

        source_class, source_field = extract_class_field(mapping["subject_id"])
        target_class, target_field = extract_class_field(mapping["object_id"])

        sv = source_values.get(source_class, {}).get(source_field, [])
        tv = target_values.get(target_class, {}).get(target_field, [])

        if not sv or not tv:
            continue

        matched, unmatched_s, unmatched_t = match_values(
            sv, tv,
            source_model["model_id"], target_model["model_id"],
            source_class, source_field, target_class, target_field,
        )

        all_matched.extend(matched)
        if unmatched_s:
            all_unmatched_source.append({
                "field": f"{source_class}/{source_field}",
                "target_field": f"{target_class}/{target_field}",
                "values": unmatched_s,
            })
        if unmatched_t:
            all_unmatched_target.append({
                "field": f"{target_class}/{target_field}",
                "source_field": f"{source_class}/{source_field}",
                "values": unmatched_t,
            })

    return all_matched, all_unmatched_source, all_unmatched_target


VALUE_SSSOM_COLUMNS = [
    "subject_id",
    "subject_label",
    "subject_match_field",
    "predicate_id",
    "object_id",
    "object_label",
    "object_match_field",
    "mapping_justification",
    "confidence",
    "comment",
]


def matches_to_value_sssom_tsv(
    matches: list[dict], source_id: str, target_id: str, domain: str
) -> str:
    """Convert value matches to SSSOM TSV with metadata header."""
    from datetime import date

    today = date.today().isoformat()
    source_prefix = source_id.split("/")[-1].split("@")[0].replace("-", "_")
    target_prefix = target_id.split("/")[-1].split("@")[0].replace("-", "_")

    header = f"""#curie_map:
#  skos: http://www.w3.org/2004/02/skos/core#
#  semapv: https://w3id.org/semapv/vocab/
#  {source_prefix}: https://data.humantumoratlas.org/{source_prefix}/
#  {target_prefix}: https://data.humantumoratlas.org/{target_prefix}/
#  caDSR: https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=
#mapping_set_id: https://github.com/ncihtan/htan-model-mappings/mappings/{source_prefix}_to_{target_prefix}/{domain}_values
#mapping_set_description: Value-level mappings for {domain} domain from {source_id} to {target_id}
#license: https://creativecommons.org/publicdomain/zero/1.0/
#mapping_date: {today}
"""

    lines = [header + "\t".join(VALUE_SSSOM_COLUMNS)]

    sorted_matches = sorted(
        matches,
        key=lambda m: (-float(m.get("confidence", 0)), m.get("subject_match_field", ""), m.get("subject_label", "")),
    )

    for match in sorted_matches:
        row = []
        for col in VALUE_SSSOM_COLUMNS:
            val = match.get(col, "")
            if val is None:
                val = ""
            row.append(str(val))
        lines.append("\t".join(row))

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Deterministic value matching within field pairs")
    parser.add_argument("--source", required=True, help="Path to normalized source model JSON")
    parser.add_argument("--target", required=True, help="Path to normalized target model JSON")
    parser.add_argument("--field-sssom", required=True, help="Path to field-level SSSOM TSV")
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--domain", required=True, help="Domain name (clinical, biospecimen, assay)")
    parser.add_argument("--min-confidence", type=float, default=0.7, help="Min field confidence to match values")
    args = parser.parse_args()

    source = json.loads(Path(args.source).read_text())
    target = json.loads(Path(args.target).read_text())
    field_mappings = load_field_sssom(Path(args.field_sssom))

    matched, unmatched_source, unmatched_target = value_match_for_domain(
        source, target, field_mappings, args.min_confidence
    )

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write value-level SSSOM TSV
    tsv_content = matches_to_value_sssom_tsv(
        matched, source["model_id"], target["model_id"], args.domain
    )
    tsv_path = output_dir / f"{args.domain}_values.sssom.tsv"
    tsv_path.write_text(tsv_content)

    # Write JSON intermediaries for downstream use
    (output_dir / f"{args.domain}_matched_values.json").write_text(
        json.dumps(matched, indent=2)
    )
    (output_dir / f"{args.domain}_unmatched_source_values.json").write_text(
        json.dumps(unmatched_source, indent=2)
    )
    (output_dir / f"{args.domain}_unmatched_target_values.json").write_text(
        json.dumps(unmatched_target, indent=2)
    )

    print(f"Value matching complete for {args.domain}:")
    print(f"  Matched values:          {len(matched)}")
    print(f"  Fields with unmatched source values: {len(unmatched_source)}")
    print(f"  Fields with unmatched target values: {len(unmatched_target)}")
    print(f"  SSSOM TSV: {tsv_path}")


if __name__ == "__main__":
    main()
