# HTAN Model Mappings

This repository generates and stores SSSOM (Simple Standard for Sharing Ontological Mappings) between biomedical data models, starting with HTAN Phase 1 → Phase 2.

## Project Structure

```
mappings/           # Generated SSSOM TSV files organized by mapping pair
scripts/            # Python utilities for matching and validation
.claude/skills/     # Claude Code skill definitions
```

## Data Model Formats

### Schematic CSV (HTAN Phase 1)
- Repository: `ncihtan/data-models`
- Main file: `HTAN.model.csv`
- Columns: `Attribute, Description, Valid Values, DependsOn, Properties, Required, Parent, DependsOn Component, Source, Validation Rules`
- `Parent` column indicates the component (Demographics, Diagnosis, etc.)
- caDSR IDs found in `Source` column URLs: `CDEDD.ITEM_ID=2192217`
- Field names in Title Case: `Ethnicity`, `Primary Diagnosis`, `Age at Diagnosis`
- Valid values are comma-separated strings

### LinkML (HTAN Phase 2)
- Repository: `ncihtan/htan2-data-model`
- Schema files: `modules/*/domains/*.yaml` (one per domain)
- Enum files: `modules/*/enums/*.yaml`
- `slot_uri: caDSR:2192217` on attributes for caDSR references
- Field names in UPPER_SNAKE_CASE: `ETHNIC_GROUP`, `PRIMARY_DIAGNOSIS`
- Enums as LinkML `permissible_values` with descriptions

### GDC JSON Schema
- JSON files with `properties:`, `enum:`, `$ref`
- Used by GDC/TCGA models

## SSSOM Format Reference

### Required TSV Columns
- `subject_id`: Source field identifier (CURIE)
- `subject_label`: Human-readable source field name
- `predicate_id`: SKOS mapping predicate
- `object_id`: Target field identifier (CURIE)
- `object_label`: Human-readable target field name
- `mapping_justification`: How the mapping was determined (SEMAPV term)
- `confidence`: Float 0.0-1.0
- `comment`: Rationale for the mapping

### Predicate Selection Guide
| Scenario | Predicate | Confidence |
|----------|-----------|------------|
| Same caDSR ID | `skos:exactMatch` | 1.0 |
| Exact normalized name match | `skos:exactMatch` | 0.9 |
| Same concept, different name (e.g., Ethnicity ↔ ETHNIC_GROUP) | `skos:closeMatch` | 0.7-0.9 |
| Source is more specific than target | `skos:narrowMatch` | 0.5-0.7 |
| Source is more general than target | `skos:broadMatch` | 0.5-0.7 |
| Related but different aspects | `skos:relatedMatch` | 0.3-0.5 |

### Mapping Justification Values
- `semapv:DatabaseCrossReference` — caDSR ID match
- `semapv:LexicalMatching` — Name/label string matching
- `semapv:LogicalReasoning` — Semantic reasoning
- `semapv:MappingReview` — Human or QA agent review

## Known caDSR Anchors (HTAN1 ↔ HTAN2)
These are confirmed shared identifiers between models:
- Ethnicity / ETHNIC_GROUP → caDSR:2192217
- Race / RACE → caDSR:2192199
- Gender / GENDER → caDSR:2200604

## Normalized Model JSON Schema

All models are normalized to this common format before matching:

```json
{
  "model_id": "owner/repo@tag",
  "format": "schematic-csv | linkml | json-schema",
  "classes": [
    {
      "name": "ComponentName",
      "fields": [
        {
          "name": "OriginalFieldName",
          "normalized_name": "lowercase_underscore_name",
          "description": "Field description text",
          "cadsr_id": "2192217",
          "source_uri": "https://...",
          "valid_values": ["value1", "value2"],
          "required": true
        }
      ]
    }
  ]
}
```

## Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Run validation on existing mappings
python scripts/validate_mappings.py mappings/htan1_to_htan2/

# Run deterministic matching
python scripts/deterministic_match.py --source source.json --target target.json --output matches/
```
