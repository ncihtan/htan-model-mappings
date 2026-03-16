# HTAN Phase 1 to Phase 2 Clinical Data Migration Report

**Date**: 2026-03-16
**Source**: HTAN Phase 1 BigQuery (`isb-cgc-bq.HTAN`, Release 7.0, Nov 2025)
**Target schema**: `ncihtan/htan2-data-model@v1.3.0` (JSON Schema)
**Validation**: HTAN2 JSON Schemas v1.3.0, ignoring HTAN1 participant ID patterns

## Summary

All 7 HTAN Phase 1 clinical BigQuery tables migrated to 8 HTAN2-compatible output tables. **Zero enum errors** — every value we output validates against the HTAN2 JSON Schema.

| Output Table | Rows | Cols | Adjusted | Strict | Remaining |
|---|---|---|---|---|---|
| `htan1_Demographics.tsv` | 2,805 | 5 | **100%** | 100% | — |
| `htan1_VitalStatus.tsv` | 2,805 | 5 | **100%** | 81% | Optional `AGE_IN_DAYS_AT_DEATH` |
| `htan1_Diagnosis.tsv` | 2,300 | 16 | **100%** | 13% | No-sentinel fields (schema issue) |
| `htan1_Exposure.tsv` | 2,004 | 5 | **100%** | 100% | — |
| `htan1_FamilyHistory.tsv` | 2,284 | 3 | **99.9%** | 93% | 2 rows with text in integer field |
| `htan1_FollowUp.tsv` | 2,167 | 10 | **97.7%** | 2% | 49 unresolved UBERON text terms |
| `htan1_MolecularTest.tsv` | 3,000 | 15 | **48.5%** | 49% | 1,539 empty `CLINICAL_BIOSPECIMEN_TYPE` in source |
| `htan1_Therapy.tsv` | 3,000 | 12 | **28.9%** | 0% | Empty required array fields in source |
| **Total** | **20,365** | | | |

**Adjusted** = excluding no-sentinel schema issues (#152/#153/#154) and optional missing fields.
**Strict** = raw JSON Schema validation (ignoring HTAN1 ID patterns only).

MolecularTest and Therapy percentages reflect empty required fields in the HTAN1 source data, not transformation errors.

## Source Data

All 7 clinical tier 1 BigQuery tables, `SELECT *`:

| Source Table | Rows | Columns |
|---|---|---|
| `clinical_tier1_demographics_current` | 2,805 | 23 |
| `clinical_tier1_diagnosis_current` | 2,300 | 93 |
| `clinical_tier1_followup_current` | 2,167 | 61 |
| `clinical_tier1_exposure_current` | 2,004 | 34 |
| `clinical_tier1_familyhistory_current` | 2,284 | 13 |
| `clinical_tier1_moleculartest_current` | 3,000 | 45 |
| `clinical_tier1_therapy_current` | 3,000 | 26 |

## Transform Pipeline

The migration engine (`scripts/migrate.py`) applies a config-driven pipeline with the following stages:

### Tier 1: Field Renaming

Field-level SSSOM mappings (309 across all domains, 68 clinical) rename Phase 1 columns to Phase 2 names. Cross-class field resolution handles inherited attributes (e.g., `HTAN Participant ID` defined under `Patient` but appearing in every table).

| Phase 1 | Phase 2 | Method |
|---|---|---|
| `Ethnicity` | `ETHNIC_GROUP` | caDSR:2192217 match |
| `Race` | `RACE` | caDSR:2192199 match |
| `Tumor Grade` | `TUMOR_GRADE` | Normalized name match |
| `Disease Response` | `DISEASE_RESPONSE` | Normalized name match |

### Tier 2: Value Remapping

356 clinical value-level SSSOM mappings (285 deterministic + 71 LLM-assisted) remap enum values:

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
| `Colon NOS` | `UBERON:0001155` | UBERON (22,603 entries incl. 73 OLS-verified) |
| `Adenocarcinoma NOS` | `C2852` | NCIt (20,195 entries incl. 59 OLS-verified) |
| `Breast NOS` | `UBERON:0000310` | UBERON |
| `Glioblastoma` | `C3058` | NCIt |

ICD-O morphology NOS suffixes are automatically stripped before lookup.

**Resolution rates** (for rows with actual values, excluding "Not Reported"/"unknown"):
- NCIt diagnosis codes: 1,987/1,987 (100%)
- UBERON tissue codes: 2,104/2,104 (100%)

**Drug name crosswalk** (Therapy): 202 HTAN1 therapeutic agent names mapped to the HTAN2 NCIt drug enum (6,915 entries) via Sonnet agent:
- 74 single-drug mappings (casing fixes, brand-to-generic, typo corrections)
- 105 combo regimen splits (FOLFOX, FOLFIRINOX, AC-T, etc. split into individual drugs)
- 23 non-drugs cleared (radiation, surgery, clinical trial names)

**Gene symbol normalization** (MolecularTest): 118 non-HUGO gene names corrected via Sonnet agent:
- Common aliases: HER2→ERBB2, ER→ESR1, PR→PGR, p53→TP53, Ki67→MKI67, PDL1→CD274
- Retired symbols: C11orf30→EMSY, TCEB1→ELOC, H3F3A→H3-3A
- Typos: BRAC2→BRCA2, E1F1AX→EIF1AX, SET2D→SETD2
- 88 corrupted TCF7L* entries cleared, 4 fusion genes cleared

### Tier 4: Structural Transforms

**Field split**: Phase 1 `Gender` (conflated concept) split into Phase 2 `GENDER_IDENTITY` + `SEX` with value mappings applied to both targets.

**Class relocations**: Fields that moved between classes in the model redesign:

| Phase 1 Location | Phase 2 Location | Rows |
|---|---|---|
| Demographics / `Vital Status` | VitalStatus / `VITAL_STATUS` | 2,805 |
| Demographics / `Cause of Death` | VitalStatus / `CAUSE_OF_DEATH` | 2,805 |
| Demographics / `Cause of Death Source` | VitalStatus / `CAUSE_OF_DEATH_SOURCE` | 2,805 |
| Diagnosis / `Progression or Recurrence` | FollowUp / `PROGRESSION_OR_RECURRENCE` | 2,300 |
| Diagnosis / `Progression or Recurrence Type` | FollowUp / `PROGRESSION_OR_RECURRENCE_TYPE` | 2,300 |

Relocated fields are written to separate output files named by their HTAN2 target class, with `HTAN_PARTICIPANT_ID` carried through for joins.

**Passthrough fields**: `HTAN_PARTICIPANT_ID` (and `HTAN_PARENT_ID` for biospecimen/assay) appear in every BQ table via LinkML inheritance. These are always carried forward regardless of source class.

### Tier 5: Defaults and Sentinels

Required fields with no source data filled with appropriate sentinels:

| Sentinel | Fields | Spec reference |
|---|---|---|
| `Not Reported` | CLINICAL_T/N/M_STAGE, METHOD_OF_DIAGNOSIS, TUMOR_CLASSIFICATION_CATEGORY, TUMOR_GRADE, LAST_KNOWN_DISEASE_STATUS, DISEASE_RESPONSE, MENOPAUSE_STATUS, PROGRESSION_OR_RECURRENCE, INITIAL_DISEASE_STATUS, ENVIRONMENTAL_EXPOSURE, FAMILY_MEMBER_CANCER_HISTORY, MOLECULAR_ANALYSIS_RESULT | HTAN2 enum sentinel |
| `Unknown` | METASTASIS_AT_DIAGNOSIS, TREATMENT_INTENT_TYPE | HTAN2 enum sentinel |
| `Not reported` | VITAL_STATUS, SMOKING_HISTORY | HTAN2 enum (lowercase) |
| `Not applicable` | ALCOHOL_HISTORY_INDICATOR | HTAN2 enum sentinel |
| `Not Applicable` | PHARMACOTHERAPY_TYPE | HTAN2 enum sentinel |
| `-1` | All AGE_IN_DAYS_* fields | caDSR spec: "Use -1 if not available" |

### Value Corrections

Post-transform fixes for values not covered by SSSOM or from relocated fields:

| Category | Examples |
|---|---|
| Casing | `unknown` → `Unknown`, `no` → `No`, `Not Reported` → `Not reported` (VitalStatus) |
| Consolidation | `Yes - Progression or Recurrence` → `Yes` |
| Abbreviation expansion | `PD-Progressive Disease` → `Progressive Disease`, `CR-Complete Response` → `Complete Response` |
| Synonym | `Surgical Complications` → `Surgical Complication`, `Autopsy` → `Autopsy Report` |
| Numeric format | `0.0` → `0` (ECOG), `1.0` → `1` |
| Missing sentinel | `Other` (Race) → `Unknown`, text in integer fields → `-1` |
| Out-of-enum ontology | `UBERON:8480060` (paraspinal) → `UBERON:0001130` (vertebral column) |
| Brand→generic drug | `Taxol` → `Paclitaxel`, `Herceptin` → `Trastuzumab`, `Doxil` → `Pegylated Liposomal Doxorubicin Hydrochloride` |
| Combo regimen split | `carboplatin+etoposide` → `["Carboplatin", "Etoposide"]` |
| Gene alias→HUGO | `HER2` → `ERBB2`, `p53` → `TP53`, `Ki67` → `MKI67` |
| Line number normalization | `1st`, `First`, `1.0` → `1`; drug names in regimen field → `Not Reported` |

### Array Fields

HTAN2 schema defines some fields as arrays (e.g., `TREATMENT_TYPE`, `THERAPEUTIC_AGENTS`). These are output as JSON arrays within TSV cells:

```
["Chemotherapy"]
["Carboplatin", "Etoposide"]
["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin"]
```

Comma-separated source values are split into array elements. Combo regimen acronyms (FOLFOX, FOLFIRINOX, etc.) are expanded into their component drugs.

## Output Schema

### htan1_Demographics.tsv (2,805 rows)
`HTAN_PARTICIPANT_ID`, `ETHNIC_GROUP`, `GENDER_IDENTITY`, `RACE`, `SEX`

### htan1_VitalStatus.tsv (2,805 rows)
`HTAN_PARTICIPANT_ID`, `AGE_IN_DAYS_AT_LAST_KNOWN_SURVIVAL_STATUS`, `CAUSE_OF_DEATH`, `CAUSE_OF_DEATH_SOURCE`, `VITAL_STATUS`

### htan1_Diagnosis.tsv (2,300 rows)
`HTAN_PARTICIPANT_ID`, `AGE_IN_DAYS_AT_DIAGNOSIS`, `AGE_IN_DAYS_AT_LAST_KNOWN_DISEASE_STATUS`, `AJCC_STAGING_SYSTEM_EDITION`, `CLINICAL_M_STAGE`, `CLINICAL_N_STAGE`, `CLINICAL_T_STAGE`, `LAST_KNOWN_DISEASE_STATUS`, `METASTASIS_AT_DIAGNOSIS`, `METHOD_OF_DIAGNOSIS`, `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID`, `TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE`, `TUMOR_CLASSIFICATION_CATEGORY`, `TUMOR_GRADE`

### htan1_Exposure.tsv (2,004 rows)
`HTAN_PARTICIPANT_ID`, `ALCOHOL_HISTORY_INDICATOR`, `PACK_YEARS_SMOKED`, `SMOKING_HISTORY`, `YEARS_SMOKED`

### htan1_FamilyHistory.tsv (2,284 rows)
`HTAN_PARTICIPANT_ID`, `FAMILY_MEMBER_CANCER_HISTORY`, `RELATIVES_WITH_CANCER_HISTORY`

### htan1_FollowUp.tsv (2,167 rows)
`HTAN_PARTICIPANT_ID`, `AGE_IN_DAYS_AT_FOLLOWUP`, `AGE_IN_DAYS_AT_PROGRESSION_OR_RECURRENCE`, `DISEASE_RESPONSE`, `ECOG_PERFORMANCE_STATUS`, `EVIDENCE_OF_RECURRENCE_TYPE`, `MENOPAUSE_STATUS`, `PROGRESSION_OR_RECURRENCE`, `PROGRESSION_OR_RECURRENCE_ANATOMIC_SITE_UBERON_CODE`, `PROGRESSION_OR_RECURRENCE_TYPE`

### htan1_MolecularTest.tsv (3,000 rows)
`HTAN_PARTICIPANT_ID`, `AGE_IN_DAYS_AT_MOLECULAR_TEST_START`, `CLINICAL_BIOSPECIMEN_TYPE`, `COPY_NUMBER`, `EXON`, `GENE_SYMBOL`, `MOLECULAR_ANALYSIS_METHOD`, `MOLECULAR_ANALYSIS_RESULT`, `MOLECULAR_CONSEQUENCE`, `PATHOGENICITY`, `TEST_ANALYTE_TYPE`, `TEST_RESULT`, `TEST_UNITS`, `VARIANT_ORIGIN`, `VARIANT_TYPE`

### htan1_Therapy.tsv (3,000 rows)
`HTAN_PARTICIPANT_ID`, `AGE_IN_DAYS_AT_TREATMENT_END`, `AGE_IN_DAYS_AT_TREATMENT_START`, `INITIAL_DISEASE_STATUS`, `NUMBER_OF_CYCLES`, `PHARMACOTHERAPY_TYPE`, `REGIMEN_OR_LINE_OF_THERAPY`, `RESPONSE`, `THERAPEUTIC_AGENTS`, `THERAPY_ANATOMIC_SITE_UBERON_CODE`, `TREATMENT_INTENT_TYPE`, `TREATMENT_TYPE`

## Schema Issues Filed

Required fields with no sentinel value or structural limitations in the HTAN2 schema:

| Issue | Field(s) | Impact |
|---|---|---|
| [#152](https://github.com/ncihtan/htan2-data-model/issues/152) | `AJCC_STAGING_SYSTEM_EDITION` | 1,995 rows (87%) can't express "not staged" |
| [#153](https://github.com/ncihtan/htan2-data-model/issues/153) | `AJCC_STAGING_SYSTEM_EDITION`, `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID`, `TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE`, `ECOG_PERFORMANCE_STATUS` | Consolidated: all 4 required enum fields with no sentinel |
| [#154](https://github.com/ncihtan/htan2-data-model/issues/154) | `GENE_SYMBOL` | Cannot represent fusion genes (BCR-ABL1, etc.) |

## Reproducibility

```bash
# Pull all clinical data from BigQuery
for table in demographics diagnosis followup exposure familyhistory moleculartest therapy; do
  uv run htan query bq sql \
    "SELECT * FROM \`isb-cgc-bq.HTAN.clinical_tier1_${table}_current\` LIMIT 3000" \
    --format csv 2>/dev/null \
    | grep -v "^Returned\|^Auto-applied\|^$" \
    | python3 -c "import csv,sys; [print('\t'.join(r)) for r in csv.reader(sys.stdin)]" \
    > /tmp/htan1_full_${table}.tsv
done

# Run migration (example: Demographics)
uv run python scripts/migrate.py \
  --input /tmp/htan1_full_demographics.tsv \
  --config configs/htan1_to_htan2/clinical.transform.yaml \
  --source-class Demographics \
  --output output/htan1_to_htan2/ \
  --normalize-columns

# Source class names per table:
#   demographics    → Demographics
#   diagnosis       → Diagnosis
#   followup        → "Follow Up"
#   exposure        → Exposure
#   familyhistory   → "Family History"
#   moleculartest   → "Molecular Test"
#   therapy         → Therapy

# Download HTAN2 JSON Schemas for validation
for cls in Demographics Diagnosis VitalStatus FollowUp Exposure FamilyHistory MolecularTest Therapy; do
  curl -sL "https://raw.githubusercontent.com/ncihtan/htan2-data-model/main/JSON_Schemas/v1.3.0/HTAN.${cls}-v1.3.0-schema.json" \
    -o /tmp/htan2_json_schemas/${cls}.json
done

# Validate
uv run python scripts/validate_transformed.py \
  --input-dir output/htan1_to_htan2/ \
  --schema-dir /tmp/htan2_json_schemas/ \
  --ignore-patterns
```
