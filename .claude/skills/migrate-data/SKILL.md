---
name: migrate-data
description: Orchestrate HTAN Phase 1 to Phase 2 data migration
user-invocable: true
---

# /migrate-data

Migrate HTAN Phase 1 tabular data to Phase 2 format using config-driven transforms.

## Usage

```
/migrate-data --input <file.tsv> --source-class <ClassName> --domain <domain> [--validate] [--report <path>]
```

### Arguments

- `--input` (required): Path to HTAN1 TSV data file
- `--source-class` (required): Source class name (e.g., `Demographics`, `Diagnosis`, `Biospecimen`)
- `--domain` (required): Domain name (`clinical`, `biospecimen`, `assay`)
- `--validate`: Run LinkML validation on output (optional)
- `--report`: Path to write JSON migration report (optional)
- `--output`: Output path (default: `<input>_htan2.tsv`)

### Examples

```
/migrate-data --input data/htan1_demographics.tsv --source-class Demographics --domain clinical
/migrate-data --input data/htan1_biospecimen.tsv --source-class Biospecimen --domain biospecimen --validate
```

## Behavior

This skill orchestrates the full migration pipeline:

### 1. Pre-flight Checks

Before running migration, read all scripts to understand the available tooling:
- `scripts/value_match.py` — Deterministic value matching
- `scripts/semantic_value_match.py` — Semantic value matching with LLM agents
- `scripts/build_lookup_tables.py` — UBERON/NCI-T lookup extraction
- `scripts/migrate.py` — Main migration engine
- `scripts/validate_transformed.py` — LinkML validation

Then verify prerequisites:
- Check that the transform config exists at `configs/htan1_to_htan2/<domain>.transform.yaml`
- Check that field-level SSSOM exists at `mappings/htan1_to_htan2/<domain>_fields.sssom.tsv`

### 2. Deterministic Value Matching (if value SSSOM missing)

If `mappings/htan1_to_htan2/<domain>_values.sssom.tsv` does not exist:

1. Check for normalized model JSONs in `/tmp/htan1_<domain>.json` and `/tmp/htan2_<domain>.json`
2. If they don't exist, inform the user they need to run `/map-models` first to generate the normalized models
3. Run deterministic value matching:
   ```
   uv run python scripts/value_match.py \
     --source /tmp/htan1_<domain>.json \
     --target /tmp/htan2_<domain>.json \
     --field-sssom mappings/htan1_to_htan2/<domain>_fields.sssom.tsv \
     --output mappings/htan1_to_htan2/ \
     --domain <domain>
   ```
4. Report value match statistics

### 3. Semantic Value Matching (Parallel Haiku Agents)

After deterministic matching, check for remaining unmatched values in
`mappings/htan1_to_htan2/<domain>_unmatched_source_values.json` and
`mappings/htan1_to_htan2/<domain>_unmatched_target_values.json`.

If unmatched values exist:

1. **Prepare agent prompts**:
   ```
   uv run python scripts/semantic_value_match.py prepare \
     --unmatched-source mappings/htan1_to_htan2/<domain>_unmatched_source_values.json \
     --unmatched-target mappings/htan1_to_htan2/<domain>_unmatched_target_values.json \
     --output /tmp/value_match_prompts_<domain>/
   ```

2. **Read the manifest** at `/tmp/value_match_prompts_<domain>/manifest.json` to get the list of field pair groups.

3. **Launch parallel Haiku agents**, batching small groups together. Each agent receives:
   - The prompt text from the prompt file
   - Instructions to return ONLY a JSON array of match objects

   Group prompts into batches of 3-5 field pairs per agent for efficiency. Each agent prompt should include all field pairs in its batch, clearly separated.

   **Agent prompt template** (per batch):
   ```
   You are matching values between HTAN Phase 1 and Phase 2 data models.
   For each field pair below, find semantic matches among the unmatched values.

   [Include the prompt text from each prompt file in the batch]

   Return a single JSON object with field pair keys mapping to arrays of matches:
   {
     "SourceClass/SourceField -> TargetClass/TargetField": [
       {
         "source_value": "the Phase 1 value",
         "target_value": "the Phase 2 value",
         "predicate_id": "skos:closeMatch",
         "confidence": 0.8,
         "comment": "brief rationale"
       }
     ],
     ...
   }
   ```

4. **Parse agent results** and write each field pair's matches to `/tmp/value_match_prompts_<domain>/result_NNN.json`.

5. **Merge results**:
   ```
   uv run python scripts/semantic_value_match.py merge \
     --deterministic mappings/htan1_to_htan2/<domain>_matched_values.json \
     --semantic /tmp/value_match_prompts_<domain>/ \
     --domain <domain> \
     --output mappings/htan1_to_htan2/<domain>_values.sssom.tsv
   ```

### 4. Lookup Tables (if missing)

If the transform config references lookup tables that don't exist in `lookups/`:

1. Check for HTAN2 enum YAML files in `/tmp/htan2_enums/`
2. If they don't exist, fetch them from GitHub:
   ```
   mkdir -p /tmp/htan2_enums
   # List files:
   gh api 'repos/ncihtan/htan2-data-model/git/trees/main?recursive=1' \
     --jq '.tree[] | select(.path | test("yaml$")) | .path' | grep -iE "(uberon|ncit)"
   # Download each:
   curl -sL "https://raw.githubusercontent.com/ncihtan/htan2-data-model/main/<path>" -o /tmp/htan2_enums/<basename>
   ```
3. Build lookup tables:
   ```
   uv run python scripts/build_lookup_tables.py \
     --enum-dir /tmp/htan2_enums/ \
     --output lookups/
   ```

### 5. ICD-O → NCI Thesaurus Crosswalk (if needed)

The `Primary Diagnosis` field uses ICD-O morphology text (e.g., "Adenocarcinoma NOS") but HTAN2 requires NCI Thesaurus codes. Use the EBI OLS4 API via `scripts/ols_lookup.py` to build an authoritative crosswalk.

**IMPORTANT**: Do NOT use the HTAN2 enum YAML descriptions to resolve ICD-O terms — those descriptions are unreliable. Always use OLS for code resolution.

1. **Extract unique Primary Diagnosis values** from the input data to a text file (one per line)

2. **Build crosswalk via OLS**:
   ```
   uv run python scripts/ols_lookup.py crosswalk \
     --terms-file /tmp/icdo_terms.txt \
     --ontology ncit \
     --output /tmp/icdo_to_ncit_crosswalk_ols.json \
     --delay 0.3
   ```

3. **Review and fix** problematic matches — OLS free-text search can fail on multi-word terms.
   For any matches with confidence < 0.95, verify with exact search:
   ```
   uv run python scripts/ols_lookup.py search --ontology ncit --query "Infiltrating Ductal Carcinoma" --exact
   ```

4. **Merge verified crosswalk** into the NCI-T lookup:
   ```python
   # Add OLS-verified ICD-O entries to lookups/ncit_diagnosis_to_codes.json
   for term, entry in crosswalk.items():
       if entry["code"]:
           ncit_lookup[term] = entry["code"]
   ```

5. The migration engine's `text_to_ontology` conversion (with NOS-stripping) will use the merged lookup

### OLS Lookup Script (`scripts/ols_lookup.py`)

Utility for EBI OLS4 API (free, no auth):
- `resolve` — Look up a code's preferred label (e.g., `C2852` → "Adenocarcinoma")
- `search` — Find codes for a text term (supports `--exact`)
- `crosswalk` — Batch build ICD-O → NCIt mappings from a terms file
- `verify` — Check that crosswalk codes resolve to expected labels

### 6. Run Migration

```
uv run python scripts/migrate.py \
  --input <input_file> \
  --config configs/htan1_to_htan2/<domain>.transform.yaml \
  --source-class <source_class> \
  --output <output_file> \
  [--validate] \
  [--report <report_path>]
```

If the source class has cross-class dependencies (e.g., Diagnosis needs Demographics for birth date), provide context:
```
--context "Demographics:/path/to/demographics.tsv"
```

### 7. Validation (if --validate)

If the `--validate` flag was provided and a LinkML schema is available:

```
uv run python scripts/validate_transformed.py \
  --input <output_file> \
  --target-class <target_class> \
  --schema /tmp/htan2_schema.yaml \
  --report <report_path>
```

### 8. Report Results

Report to the user:
- Rows processed / succeeded
- Field coverage (mapped vs unmapped source fields)
- Value transform statistics (deterministic + semantic match counts)
- Ontology resolution statistics (UBERON hits, NCI-T hits, unresolved)
- Validation results (if applicable)
- Warnings (unmapped values, failed conversions)
- Path to output file and report

## Transform Pipeline

The migration engine applies five tiers of transformation:

1. **Field renaming** — Rename columns per field-level SSSOM at confidence >= `min_confidence`
2. **Value remapping** — Remap cell values per value-level SSSOM lookups (deterministic + semantic)
3. **Conversions** — Apply explicit rules: `age_days_auto`, `text_to_ontology` (with NOS-stripping), `days_from_index_to_age`
4. **Structural** — Handle field splits (1 source → N target columns) and class relocations
5. **Defaults** — Fill required target fields not populated by tiers 1-4

## Config Files

Transform configs at `configs/htan1_to_htan2/<domain>.transform.yaml` specify:
- Which SSSOM files to use (field-level and value-level)
- Confidence threshold for auto-migration
- Explicit conversion rules (unit transforms, ontology lookups)
- Structural transforms (field splits, class relocations)
- Defaults for new required fields
