#!/usr/bin/env python3
"""Prepare semantic value matching prompts and merge agent results.

Reads unmatched source/target value JSONs from deterministic value matching
and produces:
1. Grouped prompts for LLM agents (one per field pair)
2. After agent execution, merges semantic matches back into value SSSOM

Usage:
    # Generate agent prompts
    python semantic_value_match.py prepare \
        --unmatched-source mappings/htan1_to_htan2/clinical_unmatched_source_values.json \
        --unmatched-target mappings/htan1_to_htan2/clinical_unmatched_target_values.json \
        --output /tmp/value_match_prompts/

    # Merge agent results back into SSSOM
    python semantic_value_match.py merge \
        --deterministic mappings/htan1_to_htan2/clinical_matched_values.json \
        --semantic /tmp/value_match_results/ \
        --source-id "ncihtan/data-models@v25.2.1" \
        --target-id "ncihtan/htan2-data-model@v1.3.0" \
        --domain clinical \
        --output mappings/htan1_to_htan2/clinical_values.sssom.tsv
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from value_match import matches_to_value_sssom_tsv


def build_prompt_groups(
    unmatched_source: list[dict],
    unmatched_target: list[dict],
) -> list[dict]:
    """Group unmatched values by field pair for agent dispatch.

    Returns list of groups, each containing:
        field_pair: "SourceClass/SourceField -> TargetClass/TargetField"
        source_values: [str]
        target_values: [str]
        source_field: "Class/Field"
        target_field: "Class/Field"
    """
    # Index unmatched target values by their source field pair
    target_by_source = {}
    for entry in unmatched_target:
        source_field = entry.get("source_field", "")
        target_by_source[source_field] = entry

    groups = []
    seen_pairs = set()

    for entry in unmatched_source:
        source_field = entry["field"]
        target_field = entry["target_field"]
        pair_key = f"{source_field} -> {target_field}"

        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        source_values = entry["values"]
        target_entry = target_by_source.get(target_field, {})
        target_values = target_entry.get("values", [])

        if not source_values and not target_values:
            continue

        groups.append({
            "field_pair": pair_key,
            "source_field": source_field,
            "target_field": target_field,
            "source_values": source_values,
            "target_values": target_values,
        })

    # Also add target-only groups (target fields with unmatched values
    # where the source had no unmatched values)
    for entry in unmatched_target:
        target_field = entry["field"]
        source_field = entry.get("source_field", "")
        pair_key = f"{source_field} -> {target_field}"
        if pair_key not in seen_pairs:
            groups.append({
                "field_pair": pair_key,
                "source_field": source_field,
                "target_field": target_field,
                "source_values": [],
                "target_values": entry["values"],
            })

    return groups


def format_agent_prompt(
    group: dict, source_model_id: str, target_model_id: str,
    all_target_values: list[str] | None = None,
) -> str:
    """Format a prompt for a semantic value matching agent."""
    source_field = group["source_field"]
    target_field = group["target_field"]
    source_values = group["source_values"]
    target_values = group["target_values"]

    # Include full target enum for context when unmatched target list is empty
    target_context = ""
    if all_target_values and not target_values:
        target_context = f"""
**Full target enum** (all permissible values for this field — some already matched deterministically):
{json.dumps(all_target_values, indent=2)}
"""

    prompt = f"""Match values between these two fields from HTAN Phase 1 and Phase 2 data models.

**Source field**: {source_model_id} — `{source_field}`
**Target field**: {target_model_id} — `{target_field}`

These values were NOT matched by deterministic methods (case-insensitive exact, normalized, or containment matching). Your task is to find semantic matches.

**Unmatched source values** (Phase 1):
{json.dumps(source_values, indent=2)}

**Unmatched target values** (Phase 2, not yet matched):
{json.dumps(target_values, indent=2)}
{target_context}

For each match you find, return a JSON object. Consider:
- Value consolidation (e.g., multiple temperature variants → single category)
- Abbreviation expansion (e.g., "G1" → "Grade 1" or "G1 Low Grade")
- Synonym matching (e.g., "Not Applicable" ↔ "Not Available")
- Semantic equivalence (e.g., "Dead" ↔ "Deceased", "Other" in both)
- For numeric-style values like ECOG scores, consider whether "1.0" matches "1"
- If no match exists, omit the value

Return ONLY a JSON array. Each element must have this exact format:
```json
[
  {{
    "source_value": "the Phase 1 value",
    "target_value": "the Phase 2 value",
    "predicate_id": "skos:closeMatch",
    "confidence": 0.8,
    "comment": "brief rationale"
  }}
]
```

Predicate guide:
- `skos:closeMatch` (0.7-0.9): Same concept, different expression
- `skos:narrowMatch` (0.5-0.7): Source value is more specific than target
- `skos:broadMatch` (0.5-0.7): Source value is more general than target
- `skos:relatedMatch` (0.3-0.5): Related but not equivalent

If no matches exist, return an empty array: `[]`"""

    return prompt


def prepare_prompts(
    unmatched_source_path: str,
    unmatched_target_path: str,
    source_model_id: str,
    target_model_id: str,
    output_dir: str,
    target_model_path: str | None = None,
) -> list[dict]:
    """Generate agent prompt files and metadata."""
    unmatched_source = json.loads(Path(unmatched_source_path).read_text())
    unmatched_target = json.loads(Path(unmatched_target_path).read_text())

    # Load full target model for enum context
    target_value_index: dict[str, list[str]] = {}
    if target_model_path:
        target_model = json.loads(Path(target_model_path).read_text())
        for cls in target_model.get("classes", []):
            for field in cls.get("fields", []):
                key = f"{cls['name']}/{field['name']}"
                if field.get("valid_values"):
                    target_value_index[key] = field["valid_values"]

    groups = build_prompt_groups(unmatched_source, unmatched_target)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    manifest = []
    for i, group in enumerate(groups):
        all_target = target_value_index.get(group["target_field"], [])
        prompt = format_agent_prompt(group, source_model_id, target_model_id, all_target)
        prompt_path = out / f"prompt_{i:03d}.txt"
        prompt_path.write_text(prompt)

        meta = {
            "index": i,
            "field_pair": group["field_pair"],
            "source_field": group["source_field"],
            "target_field": group["target_field"],
            "n_source_values": len(group["source_values"]),
            "n_target_values": len(group["target_values"]),
            "prompt_path": str(prompt_path),
        }
        manifest.append(meta)

    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    print(f"Prepared {len(groups)} agent prompts in {output_dir}")
    for m in manifest:
        print(f"  [{m['index']:03d}] {m['field_pair']} "
              f"({m['n_source_values']}s / {m['n_target_values']}t)")

    return manifest


def parse_agent_result(result_text: str) -> list[dict]:
    """Parse JSON array from agent response text.

    Handles both clean JSON and JSON embedded in markdown code blocks.
    """
    text = result_text.strip()

    # Try to extract JSON from markdown code blocks
    if "```" in text:
        import re
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError:
        return []


def merge_results(
    deterministic_path: str,
    semantic_dir: str,
    source_model_id: str,
    target_model_id: str,
    domain: str,
    output_path: str,
):
    """Merge deterministic and semantic value matches into final SSSOM."""
    from deterministic_match import make_field_id
    from value_match import make_value_id

    # Load deterministic matches
    deterministic = json.loads(Path(deterministic_path).read_text())

    # Load manifest and results
    manifest_path = Path(semantic_dir) / "manifest.json"
    if not manifest_path.exists():
        print(f"No manifest found at {manifest_path}, using deterministic only")
        all_matches = deterministic
    else:
        manifest = json.loads(manifest_path.read_text())
        semantic_matches = []

        for entry in manifest:
            result_path = Path(semantic_dir) / f"result_{entry['index']:03d}.json"
            if not result_path.exists():
                continue

            results = json.loads(result_path.read_text())
            if not isinstance(results, list):
                continue

            source_field = entry["source_field"]
            target_field = entry["target_field"]
            source_class, source_fname = source_field.split("/", 1)
            target_class, target_fname = target_field.split("/", 1)

            for match in results:
                source_value = match.get("source_value", "")
                target_value = match.get("target_value", "")
                if not source_value or not target_value:
                    continue

                semantic_matches.append({
                    "subject_id": make_value_id(source_model_id, source_class, source_fname, source_value),
                    "subject_label": source_value,
                    "subject_match_field": make_field_id(source_model_id, source_class, source_fname),
                    "predicate_id": match.get("predicate_id", "skos:closeMatch"),
                    "object_id": make_value_id(target_model_id, target_class, target_fname, target_value),
                    "object_label": target_value,
                    "object_match_field": make_field_id(target_model_id, target_class, target_fname),
                    "mapping_justification": "semapv:LogicalReasoning",
                    "confidence": match.get("confidence", 0.7),
                    "comment": match.get("comment", "Semantic match by LLM agent"),
                })

        print(f"Semantic matches: {len(semantic_matches)}")
        all_matches = deterministic + semantic_matches

    # Generate SSSOM
    tsv_content = matches_to_value_sssom_tsv(all_matches, source_model_id, target_model_id, domain)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tsv_content)

    # Also write merged JSON
    merged_json_path = out.parent / f"{domain}_matched_values.json"
    merged_json_path.write_text(json.dumps(all_matches, indent=2))

    print(f"Merged {len(all_matches)} total value matches -> {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Semantic value matching preparation and merge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # prepare subcommand
    prep = subparsers.add_parser("prepare", help="Generate agent prompts")
    prep.add_argument("--unmatched-source", required=True)
    prep.add_argument("--unmatched-target", required=True)
    prep.add_argument("--source-id", default="ncihtan/data-models@v25.2.1")
    prep.add_argument("--target-id", default="ncihtan/htan2-data-model@v1.3.0")
    prep.add_argument("--target-model", help="Path to normalized target model JSON (for full enum context)")
    prep.add_argument("--output", required=True)

    # merge subcommand
    mrg = subparsers.add_parser("merge", help="Merge deterministic + semantic results")
    mrg.add_argument("--deterministic", required=True)
    mrg.add_argument("--semantic", required=True)
    mrg.add_argument("--source-id", default="ncihtan/data-models@v25.2.1")
    mrg.add_argument("--target-id", default="ncihtan/htan2-data-model@v1.3.0")
    mrg.add_argument("--domain", required=True)
    mrg.add_argument("--output", required=True)

    args = parser.parse_args()

    if args.command == "prepare":
        prepare_prompts(
            args.unmatched_source, args.unmatched_target,
            args.source_id, args.target_id, args.output,
            getattr(args, "target_model", None),
        )
    elif args.command == "merge":
        merge_results(
            args.deterministic, args.semantic,
            args.source_id, args.target_id, args.domain, args.output,
        )


if __name__ == "__main__":
    main()
