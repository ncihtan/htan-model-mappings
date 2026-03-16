# HTAN Phase 1 to Phase 2 Model Mappings

Field-level SSSOM mappings from [ncihtan/data-models@v25.2.1](https://github.com/ncihtan/data-models/tree/v25.2.1) (Schematic CSV) to [ncihtan/htan2-data-model@v1.3.0](https://github.com/ncihtan/htan2-data-model/tree/v1.3.0) (LinkML).

Generated 2026-03-16.

## Overview

HTAN Phase 2 is a substantial redesign of the HTAN data model. The Phase 1 model used a flat Schematic CSV with 59 classes and a broad, permissive schema. Phase 2 adopts LinkML with a smaller set of tightly-defined classes, UBERON/NCI Thesaurus ontology codes, age-in-days temporal fields, and a hierarchical class structure for assays. This mapping set documents the field-level correspondence between the two models across three domains.

| Domain | Matched | Unmapped Source | Unmapped Target | Files |
|--------|---------|-----------------|-----------------|-------|
| Clinical | 68 | 351 | 9 | `clinical_fields.sssom.tsv` |
| Biospecimen | 35 | 31 | 2 | `biospecimen_fields.sssom.tsv` |
| Assay | 206 | 411 | 77 | `assay_fields.sssom.tsv` |
| **Total** | **309** | **793** | **88** | 9 files |

Each domain produces three files:
- `*_fields.sssom.tsv` -- matched source-to-target mappings with predicates and confidence scores
- `*_unmapped_source.sssom.tsv` -- Phase 1 fields with no Phase 2 equivalent, annotated with reasons
- `*_unmapped_target.sssom.tsv` -- Phase 2 fields with no Phase 1 predecessor, categorized by type

## Matching Methodology

Mappings were produced through a three-stage pipeline:

1. **caDSR ID matching** (deterministic) -- Fields sharing the same caDSR common data element identifier are matched as `skos:exactMatch` at confidence 1.0. This is the highest-fidelity signal and anchors the mapping. Only clinical and biospecimen fields carry caDSR IDs; assay fields do not.

2. **Normalized name matching** (deterministic) -- Field names are lowercased, stripped of prefixes, and converted to underscore form. Exact normalized matches are `skos:exactMatch` at confidence 0.9. This captures the many fields that were simply renamed from Title Case to UPPER_SNAKE_CASE.

3. **Semantic matching** (LLM-assisted) -- Remaining unmatched fields are grouped by domain area and evaluated by language model agents considering descriptions, valid value overlap, naming patterns, and domain context. Results are reviewed by a QA agent that checks for duplicates, adjusts confidence on cross-class or 1-to-many mappings, and corrects false positives.

### Match rates by method

| Method | Clinical | Biospecimen | Assay | Total |
|--------|----------|-------------|-------|-------|
| caDSR ID | 10 | 10 | 0 | 20 |
| Normalized name | 26 | 10 | 113 | 149 |
| Semantic reasoning | 19 | 10 | 82 | 111 |
| QA-modified | 13 | 5 | 11 | 29 |

## Confidence and Predicate Summary

| Predicate | Clinical | Biospecimen | Assay | Total | Meaning |
|-----------|----------|-------------|-------|-------|---------|
| `skos:exactMatch` | 39 | 23 | 172 | 234 | Same concept and semantics |
| `skos:closeMatch` | 26 | 9 | 23 | 58 | Same concept, different scope or encoding |
| `skos:broadMatch` | 2 | 0 | 4 | 6 | Source is broader than target |
| `skos:narrowMatch` | 1 | 1 | 0 | 2 | Source is narrower than target |
| `skos:relatedMatch` | 0 | 2 | 7 | 9 | Related but not equivalent |

Average confidence across all 309 matched mappings is **0.87**.

## Domain-Specific Notes

### Clinical

The clinical domain underwent the most structural reorganization. Key changes:

- **Temporal fields shifted from days-from-index to age-in-days.** HTAN1 used `Days to Diagnosis`, `Days to Follow Up`, etc. (days from an index date). HTAN2 uses `AGE_IN_DAYS_AT_DIAGNOSIS`, `AGE_IN_DAYS_AT_FOLLOWUP`, etc. (absolute age). These are mapped as `skos:closeMatch` at 0.85 since they represent the same event but require a calculation to convert.

- **Gender was split into two fields.** HTAN1 `Gender` (caDSR:2200604) conflated biological sex and gender identity. HTAN2 separates `GENDER_IDENTITY` and `SEX`. The primary mapping is Gender -> GENDER_IDENTITY (closeMatch 0.8); the secondary is Gender -> SEX (broadMatch 0.6).

- **Text terms replaced by ontology codes.** `Tissue or Organ of Origin` (free text) became `TISSUE_OR_ORGAN_OF_ORIGIN_UBERON_CODE` (UBERON identifier). `Primary Diagnosis` (text) has a new companion `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID`. These are closeMatch since the concept is identical but the encoding differs.

- **Fields relocated between classes.** `Progression or Recurrence` moved from Diagnosis to FollowUp. `Vital Status` moved from Demographics to a dedicated VitalStatus class. Cross-class mappings are closeMatch at 0.75.

- **351 unmapped source fields** fall into two categories: 108 cancer-type-specific Tier 2/3 fields (Breast Cancer Tier 3, Melanoma Tier 3, etc.) that HTAN2 does not include, and 243 granular clinical fields from core classes that HTAN2 streamlined away.

- **9 unmapped target fields** are new in HTAN2, including `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID`, `ENVIRONMENTAL_EXPOSURE_TYPE`, `PHARMACOTHERAPY_TYPE`, and several `AGE_IN_DAYS_AT_*` temporal fields.

### Biospecimen

The biospecimen domain has the highest target coverage (95%). Most fields carried over with name changes.

- **20 caDSR-anchored matches** provide a strong foundation. However, one false positive was detected and removed: HTAN1 `Percent Neutrophil Infiltration` had an incorrect caDSR annotation (2841233, which actually means "Percent Normal Cells"), producing a spurious match to `PERCENT_NORMAL_CELLS`.

- **Dimension fields restructured.** HTAN1 used generic `Biospecimen Dimension 1/2/3`; HTAN2 uses named `LONGEST_DIMENSION` and `SHORTEST_DIMENSION`. Mapped as closeMatch at 0.7 based on convention (dimension 1 = longest).

- **Fixative Type -> PRESERVATION_MEDIUM** is a `skos:narrowMatch` since fixatives are a subset of preservation media.

- **31 unmapped source fields** include granular histology metrics (percent infiltration by cell type), specimen-subtype fields (Blood/Bone Marrow/Urine Biospecimen Type), and processing details.

- **2 unmapped target fields**: `SITE_OF_RESECTION_OR_BIOPSY` (new UBERON-coded anatomic site) and `ICD_10_DISEASE_CODE` (new ICD-10 coding for precancerous lesions).

### Assay

The assay domain is the largest and most restructured. HTAN2 introduced a class hierarchy (CoreFileAttributes -> BaseSequencingAttributes -> level-specific classes) and new dedicated modules (MultiplexMicroscopy, SpatialOmics, WES, DigitalPathology).

- **No caDSR IDs exist in either model's assay domain.** All matching relied on normalized names (113 matches) and semantic reasoning (82 matches).

- **FILENAME and FILE_FORMAT appear in every HTAN2 level class.** These all map back to the corresponding HTAN1 level class's Filename/File Format, or to the Assay base class. This accounts for a significant portion of the 172 exact matches.

- **Base-class redistribution.** HTAN1 put QC metrics, workflow URLs, and sequencing parameters on a single Sequencing class (181 fields). HTAN2 distributes these across BaseSequencingLevel1Attributes, BaseSequencingLevel2Attributes, and assay-specific level classes. Cross-class matches are closeMatch.

- **1-to-many splits** occur where HTAN1 combined concepts that HTAN2 separates: `Imaging Assay Type` -> both `EXPERIMENTAL_STRATEGY_AND_DATA_SUBTYPES` and `IMAGE_MODALITY`; `Microscope` -> both `IMAGING_EQUIPMENT_MANUFACTURER` and `IMAGING_EQUIPMENT_MODEL`.

- **411 unmapped source fields** are dominated by: Sequencing base class (103 fields of granular QC metrics), Spatial Transcriptomics platform-specific fields (70), scATAC-seq (55, no HTAN2 module yet), and assay types without HTAN2 modules (Mass Spec, Electron Microscopy, RPPA, NanoString GeoMx, Microarray, CITE-seq, scmC-seq).

- **77 unmapped target fields** reflect HTAN2's new architecture: bundle-level fields (BUNDLE_CONTENTS, HAS_SEQUENCING, HAS_IMAGES), processing provenance (CLUSTERING_METHOD, DIMENSIONALITY_REDUCTION_METHOD, CELL_TYPE_CALLING_METHOD), data governance (LICENSE, DE_IDENTIFIED), and AnnData compliance fields.

## New in Phase 2 (Unmapped Target Fields)

The 88 HTAN2 fields with no Phase 1 predecessor fall into distinct categories that reflect the design priorities of the new model:

| Category | Count | Examples |
|----------|-------|---------|
| Analysis provenance | 22 | `CLUSTERING_METHOD`, `DIMENSIONALITY_REDUCTION_METHOD`, `CELL_TYPE_CALLING_METHOD`, `CELL_SEGMENTATION_METHOD` |
| Boolean indicators | 16 | `HAS_CLUSTERING`, `HAS_CELL_SEGMENTATION`, `HAS_IMAGES`, `HAS_PROBE_SET`, `HAS_NORMALISED_ARRAY` |
| Container references | 14 | `LEVEL_1_DATA`, `LEVEL_2_DATA`, `level1_data`, `PANEL_DATA` |
| Bundle/packaging | 5 | `BUNDLE_CONTENTS`, `PORTAL_PREVIEW_FILE`, `TOOL_COMPATIBILITY` |
| Data governance | 6 | `LICENSE`, `DE_IDENTIFIED`, `DE_IDENTIFICATION_METHOD_TYPE`, `SLIDE_LABEL_REDACTED` |
| Workflow URLs | 5 | `SEGMENTATION_WORKFLOW_URL`, `FEATURE_EXTRACTION_WORKFLOW_URL` |
| Age-in-days temporal | 5 | `AGE_IN_DAYS_AT_MOLECULAR_TEST_START`, `AGE_IN_DAYS_AT_DEATH` |
| Ontology-coded fields | 3 | `PRIMARY_DIAGNOSIS_NCI_THESAURUS_ID`, `SITE_OF_RESECTION_OR_BIOPSY`, `ICD_10_DISEASE_CODE` |
| Spatial-specific | 7 | `CYTASSIST_USED`, `REGION_AREA`, `SAME_SECTION_IMAGING_ID`, `PANEL_SYNAPSE_ID` |
| AnnData compliance | 2 | `ANNDATA_SCHEMA_VERSION`, `ANNDATA_STRUCTURE_VALIDATED` |
| Other | 3 | `PHARMACOTHERAPY_TYPE`, `ENVIRONMENTAL_EXPOSURE_TYPE`, `TIMEPOINT_LABEL` |

These are catalogued in the `*_unmapped_target.sssom.tsv` files with categorized reasons in the comment column.

## How to Use These Mappings

**For data migration**: Start with `skos:exactMatch` mappings at confidence >= 0.9. These are safe for automated field renaming. `skos:closeMatch` mappings require transformation logic (unit conversion, ontology lookup, structural reorganization). Lower-confidence and `skos:relatedMatch` mappings should be reviewed manually.

**For gap analysis**: The `*_unmapped_source.sssom.tsv` files identify Phase 1 fields that have no Phase 2 home. The `*_unmapped_target.sssom.tsv` files identify new Phase 2 requirements with no Phase 1 source. The `comment` column in both categorizes the reason.

**For validation**: Run `python scripts/validate_mappings.py mappings/htan1_to_htan2/` to check structural validity of all files.

## File Format

All files follow the [SSSOM](https://mapping-commons.github.io/sssom/) specification with a YAML metadata header and tab-separated body. Key columns:

| Column | Description |
|--------|-------------|
| `subject_id` | Source (Phase 1) field CURIE |
| `subject_label` | Source field name |
| `predicate_id` | SKOS mapping predicate |
| `object_id` | Target (Phase 2) field CURIE |
| `object_label` | Target field name |
| `mapping_justification` | How the mapping was determined (SEMAPV term) |
| `confidence` | Float 0.0-1.0 |
| `comment` | Rationale or categorization |
