---
name: map-models
description: Generate SSSOM mappings between two biomedical data models
user-invocable: true
---

# /map-models

Generate SSSOM (Simple Standard for Sharing Ontological Mappings) between two
data models hosted on GitHub.

## Usage

```
/map-models --source <owner/repo@tag> --target <owner/repo@tag> [--domain <domain>] [--output <dir>]
```

### Arguments

- `--source` (required): Source model repository in `owner/repo@tag` format
- `--target` (required): Target model repository in `owner/repo@tag` format
- `--domain` (optional): Filter to a specific domain (e.g., `clinical`, `biospecimen`, `assay`). Default: all domains.
- `--output` (optional): Output directory for SSSOM files. Default: `mappings/<source>_to_<target>/`

### Examples

```
/map-models --source ncihtan/data-models@v25.2.1 --target ncihtan/htan2-data-model@v1.3.0 --domain clinical
/map-models --source ncihtan/data-models@v25.2.1 --target ncihtan/htan2-data-model@v1.3.0 --domain biospecimen --output mappings/htan1_to_htan2_biospecimen/
```

## Behavior

This skill orchestrates a multi-agent pipeline to produce SSSOM mappings:

### 1. Parse Arguments

Extract source repo/tag, target repo/tag, domain filter, and output directory from the command arguments.

### 2. Read Existing Scripts

Before launching agents, read all scripts in `scripts/` to understand the available tooling:
- `scripts/normalize_model.py` — Normalizes models to common JSON format
- `scripts/deterministic_match.py` — caDSR ID and normalized name matching
- `scripts/generate_sssom_tsv.py` — Converts match JSON to SSSOM TSV
- `scripts/validate_mappings.py` — Validates SSSOM output files

### 3. Model Extraction (Parallel Sonnet Agents)

Launch two agents in parallel — one per model — to:
- Fetch model files from GitHub using `gh api` for tree listing and `curl -sL` with raw GitHub URLs for file content
- Auto-detect the model format:
  - **Schematic CSV**: Look for `*.model.csv` files with columns `Attribute, Description, Valid Values, DependsOn, Properties, Required, Parent, Source`
  - **LinkML**: Look for `*.yaml` files with `classes:` and `slots:` keys
  - **JSON Schema**: Look for `*.json` files with `properties:` and `$ref` keys
- Parse and normalize each model using `uv run python scripts/normalize_model.py`
- If a domain filter is specified, filter the normalized JSON to only include classes in that domain
- Write normalized JSON to `/tmp/` for downstream steps

**Important notes for extraction agents:**
- For LinkML repos with multiple YAML files (e.g., one per domain, separate enum files), download ALL relevant files to a temp directory and run normalize_model.py with `--path <directory>` — the script handles merging
- Some YAML files may have malformed content (unquoted multi-line strings, etc.) — `yaml.safe_load` will fail on these. Log a warning and skip them rather than failing the entire extraction
- When domain-filtering, be inclusive of what constitutes a domain. For "clinical": Demographics, Diagnosis, Exposure, Family History, Follow-up, Molecular Test, Therapy, Vital Status, Patient, plus any container/structural classes
- Each agent should write to `/tmp/` only — never modify project files

Each extraction agent should return: the normalized JSON path and a summary of what was found (number of classes, fields, format detected, caDSR IDs found).

### 4. Deterministic Matching Pass (Python Script)

Run `uv run python scripts/deterministic_match.py` with both normalized models as input. This script:
- Matches fields by **caDSR ID** (exact match → `skos:exactMatch`, confidence 1.0)
- Matches fields by **exact normalized name** (lowercase, stripped → `skos:exactMatch`, confidence 0.9)
- Outputs: `matched_fields.json` (confirmed matches), `unmatched_source.json`, and `unmatched_target.json`

### 5. Semantic Matching (Parallel Haiku Agents)

Group unmatched **target** fields by domain area (e.g., Demographics/Diagnosis, Exposure/FamilyHistory/VitalStatus, FollowUp/MolecularTest/Therapy) and launch one Haiku agent per group. This is more efficient than one agent per field.

Each agent receives:
- Its batch of unmatched target fields with full metadata (name, description, valid values, caDSR ID)
- All relevant unmatched source fields from the same or related classes, with full metadata
- Instructions to return a JSON array of match objects

**Agent prompt must specify the exact JSON return format:**
```json
{
  "target_field_id": "prefix:Class/FIELD_NAME",
  "target_label": "FIELD_NAME",
  "source_field_id": "prefix:Class/Field Name",  // null if no match
  "source_label": "Field Name",
  "source_class": "ClassName",
  "predicate_id": "skos:closeMatch",
  "confidence": 0.8,
  "comment": "rationale"
}
```

Each agent should consider:
- Field descriptions and their semantic similarity
- Valid value overlap (do the enums represent the same concept?)
- Naming patterns (e.g., `Days to Birth` ↔ `AGE_IN_DAYS` — same concept, different expression)
- Unit/encoding differences (years vs days, text terms vs ontology codes like UBERON)
- Cross-class mappings (fields may have moved between classes across model versions)
- Return "no match" (source fields as null, confidence 0) if no reasonable mapping exists

### 6. Merge Matches

Write a Python script (inline or temp file) to:
- Combine deterministic matches with semantic matches into a single list
- Convert semantic match format to SSSOM format (swap subject/object so source is always subject)
- Filter out no-match entries (null source)
- Track which target fields had no match and which source fields had no match
- Write combined matches to `/tmp/.../all_matches.json`

### 7. Quality Review (Sonnet Agent)

Launch a single Sonnet review agent that reads the combined matches file and:
- Flags **duplicate mappings** (multiple source fields mapping to the same target, or vice versa)
- Flags **conflicting predicates** (same pair with different predicates from different stages)
- Reviews **cross-class mappings**: Fields that moved between classes should typically be `skos:closeMatch`, not `skos:exactMatch`, even if names match exactly
- Reviews **container/structural references**: These map at different structural levels (e.g., singular vs plural naming, component ref vs list slot) — should be `skos:closeMatch` at ~0.8
- Reviews **1-to-many splits**: When one source field maps to multiple target fields (e.g., Gender → GENDER_IDENTITY + SEX), ensure predicates and confidence reflect the split
- Adjusts confidence scores based on full-context review
- Updates `mapping_justification` to `semapv:MappingReview` for any modified matches
- Writes final cleaned matches to `/tmp/.../final_matches.json`
- Writes a review report to `/tmp/.../review_report.txt`

### 8. Generate SSSOM TSV Files

Run `uv run python scripts/generate_sssom_tsv.py` to produce the matched mappings file.

Then generate a **second SSSOM file for unmapped source fields** using `skos:noMappingFound` as the predicate. This file documents source fields with no target equivalent. Categorize the reason in the `comment` column (e.g., "Cancer-type-specific field; target model does not include disease-specific tiers", "No equivalent field in target model").

### 9. Validate & Report

- Run `uv run python scripts/validate_mappings.py` on the output directory
- Report summary statistics to the user:
  - Total fields in source / target
  - Matched (exact + semantic) with predicate breakdown
  - Unmatched source fields (with category breakdown)
  - Unmatched target fields (new in target)
  - Confidence distribution (avg, min, max)

## Output Files

Two SSSOM TSV files are produced per mapping run:

1. **`<domain>_fields.sssom.tsv`** — Matched source→target mappings
2. **`<domain>_unmapped_source.sssom.tsv`** — Source fields with no target equivalent

Each file has a YAML metadata header and TSV body:

```
#curie_map:
#  skos: http://www.w3.org/2004/02/skos/core#
#  semapv: https://w3id.org/semapv/vocab/
#  <source_prefix>: https://data.humantumoratlas.org/<source_prefix>/
#  <target_prefix>: https://data.humantumoratlas.org/<target_prefix>/
#  caDSR: https://cadsr.cancer.gov/onedata/dmdirect/NIH/NCI/CO/CDEDD?filter=CDEDD.ITEM_ID=
#mapping_set_id: https://github.com/ncihtan/htan-model-mappings/mappings/<source>_to_<target>/<type>
#mapping_set_description: <description>
#license: https://creativecommons.org/publicdomain/zero/1.0/
#mapping_date: <today>
subject_id	subject_label	predicate_id	object_id	object_label	mapping_justification	confidence	comment
```

### Predicates

- `skos:exactMatch` — Same concept, same semantics (caDSR ID match or identical meaning)
- `skos:closeMatch` — Same concept, slightly different scope, naming, or structural placement
- `skos:narrowMatch` — Source field is narrower than target
- `skos:broadMatch` — Source field is broader than target
- `skos:relatedMatch` — Related but not directly equivalent
- `skos:noMappingFound` — No equivalent in the target model (used in unmapped source file)

### Mapping Justification Values

- `semapv:DatabaseCrossReference` — caDSR ID match
- `semapv:LexicalMatching` — Name/label string matching
- `semapv:LogicalReasoning` — Semantic reasoning by agent
- `semapv:MappingReview` — Reviewed/modified by QA agent

### Confidence Guidelines

| Scenario | Predicate | Confidence |
|----------|-----------|------------|
| Same caDSR ID | `skos:exactMatch` | 1.0 |
| Exact normalized name, same class | `skos:exactMatch` | 0.9 |
| Exact normalized name, different class | `skos:closeMatch` | 0.75 |
| Same concept, different encoding (text vs ontology code, years vs days) | `skos:closeMatch` | 0.8-0.9 |
| Structural/container references across levels | `skos:closeMatch` | 0.8 |
| 1-to-many field split (primary mapping) | `skos:closeMatch` | 0.8 |
| 1-to-many field split (secondary mapping) | `skos:broadMatch` | 0.6 |
| Partial concept overlap | `skos:narrowMatch` or `skos:broadMatch` | 0.5-0.7 |
