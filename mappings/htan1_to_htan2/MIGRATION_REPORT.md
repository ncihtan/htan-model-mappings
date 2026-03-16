# HTAN Phase 1 to Phase 2 Clinical Data Migration Report

**Date**: 2026-03-16
**Source**: HTAN Phase 1 BigQuery (`isb-cgc-bq.HTAN`, Release 7.0, Nov 2025)
**Target schema**: `ncihtan/htan2-data-model@v1.3.0` (JSON Schema)
**Validation**: HTAN2 JSON Schemas, ignoring HTAN1 participant ID patterns

## Summary

| Output Table | Rows | Columns | Validation |
|---|---|---|---|
| `htan1_Demographics.tsv` | 2,805 | 5 | **100%** |
| `htan1_VitalStatus.tsv` | 2,805 | 5 | **100%** |
| `htan1_Diagnosis.tsv` | 2,300 | 16 | **100%** |
| `htan1_FollowUp.tsv` | 2,167 | 10 | **100%** |
| **Total** | **10,077** | | **100%** |

All output values are valid against the HTAN2 JSON Schema enums, types, and required field constraints. Four required fields with no sentinel value in the schema are excluded from validation (see [Schema Issues](#schema-issues-filed)).

## Source Data

Three BigQuery tables, `SELECT *`:

| Source Table | Rows | Columns |
|---|---|---|
| `clinical_tier1_demographics_current` | 2,805 | 23 |
| `clinical_tier1_diagnosis_current` | 2,300 | 93 |
| `clinical_tier1_followup_current` | 2,167 | 61 |

## Transform Pipeline

The migration engine (`scripts/migrate.py`) applies a five-tier config-driven pipeline:

### Tier 1: Field Renaming
Field-level SSSOM mappings (309 across all domains, 68 clinical) rename Phase 1 columns to Phase 2 names. Examples:

| Phase 1 | Phase 2 | Method |
|---|---|---|
| `Ethnicity` | `ETHNIC_GROUP` | caDSR:2192217 match |
| `Race` | `RACE` | caDSR:2192199 match |
| `Tumor Grade` | `TUMOR_GRADE` | Normalized name match |
| `Disease Response` | `DISEASE_RESPONSE` | Normalized name match |

### Tier 2: Value Remapping
356 clinical value-level SSSOM mappings (285 deterministic + 71 LLM-assisted) remap enum values. Examples:

| Phase 1 Value | Phase 2 Value | Method |
|---|---|---|
| `not hispanic or latino` | `Not Hispanic or Latino` | Case-insensitive match |
| `Current Reformed Smoker` | `Former Smoker` | Semantic (Haiku agent) |
| `Low Grade` | `G1 Low Grade` | Semantic (Haiku agent) |
| `"0.0"` (ECOG) | `0` | Semantic (Haiku agent) |

### Tier 3: Conversions

**Age/time fields**: `age_days_auto` conversion detects whether source values are already in days (>200) or need year-to-day conversion. Phase 1 BQ data is already in days.

**Ontology code resolution**: Text terms converted to ontology codes via lookup tables built from HTAN2 enum YAMLs and verified against the EBI OLS4 API.

| Phase 1 | Phase 2 | Lookup |
|---|---|---|
| `Colon NOS` | `UBERON:0001155` | UBERON (22,551 entries + 73 OLS-verified tissue terms) |
| `Adenocarcinoma NOS` | `C2852` | NCIt (20,136 entries + 59 OLS-verified ICD-O terms) |
| `Breast NOS` | `UBERON:0000310` | UBERON |
| `Glioblastoma` | `C3058` | NCIt |

ICD-O morphology NOS suffixes are automatically stripped before lookup (`Adenocarcinoma NOS` -> search for `adenocarcinoma`).

**Resolution rates** (for rows with actual diagnoses, excluding "Not Reported"/"unknown"):
- NCIt diagnosis codes: 1,987/1,987 (100%)
- UBERON tissue codes: 2,104/2,104 (100%)

### Tier 4: Structural Transforms

**Field split**: Phase 1 `Gender` (conflated concept) split into Phase 2 `GENDER_IDENTITY` + `SEX` with value mappings applied to both.

**Class relocations**: Fields that moved between classes in the model redesign:

| Phase 1 Location | Phase 2 Location | Rows |
|---|---|---|
| Demographics / `Vital Status` | VitalStatus / `VITAL_STATUS` | 2,805 |
| Demographics / `Cause of Death` | VitalStatus / `CAUSE_OF_DEATH` | 2,805 |
| Demographics / `Cause of Death Source` | VitalStatus / `CAUSE_OF_DEATH_SOURCE` | 2,805 |
| Diagnosis / `Progression or Recurrence` | FollowUp / `PROGRESSION_OR_RECURRENCE` | 2,300 |
| Diagnosis / `Progression or Recurrence Type` | FollowUp / `PROGRESSION_OR_RECURRENCE_TYPE` | 2,300 |

Relocated fields are written to separate output files named by their HTAN2 target class, with `HTAN_PARTICIPANT_ID` carried through for joins.

### Tier 5: Defaults and Sentinels

Required fields with no source data filled with appropriate sentinels:

| Sentinel | Fields | Spec reference |
|---|---|---|
| `Not Reported` | CLINICAL_T/N/M_STAGE, METHOD_OF_DIAGNOSIS, TUMOR_CLASSIFICATION_CATEGORY, TUMOR_GRADE, LAST_KNOWN_DISEASE_STATUS, DISEASE_RESPONSE, MENOPAUSE_STATUS, PROGRESSION_OR_RECURRENCE | HTAN2 enum includes "Not Reported" |
| `Unknown` | METASTASIS_AT_DIAGNOSIS | HTAN2 enum includes "Unknown" |
| `Not reported` | VITAL_STATUS | HTAN2 enum uses lowercase "reported" |
| `-1` | All AGE_IN_DAYS_* fields | caDSR spec: "Use -1 if not available" |

### Value Corrections

Post-transform fixes for values not covered by SSSOM or from relocated fields:

| Category | Examples |
|---|---|
| Casing | `unknown` -> `Unknown`, `no` -> `No`, `Not Reported` -> `Not reported` (VitalStatus) |
| Consolidation | `Yes - Progression or Recurrence` -> `Yes` |
| Abbreviation expansion | `PD-Progressive Disease` -> `Progressive Disease`, `CR-Complete Response` -> `Complete Response` |
| Synonym | `Surgical Complications` -> `Surgical Complication`, `Autopsy` -> `Autopsy Report` |
| Numeric format | `0.0` -> `0` (ECOG), `1.0` -> `1` |
| Missing sentinel | `Other` (Race) -> `Unknown`, text in integer fields -> `-1` |
| Out-of-enum ontology | `UBERON:8480060` (paraspinal, not in enum) -> `UBERON:0001130` (vertebral column) |

## Output Schema

### htan1_Demographics.tsv (2,805 rows)
| Column | Description |
|---|---|
| `HTAN_PARTICIPANT_ID` | Participant identifier (join key) |
| `ETHNIC_GROUP` | Ethnicity (5 enum values) |
| `GENDER_IDENTITY` | Gender identity (5 enum values) |
| `RACE` | Race (8 enum values) |
| `SEX` | Biological sex (5 enum values) |

### htan1_VitalStatus.tsv (2,805 rows)
| Column | Description |
|---|---|
| `HTAN_PARTICIPANT_ID` | Participant identifier (join key) |
| `AGE_IN_DAYS_AT_LAST_KNOWN_SURVIVAL_STATUS` | Age at last known status (-1 if unavailable) |
| `CAUSE_OF_DEATH` | Cause of death (86 enum values) |
| `CAUSE_OF_DEATH_SOURCE` | Source of death information (7 enum values) |
| `VITAL_STATUS` | Alive/Dead/Not reported/Unknown/Unspecified |

### htan1_Diagnosis.tsv (2,300 rows)
| Column | Description |
|---|---|
| `HTAN_PARTICIPANT_ID` | Participant identifier (join key) |
| `AGE_IN_DAYS_AT_DIAGNOSIS` | Age at diagnosis in days (-1 if unavailable) |
| `AGE_IN_DAYS_AT_LAST_KNOWN_DISEASE_STATUS` | Age at last status in days (-1 if unavailable) |
| `AJCC_STAGING_SYSTEM_EDITION` | AJCC edition (1st-8th, empty if not staged) |
| `CLINICAL_M_STAGE` | Metastasis stage |
| `CLINICAL_N_STAGE` | Node stage |
| `CLINICAL_T_STAGE` | Tumor stage |
| `LAST_KNOWN_DISEASE_STATUS` | Last known disease status |
| `METASTASIS_AT_DIAGNOSIS` | Metastasis at diagnosis |
| `METHOD_OF_DIAGNOSIS` | Diagnostic method |
| `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID` | NCIt diagnosis code (e.g., C2852) |
| `TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE` | UBERON tissue code (e.g., UBERON:0001155) |
| `TUMOR_CLASSIFICATION_CATEGORY` | Tumor classification |
| `TUMOR_GRADE` | Tumor grade |

### htan1_FollowUp.tsv (2,167 rows)
| Column | Description |
|---|---|
| `HTAN_PARTICIPANT_ID` | Participant identifier (join key) |
| `AGE_IN_DAYS_AT_FOLLOWUP` | Age at follow-up in days (-1 if unavailable) |
| `AGE_IN_DAYS_AT_PROGRESSION_OR_RECURRENCE` | Age at progression in days (-1 if unavailable) |
| `DISEASE_RESPONSE` | Treatment response |
| `ECOG_PERFORMANCE_STATUS` | ECOG score (0-5, empty if not assessed) |
| `EVIDENCE_OF_RECURRENCE_TYPE` | Type of recurrence evidence |
| `MENOPAUSE_STATUS` | Menopause status |
| `PROGRESSION_OR_RECURRENCE` | Whether progression/recurrence occurred |
| `PROGRESSION_OR_RECURRENCE_ANATOMIC_SITE_UBERON_CODE` | UBERON code for recurrence site |
| `PROGRESSION_OR_RECURRENCE_TYPE` | Type of progression/recurrence |

## Schema Issues Filed

Four required fields in the HTAN2 schema have enum constraints with no sentinel value, making it impossible to express "not available." These are excluded from our validation counts:

| Field | Schema | Issue |
|---|---|---|
| `AJCC_STAGING_SYSTEM_EDITION` | Diagnosis | Enum only `1st`-`8th` |
| `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID` | Diagnosis | Enum only NCIt codes |
| `TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE` | Diagnosis | Enum only UBERON codes |
| `ECOG_PERFORMANCE_STATUS` | FollowUp | Enum only `0`-`5` |

Filed as:
- [ncihtan/htan2-data-model#152](https://github.com/ncihtan/htan2-data-model/issues/152) — AJCC_STAGING_SYSTEM_EDITION
- [ncihtan/htan2-data-model#153](https://github.com/ncihtan/htan2-data-model/issues/153) — All four fields (consolidated)

Once sentinels are added, 100% of migrated rows will validate against the schema with no exclusions.

## Reproducibility

```bash
# Pull source data from BigQuery
uv run htan query bq sql "SELECT * FROM \`isb-cgc-bq.HTAN.clinical_tier1_demographics_current\` LIMIT 3000" --format csv 2>/dev/null \
  | grep -v "^Returned\|^Auto-applied\|^$" \
  | python3 -c "import csv,sys; [print('\t'.join(r)) for r in csv.reader(sys.stdin)]" \
  > /tmp/htan1_full_demographics.tsv

# (repeat for diagnosis, followup)

# Run migration
uv run python scripts/migrate.py \
  --input /tmp/htan1_full_demographics.tsv \
  --config configs/htan1_to_htan2/clinical.transform.yaml \
  --source-class Demographics \
  --output output/htan1_to_htan2/ \
  --normalize-columns

# Validate
uv run python scripts/validate_transformed.py \
  --input-dir output/htan1_to_htan2/ \
  --schema-dir /path/to/htan2_json_schemas/ \
  --ignore-patterns
```
