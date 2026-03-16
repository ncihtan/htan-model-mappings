"""
map_drug_names.py

Crosswalk from HTAN Phase 1 therapeutic agent names to HTAN Phase 2 approved drug enum.

Usage:
    uv run python3 scripts/map_drug_names.py
"""

import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

BAD_DRUG_FILE = Path("/tmp/bad_drug_names.json")
ENUM_FILE = Path("/tmp/htan2_drug_enum.json")
OUTPUT_FILE = Path("/tmp/drug_crosswalk.json")

with open(BAD_DRUG_FILE) as f:
    bad_drug_names: dict[str, int] = json.load(f)

with open(ENUM_FILE) as f:
    drug_enum: list[str] = json.load(f)

# Build case-insensitive lookup: lower -> canonical
enum_lower: dict[str, str] = {d.lower(): d for d in drug_enum}


# ---------------------------------------------------------------------------
# Helper: look up a single drug name in the enum (case-insensitive)
# Returns the canonical enum value or None
# ---------------------------------------------------------------------------

def lookup(name: str) -> str | None:
    """Case-insensitive exact lookup in the drug enum."""
    return enum_lower.get(name.strip().lower())


def lookup_with_suffixes(name: str) -> str | None:
    """Try exact match, then common pharmaceutical suffixes."""
    hit = lookup(name)
    if hit:
        return hit
    for suffix in (
        " Hydrochloride",
        " Mesylate",
        " Sulfate",
        " Phosphate",
        " Acetate",
        " Tosylate",
        " Calcium",
        " Sodium",
    ):
        hit = lookup(name + suffix)
        if hit:
            return hit
    return None


# ---------------------------------------------------------------------------
# Brand → generic map (maps to the canonical enum value after lookup)
# ---------------------------------------------------------------------------

BRAND_TO_GENERIC: dict[str, str] = {
    # brand name (lower) -> preferred search term
    "taxol": "Paclitaxel",
    "doxil": "Pegylated Liposomal Doxorubicin Hydrochloride",
    "herceptin": "Trastuzumab",
    "avastin": "Bevacizumab",
    "bev": "Bevacizumab",
    "xeloda": "Capecitabine",
    "abraxane": "Nab-paclitaxel",
    "nab paclitaxel": "Nab-paclitaxel",
    "gemzar": "Gemcitabine Hydrochloride",
    "pembro": "Pembrolizumab",
    "keytruda": "Pembrolizumab",
    "perjecta": "Pertuzumab",
    "faslodex": "Fulvestrant",
    "taxotere": "Docetaxel",
    "cytoxan": "Cyclophosphamide",
    "enhertu": "Trastuzumab Deruxtecan",
    "tdm1": "Trastuzumab Emtansine",
    "ado-trastuzumab emtansine": "Trastuzumab Emtansine",
}

# ---------------------------------------------------------------------------
# Known combo regimens  → list of component drug search terms
# ---------------------------------------------------------------------------

COMBO_REGIMENS: dict[str, list[str]] = {
    "folfox": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin"],
    "mfolfox6": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin"],
    "folfiri": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride"],
    "folfirinox": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"],
    "mfolfirinox": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"],
    "cmf": ["Cyclophosphamide", "Methotrexate", "Fluorouracil"],
}

# ---------------------------------------------------------------------------
# Typo corrections: input lower → corrected canonical search term
# ---------------------------------------------------------------------------

TYPO_FIXES: dict[str, str] = {
    "cepcitabine": "Capecitabine",
    "olaprib": "Olaparib",
    "afatanib": "Afatinib",
    "gemcitibine": "Gemcitabine Hydrochloride",
    "docetaxcel": "Docetaxel",
    "anastrazole": "Anastrozole",
    "carbplatin": "Carboplatin",
    "lurbinectidin": "Lurbinectedin",
    "premetrexed": "Pemetrexed",
    "ipilmumab": "Ipilimumab",
    "palbociblib": "Palbociclib",
    "dacomitnib": "Dacomitinib",
    "bevaciuzmab": "Bevacizumab",
    "traztuzumab": "Trastuzumab",
    "abrazane": "Nab-paclitaxel",
    "gemcidabine": "Gemcitabine Hydrochloride",
    "ado-trastuzumab emtanisine": "Trastuzumab Emtansine",
}

# ---------------------------------------------------------------------------
# Non-drug terms and trial IDs → empty string
# ---------------------------------------------------------------------------

NON_DRUGS = {
    "radiation",
    "surgery",
    "radiation therapy",
    "not reported",
    "other",
    "clinical trial",
    "keynote-522",
    "celldex trial",
    "ovation ii study",
    "guided sbrt",
    "sbrt",
    "ci",  # ambiguous abbreviation
}

# ---------------------------------------------------------------------------
# Core mapping logic for a single (possibly compound) drug string
# ---------------------------------------------------------------------------

def is_non_drug(name: str) -> bool:
    return name.strip().lower() in NON_DRUGS


def strip_modifiers(name: str) -> str:
    """Remove common adjectival/adverbial prefixes and suffixes."""
    # "osimertinib alone" → "osimertinib"
    # "oral etoposide" → "etoposide"
    # "adjuvant cisplatin+vinorelbine" → "cisplatin+vinorelbine"
    # "temozolomide alone" → "temozolomide"
    # "temozolomide (rechallenge)" → "temozolomide"
    name = re.sub(r'\s*\(rechallenge\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s+alone\s*$', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'^(oral|adjuvant|sequential)\s+', '', name, flags=re.IGNORECASE).strip()
    return name


def resolve_single(raw: str) -> str:
    """
    Resolve a single (non-combo) drug name to its canonical enum value.
    Returns "" if not found in enum.
    """
    name = raw.strip()

    # Non-drug / trial ID
    if is_non_drug(name):
        return ""

    # 1. Direct case-insensitive lookup
    hit = lookup(name)
    if hit:
        return hit

    # 2. Typo fixes
    fix = TYPO_FIXES.get(name.lower())
    if fix:
        hit = lookup_with_suffixes(fix)
        if hit:
            return hit

    # 3. Brand → generic
    generic = BRAND_TO_GENERIC.get(name.lower())
    if generic:
        hit = lookup_with_suffixes(generic)
        if hit:
            return hit

    # 4. Try with common suffixes
    hit = lookup_with_suffixes(name)
    if hit:
        return hit

    # 5. Parenthetical: "MK-3475 (Pembrolizumab)" → try what's in parens first
    paren_match = re.search(r'\(([^)]+)\)', name)
    if paren_match:
        inner = paren_match.group(1).strip()
        hit = lookup_with_suffixes(inner)
        if hit:
            return hit
        # Also try brand map on inner
        generic2 = BRAND_TO_GENERIC.get(inner.lower())
        if generic2:
            hit = lookup_with_suffixes(generic2)
            if hit:
                return hit
        # Try before-paren part
        before_paren = name[:paren_match.start()].strip()
        hit = lookup_with_suffixes(before_paren)
        if hit:
            return hit

    return ""


def resolve_drug_name(raw: str) -> dict:
    """
    Resolve a (possibly compound) drug entry.

    Returns one of:
      {"mapped": "<canonical name>"}                 single drug
      {"mapped": ""}                                 unmappable / non-drug
      {"__SPLIT__": True, "split_into": [...]}       combo regimen
    """
    name = raw.strip()
    name_stripped = strip_modifiers(name)

    # --- non-drug / trial ID check (pre-split) ---
    if is_non_drug(name) or is_non_drug(name_stripped):
        return {"mapped": ""}

    # --- special trial / study noise embedded in combos ---
    # e.g. "Carbo/Taxol/Gen-1 (Ovation II Study)" → strip trial suffix
    name_stripped = re.sub(
        r'\s*[\(/]\s*(?:Ovation II Study|CellDex Trial|KEYNOTE-\w+)[)\s]*',
        '', name_stripped, flags=re.IGNORECASE
    ).strip()

    name_lower = name_stripped.lower()

    # --- known combo regimens (standalone keyword) ---
    # Check if the WHOLE string is a known regimen (possibly with prefix like "m")
    if name_lower in COMBO_REGIMENS:
        components = COMBO_REGIMENS[name_lower]
        resolved = [lookup_with_suffixes(c) or "" for c in components]
        return {"__SPLIT__": True, "split_into": resolved}

    # --- "nivo followed by ipi" style ---
    if "followed by" in name_lower:
        parts = re.split(r'\s+followed\s+by\s+', name_stripped, flags=re.IGNORECASE)
        resolved = []
        for p in parts:
            p = p.strip()
            if not is_non_drug(p):
                r = resolve_single(p)
                if r:
                    resolved.append(r)
        if len(resolved) > 1:
            return {"__SPLIT__": True, "split_into": resolved}
        elif len(resolved) == 1:
            return {"mapped": resolved[0]}
        return {"mapped": ""}

    # --- Detect separator: +, /, "and" (but NOT in single-word names) ---
    # Split heuristic: treat "/" as separator if there are multiple words
    # and "+" always as separator
    has_plus = "+" in name_stripped
    # "/" as separator only if neither part is empty and the whole thing isn't
    # a known single drug
    has_slash = "/" in name_stripped and lookup(name_stripped) is None

    separators = has_plus or has_slash

    if separators:
        # Try splitting on + first, then /
        if has_plus:
            raw_parts = re.split(r'\s*\+\s*(?:/-)?\s*', name_stripped)
        else:
            raw_parts = re.split(r'\s*/\s*', name_stripped)

        resolved_parts = []
        split_needed = False

        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            # Recursively handle nested combos (e.g. "Folfox + Avastin")
            sub = resolve_drug_name(part)
            if sub.get("__SPLIT__"):
                split_needed = True
                for sp in sub["split_into"]:
                    if sp:
                        resolved_parts.append(sp)
            elif sub.get("mapped") == "" and is_non_drug(part):
                # Non-drug part in a combo → skip it (e.g. radiation in combo)
                pass
            else:
                split_needed = True
                if sub.get("mapped"):
                    resolved_parts.append(sub["mapped"])
                else:
                    # part is unmappable; keep empty to signal failure
                    resolved_parts.append("")

        if split_needed and len(resolved_parts) >= 1:
            return {"__SPLIT__": True, "split_into": resolved_parts}
        # Fall through to single-drug resolution

    # --- "and" as separator (e.g. "ipilimumab and nivolumab") ---
    if re.search(r'\band\b', name_stripped, flags=re.IGNORECASE):
        parts = re.split(r'\s+and\s+', name_stripped, flags=re.IGNORECASE)
        if len(parts) > 1:
            resolved_parts = []
            for part in parts:
                part = part.strip()
                r = resolve_single(part)
                resolved_parts.append(r)
            return {"__SPLIT__": True, "split_into": resolved_parts}

    # --- single drug ---
    hit = resolve_single(name_stripped)
    return {"mapped": hit}


# ---------------------------------------------------------------------------
# Additional hand-crafted overrides for tricky cases not caught by logic above
# These are applied AFTER the automatic logic as a final safety net.
# ---------------------------------------------------------------------------

MANUAL_OVERRIDES: dict[str, dict] = {
    # "Doxorubicin Hydrochloride Liposome (Doxil)" — lookup fails, use pegylated form
    "doxorubicin hydrochloride liposome (doxil)": {
        "mapped": "Pegylated Liposomal Doxorubicin Hydrochloride"
    },
    "doxil": {"mapped": "Pegylated Liposomal Doxorubicin Hydrochloride"},
    "doxil (doxorubicin hcl liposome)": {
        "mapped": "Pegylated Liposomal Doxorubicin Hydrochloride"
    },
    # "Doxorubicin Liposomal" — close enough to pegylated form
    "doxorubicin liposomal": {
        "mapped": "Pegylated Liposomal Doxorubicin Hydrochloride"
    },
    "doxorubicin hcl": {"mapped": "Doxorubicin Hydrochloride"},
    # "Paclitaxel Protein-Bound" → Nab-paclitaxel
    "paclitaxel protein-bound": {"mapped": "Nab-paclitaxel"},
    "abraxane (albumin-bound paclitaxel)": {"mapped": "Nab-paclitaxel"},
    "carbo/albumin-bound taxol": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Nab-paclitaxel"],
    },
    # "Carbo/Taxol" → Carboplatin + Paclitaxel
    "carbo/taxol": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Paclitaxel"],
    },
    "carbo/taxotere": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Docetaxel"],
    },
    "carbo/abraxane": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Nab-paclitaxel"],
    },
    "carbo/taxol/bev": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Paclitaxel", "Bevacizumab"],
    },
    "carbo/taxol/gen-1": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Paclitaxel"],
    },
    "carbo/taxol/gen-1 (ovation ii study)": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Paclitaxel"],
    },
    # "5-fu" → Fluorouracil
    "5-fu": {"mapped": "Fluorouracil"},
    # Folfox variants
    "folfox": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin"]},
    "mfolfox6": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin"]},
    "folfox + avastin": {
        "__SPLIT__": True,
        "split_into": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin", "Bevacizumab"],
    },
    "folfox + bevacizumab": {
        "__SPLIT__": True,
        "split_into": ["Leucovorin Calcium", "Fluorouracil", "Oxaliplatin", "Bevacizumab"],
    },
    "folfiri": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride"]},
    "folfirinox": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"]},
    "mfolfirinox": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"]},
    # Case variants
    "folfirinox (folfirinox)": {"__SPLIT__": True, "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"]},
    # "Cisplatin/Pemetrexed" — slash split
    "cisplatin/pemetrexed": {
        "__SPLIT__": True,
        "split_into": ["Cisplatin", "Pemetrexed"],
    },
    "pemetrexed/cisplatin": {
        "__SPLIT__": True,
        "split_into": ["Pemetrexed", "Cisplatin"],
    },
    # "5-FU/Avastin"
    "5-fu/avastin": {
        "__SPLIT__": True,
        "split_into": ["Fluorouracil", "Bevacizumab"],
    },
    # Traztuzumab typo
    "traztuzumab": {"mapped": "Trastuzumab"},
    # "Traztuzumab; Pertuzumab"
    "traztuzumab; pertuzumab": {
        "__SPLIT__": True,
        "split_into": ["Trastuzumab", "Pertuzumab"],
    },
    # "Perjecta/Herceptin"
    "perjecta/herceptin": {
        "__SPLIT__": True,
        "split_into": ["Pertuzumab", "Trastuzumab"],
    },
    # "Faslodex + Abemaciclib"
    "faslodex + abemaciclib": {
        "__SPLIT__": True,
        "split_into": ["Fulvestrant", "Abemaciclib"],
    },
    # "Cytoxan + Taxotere"
    "cytoxan + taxotere": {
        "__SPLIT__": True,
        "split_into": ["Cyclophosphamide", "Docetaxel"],
    },
    # "Gemcitabine + Abraxane" variants
    "gemcitabine + abraxane": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride", "Nab-paclitaxel"],
    },
    "gemcitibine + abraxane": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride", "Nab-paclitaxel"],
    },
    "gemcitabine + abrazane": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride", "Nab-paclitaxel"],
    },
    "gemzar + abraxane": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride", "Nab-paclitaxel"],
    },
    "gem/abraxane": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride", "Nab-paclitaxel"],
    },
    "xeloda + gemcitabine": {
        "__SPLIT__": True,
        "split_into": ["Capecitabine", "Gemcitabine Hydrochloride"],
    },
    # "Leucovorin" alone → Leucovorin Calcium
    "leucovorin": {"mapped": "Leucovorin Calcium"},
    # "Pembro/Lenvatinib"
    "pembro/lenvatinib": {
        "__SPLIT__": True,
        "split_into": ["Pembrolizumab", "Lenvatinib"],
    },
    # Sirolimus — not in enum as standalone; closest is Sirolimus Albumin-bound Nanoparticles
    # Per task: if not found try suffixes; still not found → ""
    "sirolimus": {"mapped": ""},
    # Tipiracil alone — only appears as "Trifluridine and Tipiracil Hydrochloride"
    "tipiracil": {"mapped": "Trifluridine and Tipiracil Hydrochloride"},
    # Fostamatinib — not in enum
    "fostamatinib": {"mapped": ""},
    # Pegfilgrastim — not in enum
    "pegfilgrastim": {"mapped": ""},
    # "Ado-trastuzumab Emtansine (TDM1)"
    "ado-trastuzumab emtansine (tdm1)": {"mapped": "Trastuzumab Emtansine"},
    "ado-trastuzumab emtanisine": {"mapped": "Trastuzumab Emtansine"},
    # "DS-8201a (Enhertu)"
    "ds-8201a (enhertu)": {"mapped": "Trastuzumab Deruxtecan"},
    "ds-8201a": {"mapped": "Trastuzumab Deruxtecan"},
    # DS-1062A / DS 1062a — Datopotamab Deruxtecan
    "ds-1062a": {"mapped": "Datopotamab Deruxtecan"},
    "ds 1062a": {"mapped": "Datopotamab Deruxtecan"},
    # IMMU-132
    "immu-132 (sacituzumab govitecan)": {"mapped": "Sacituzumab Govitecan"},
    # "LY2835219 (Abemaciclib)"
    "ly2835219 (abemaciclib)": {"mapped": "Abemaciclib"},
    # "BYL 719 (Alpelisib)"
    "byl 719 (alpelisib)": {"mapped": "Alpelisib"},
    # "LEE011(Ribociclib)"
    "lee011(ribociclib)": {"mapped": "Ribociclib"},
    # "ARRY-380 (Tucatinib)"
    "arry-380 (tucatinib)": {"mapped": "Tucatinib"},
    # "MK-3475 (Pembrolizumab)"
    "mk-3475 (pembrolizumab)": {"mapped": "Pembrolizumab"},
    # SC16LD6.5 — experimental, not in enum
    "sc16ld6.5": {"mapped": ""},
    # GTX024 — not in enum
    "gtx024": {"mapped": ""},
    # U3-1402 — Patritumab Deruxtecan (U3-1402 is its code name)
    "u3-1402": {"mapped": "Patritumab Deruxtecan"},
    # Rovalpituzumab — Rovalpituzumab Tesirine
    "rovalpituzumab": {"mapped": "Rovalpituzumab Tesirine"},
    # Mirvetuxemab soravtansine — not in enum
    "mirvetuxemab soravtansine": {"mapped": ""},
    # OP-1250 — not in enum
    "op-1250": {"mapped": ""},
    # SAR439859 — not in enum
    "sar439859": {"mapped": ""},
    # CDX 1401 — not in enum
    "cdx 1401": {"mapped": ""},
    # COM701 → Anti-PVRIG MAb
    "com701": {"mapped": "Anti-PVRIG Monoclonal Antibody COM701"},
    # DKY709+PDR001
    "dky709+pdr001": {
        "__SPLIT__": True,
        "split_into": ["IKZF2 Protein Degrader DKY709", ""],
    },
    # EGF816+TNO155 — both not in enum
    "egf816+tno155": {"mapped": ""},
    # GDC-0084 — not in enum
    "gdc-0084": {"mapped": ""},
    # ABT888 → Veliparib
    "temozolomide+abt888": {
        "__SPLIT__": True,
        "split_into": ["Temozolomide", "Veliparib"],
    },
    # LDE225 → Sonidegib
    "cisplatin+etoposide+lde225": {
        "__SPLIT__": True,
        "split_into": ["Cisplatin", "Etoposide", "Sonidegib"],
    },
    # Rebastinib → Rebastinib Tosylate
    "rebastinib": {"mapped": "Rebastinib Tosylate"},
    # Nazartinib (EGF816)
    "egf816": {"mapped": "Nazartinib"},
    # Paclitaxel; AC-T  → split (AC-T = doxorubicin+cyclophosphamide+paclitaxel)
    "paclitaxel; ac-t": {
        "__SPLIT__": True,
        "split_into": ["Paclitaxel", "Doxorubicin Hydrochloride", "Cyclophosphamide"],
    },
    # ddAC-T → dose-dense AC-T: doxorubicin + cyclophosphamide + paclitaxel
    "ddac-t": {
        "__SPLIT__": True,
        "split_into": ["Doxorubicin Hydrochloride", "Cyclophosphamide", "Paclitaxel"],
    },
    # "Paclitaxel; Carboplatin + Gemcidabine"
    "paclitaxel; carboplatin + gemcidabine": {
        "__SPLIT__": True,
        "split_into": ["Paclitaxel", "Carboplatin", "Gemcitabine Hydrochloride"],
    },
    # Gemcitabine + Radiation → split, exclude radiation
    "gemcitabine + radiation": {
        "__SPLIT__": True,
        "split_into": ["Gemcitabine Hydrochloride"],
    },
    # Folfirinox + guided SBRT → just Folfirinox components
    "folfirinox + guided sbrt": {
        "__SPLIT__": True,
        "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"],
    },
    "folfiri + sbrt": {
        "__SPLIT__": True,
        "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride"],
    },
    # "mFolfirinox/Folfiri + SBRT"
    "mfolfirinox/folfiri + sbrt": {
        "__SPLIT__": True,
        "split_into": ["Leucovorin Calcium", "Fluorouracil", "Irinotecan Hydrochloride", "Oxaliplatin"],
    },
    # "Pembrolizumab + Pemetrexed + Carboplatin"
    "pembrolizumab + pemetrexed + carboplatin": {
        "__SPLIT__": True,
        "split_into": ["Pembrolizumab", "Pemetrexed", "Carboplatin"],
    },
    # "pembrolizumab/pemetrexed/carboplatin"
    "pembrolizumab/pemetrexed/carboplatin": {
        "__SPLIT__": True,
        "split_into": ["Pembrolizumab", "Pemetrexed", "Carboplatin"],
    },
    "bevacizumab/pemetrexed/carboplatin": {
        "__SPLIT__": True,
        "split_into": ["Bevacizumab", "Pemetrexed", "Carboplatin"],
    },
    # Atezolizumab with literal "<U+00A0>" suffix (stored as literal text in the JSON)
    "atezolizumab<u+00a0>": {"mapped": "Atezolizumab"},
    # "carboplatin+etoposide (rechallenge)" / "cis-carboplatin+etoposide"
    "carboplatin+etoposide (rechallenge)": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Etoposide"],
    },
    "carboplatin+etoposide+osimertinib (rechallenge)": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Etoposide", "Osimertinib"],
    },
    "cis-carboplatin+etoposide": {
        "__SPLIT__": True,
        "split_into": ["Cisplatin", "Carboplatin", "Etoposide"],
    },
    "cis/carboplatin+etoposide": {
        "__SPLIT__": True,
        "split_into": ["Cisplatin", "Carboplatin", "Etoposide"],
    },
    # "carboplatin+etoposide+tarextumab) vs placebo" — tarextumab not in enum
    "carboplatin+etoposide+tarextumab) vs placebo": {
        "__SPLIT__": True,
        "split_into": ["Carboplatin", "Etoposide", ""],
    },
    # "nazartinib+investigational" — investigational not a drug
    "nazartinib+investigational": {"mapped": "Nazartinib"},
    # "Neovax + Ipilimumab + Nivolumab" — Neovax not in enum
    "neovax + ipilimumab + nivolumab": {
        "__SPLIT__": True,
        "split_into": ["Ipilimumab", "Nivolumab"],
    },
    # "19-604:Atezolizumab + Bevacizumab" — study prefix
    "19-604:atezolizumab + bevacizumab": {
        "__SPLIT__": True,
        "split_into": ["Atezolizumab", "Bevacizumab"],
    },
    # "sequential nivo followed by ipi"
    "sequential nivo followed by ipi": {
        "__SPLIT__": True,
        "split_into": ["Nivolumab", "Ipilimumab"],
    },
    # "ly3009120 (RAF inhibitor)" — not in enum
    "ly3009120 (raf inhibitor)": {"mapped": ""},
    # "COM701 +/- PD-1 inhibitor"
    "com701 +/- pd-1 inhibitor": {"mapped": "Anti-PVRIG Monoclonal Antibody COM701"},
    # pembrolizumab + interferon → split
    "pembrolizumab + interferon": {
        "__SPLIT__": True,
        "split_into": ["Pembrolizumab", ""],
    },
    # "oral topotecan" → Oral Topotecan Hydrochloride
    "oral topotecan": {"mapped": "Oral Topotecan Hydrochloride"},
}


# ---------------------------------------------------------------------------
# Main resolution function that applies overrides first
# ---------------------------------------------------------------------------

def resolve(raw: str) -> dict:
    key = raw.strip().lower()

    # Apply manual override if present
    if key in MANUAL_OVERRIDES:
        return MANUAL_OVERRIDES[key]

    return resolve_drug_name(raw)


# ---------------------------------------------------------------------------
# Build crosswalk
# ---------------------------------------------------------------------------

crosswalk: dict[str, dict] = {}

for drug_name in bad_drug_names:
    result = resolve(drug_name)
    crosswalk[drug_name] = result


# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------

n_total = len(crosswalk)
n_mapped = sum(1 for v in crosswalk.values() if v.get("mapped") and v["mapped"] != "")
n_split = sum(1 for v in crosswalk.values() if v.get("__SPLIT__"))
n_empty = sum(1 for v in crosswalk.values() if v.get("mapped") == "")

print(f"Total entries:        {n_total}")
print(f"  Single drug mapped: {n_mapped}")
print(f"  Split combos:       {n_split}")
print(f"  Unmapped (empty):   {n_empty}")
print()

# Breakdown of split combos
print("=== Split Combos ===")
for name, v in sorted(crosswalk.items(), key=lambda x: x[0].lower()):
    if v.get("__SPLIT__"):
        print(f"  {name!r:55s} -> {v['split_into']}")

print()
print("=== Unmapped / Empty ===")
for name, v in sorted(crosswalk.items(), key=lambda x: x[0].lower()):
    if v.get("mapped") == "":
        print(f"  {name!r}")

print()
print("=== Single Drug Mappings (sample) ===")
count = 0
for name, v in sorted(crosswalk.items(), key=lambda x: x[0].lower()):
    if v.get("mapped") and v["mapped"] != "":
        print(f"  {name!r:45s} -> {v['mapped']!r}")
        count += 1
        if count >= 40:
            print("  ...")
            break

# ---------------------------------------------------------------------------
# Write output
# ---------------------------------------------------------------------------

with open(OUTPUT_FILE, "w") as f:
    json.dump(crosswalk, f, indent=2, ensure_ascii=False)

print(f"\nOutput written to {OUTPUT_FILE}")
