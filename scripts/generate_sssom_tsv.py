#!/usr/bin/env python3
"""Generate SSSOM TSV files from matching results.

Takes matched_fields.json (from deterministic + semantic matching) and
produces properly formatted SSSOM TSV with YAML metadata header.

Usage:
    python generate_sssom_tsv.py \
        --matches matches/matched_fields.json \
        --source-id "ncihtan/data-models@v25.2.1" \
        --target-id "ncihtan/htan2-data-model@v1.3.0" \
        --output mappings/htan1_to_htan2/fields.sssom.tsv
"""

import argparse
import json
from datetime import date
from pathlib import Path


SSSOM_COLUMNS = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "mapping_justification",
    "confidence",
    "comment",
]


def generate_metadata_header(
    source_id: str, target_id: str, mapping_type: str = "fields"
) -> str:
    """Generate SSSOM YAML metadata header."""
    today = date.today().isoformat()

    # Derive short prefixes from model IDs
    source_prefix = source_id.split("/")[-1].split("@")[0].replace("-", "_")
    target_prefix = target_id.split("/")[-1].split("@")[0].replace("-", "_")

    return f"""#curie_map:
#  skos: http://www.w3.org/2004/02/skos/core#
#  semapv: https://w3id.org/semapv/vocab/
#  {source_prefix}: https://data.humantumoratlas.org/{source_prefix}/
#  {target_prefix}: https://data.humantumoratlas.org/{target_prefix}/
#  caDSR: https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=
#mapping_set_id: https://github.com/ncihtan/htan-model-mappings/mappings/{source_prefix}_to_{target_prefix}/{mapping_type}
#mapping_set_description: {mapping_type.capitalize()}-level mappings from {source_id} to {target_id}
#license: https://creativecommons.org/publicdomain/zero/1.0/
#mapping_date: {today}
"""


def matches_to_sssom_tsv(
    matches: list[dict], source_id: str, target_id: str, mapping_type: str = "fields"
) -> str:
    """Convert a list of match dicts to SSSOM TSV string."""
    header = generate_metadata_header(source_id, target_id, mapping_type)

    # TSV header
    lines = [header + "\t".join(SSSOM_COLUMNS)]

    # Sort by confidence descending, then by subject_label
    sorted_matches = sorted(
        matches, key=lambda m: (-float(m.get("confidence", 0)), m.get("subject_label", ""))
    )

    for match in sorted_matches:
        row = []
        for col in SSSOM_COLUMNS:
            val = match.get(col, "")
            if val is None:
                val = ""
            row.append(str(val))
        lines.append("\t".join(row))

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate SSSOM TSV from match results")
    parser.add_argument("--matches", required=True, help="Path to matched_fields.json")
    parser.add_argument("--source-id", required=True, help="Source model ID")
    parser.add_argument("--target-id", required=True, help="Target model ID")
    parser.add_argument("--mapping-type", default="fields", help="Mapping type (fields, values, classes)")
    parser.add_argument("--output", required=True, help="Output SSSOM TSV file path")
    args = parser.parse_args()

    matches = json.loads(Path(args.matches).read_text())
    tsv_content = matches_to_sssom_tsv(matches, args.source_id, args.target_id, args.mapping_type)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tsv_content)

    print(f"Wrote {len(matches)} mappings to {args.output}")


if __name__ == "__main__":
    main()
