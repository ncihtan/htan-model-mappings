#!/usr/bin/env python3
"""Look up ontology terms via the EBI OLS4 API.

Provides two capabilities:
1. Resolve a code to its preferred label (e.g., NCIT C2852 → "Adenocarcinoma")
2. Search for a text term and return matching codes (e.g., "Adenocarcinoma NOS" → C2852)

The OLS4 API is free and requires no authentication.

Usage:
    # Resolve a single code
    python ols_lookup.py resolve --ontology ncit --code C2852

    # Search for a term
    python ols_lookup.py search --ontology ncit --query "Adenocarcinoma" --exact

    # Build ICD-O → NCIt crosswalk from a list of terms
    python ols_lookup.py crosswalk \
        --terms-file /tmp/icdo_terms.txt \
        --ontology ncit \
        --output lookups/icdo_to_ncit_crosswalk.json

    # Verify an existing crosswalk (resolve all codes and check labels)
    python ols_lookup.py verify --crosswalk lookups/icdo_to_ncit_crosswalk.json --ontology ncit
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path


OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"


def ols_resolve(ontology: str, code: str) -> dict | None:
    """Resolve an ontology code to its term metadata via OLS4.

    Returns dict with 'label', 'short_form', 'description', 'obo_id' or None.
    """
    # OLS4 uses ONTOLOGY_CODE format (e.g., NCIT_C2852)
    short_form = f"{ontology.upper()}_{code}" if not code.startswith(ontology.upper()) else code
    url = f"{OLS4_BASE}/ontologies/{ontology}/terms?short_form={short_form}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Warning: OLS lookup failed for {code}: {e}", file=sys.stderr)
        return None

    terms = data.get("_embedded", {}).get("terms", [])
    if not terms:
        return None

    term = terms[0]
    return {
        "label": term.get("label", ""),
        "short_form": term.get("short_form", ""),
        "description": (term.get("description") or [""])[0],
        "obo_id": term.get("obo_id", ""),
    }


def ols_search(ontology: str, query: str, exact: bool = False, rows: int = 10) -> list[dict]:
    """Search for terms in an ontology via OLS4.

    Returns list of dicts with 'label', 'short_form', 'obo_id'.
    """
    params = {
        "q": query,
        "ontology": ontology,
        "rows": rows,
        "exact": "true" if exact else "false",
    }
    url = f"{OLS4_BASE}/search?{urllib.parse.urlencode(params)}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"Warning: OLS search failed for '{query}': {e}", file=sys.stderr)
        return []

    results = []
    for doc in data.get("response", {}).get("docs", []):
        results.append({
            "label": doc.get("label", ""),
            "short_form": doc.get("short_form", ""),
            "obo_id": doc.get("obo_id", ""),
            "description": (doc.get("description") or [""])[0],
        })
    return results


def build_crosswalk(
    terms: list[str],
    ontology: str,
    delay: float = 0.2,
) -> dict:
    """Build a crosswalk from text terms to ontology codes using OLS search.

    For each term, searches OLS and picks the best match.
    Returns {lowercase_term: {"code": "...", "label": "...", "confidence": float, "comment": str}}.
    """
    crosswalk = {}
    for term in terms:
        term_stripped = term.strip()
        if not term_stripped:
            continue

        # Strip NOS/NEC suffixes for search
        search_term = term_stripped
        for suffix in [" NOS", ", NOS", " NEC", ", NEC", " Not Otherwise Specified"]:
            if search_term.upper().endswith(suffix.upper()):
                search_term = search_term[: -len(suffix)].strip()
                break

        # Try exact search first
        results = ols_search(ontology, search_term, exact=True, rows=5)
        if not results:
            results = ols_search(ontology, search_term, exact=False, rows=10)

        if results:
            best = results[0]
            code = best["short_form"].replace(f"{ontology.upper()}_", "")
            confidence = 0.95 if best["label"].lower() == search_term.lower() else 0.8
            crosswalk[term_stripped.lower()] = {
                "code": code,
                "label": best["label"],
                "confidence": confidence,
                "comment": f"OLS match: {best['label']} ({best['short_form']})",
            }
        else:
            crosswalk[term_stripped.lower()] = {
                "code": None,
                "label": None,
                "confidence": 0.0,
                "comment": "No OLS match found",
            }

        time.sleep(delay)  # Rate limiting

    return crosswalk


def verify_crosswalk(crosswalk_path: str, ontology: str, delay: float = 0.2) -> dict:
    """Verify a crosswalk by resolving each code via OLS and checking labels."""
    crosswalk = json.loads(Path(crosswalk_path).read_text())
    report = {"verified": 0, "mismatched": 0, "failed": 0, "details": []}

    for term, entry in crosswalk.items():
        code = entry.get("code")
        if not code:
            continue

        resolved = ols_resolve(ontology, code)
        if resolved:
            ols_label = resolved["label"]
            detail = {
                "term": term,
                "code": code,
                "ols_label": ols_label,
                "crosswalk_label": entry.get("label", ""),
                "match": ols_label.lower() == entry.get("label", "").lower(),
            }
            report["details"].append(detail)
            if detail["match"]:
                report["verified"] += 1
            else:
                report["mismatched"] += 1
                print(f"  MISMATCH: {term} -> {code} = '{ols_label}' (expected '{entry.get('label', '')}')")
        else:
            report["failed"] += 1
            print(f"  FAILED: {term} -> {code} (could not resolve)")

        time.sleep(delay)

    return report


def main():
    parser = argparse.ArgumentParser(description="OLS4 ontology lookup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # resolve
    res = subparsers.add_parser("resolve", help="Resolve a code to its label")
    res.add_argument("--ontology", required=True)
    res.add_argument("--code", required=True)

    # search
    srch = subparsers.add_parser("search", help="Search for a term")
    srch.add_argument("--ontology", required=True)
    srch.add_argument("--query", required=True)
    srch.add_argument("--exact", action="store_true")
    srch.add_argument("--rows", type=int, default=10)

    # crosswalk
    xwalk = subparsers.add_parser("crosswalk", help="Build term→code crosswalk")
    xwalk.add_argument("--terms-file", required=True, help="One term per line")
    xwalk.add_argument("--ontology", required=True)
    xwalk.add_argument("--output", required=True)
    xwalk.add_argument("--delay", type=float, default=0.2)

    # verify
    ver = subparsers.add_parser("verify", help="Verify crosswalk codes via OLS")
    ver.add_argument("--crosswalk", required=True)
    ver.add_argument("--ontology", required=True)
    ver.add_argument("--delay", type=float, default=0.2)

    args = parser.parse_args()

    if args.command == "resolve":
        result = ols_resolve(args.ontology, args.code)
        if result:
            print(f"{result['short_form']}: {result['label']}")
            if result["description"]:
                print(f"  {result['description'][:200]}")
        else:
            print(f"Not found: {args.code}")

    elif args.command == "search":
        results = ols_search(args.ontology, args.query, args.exact, args.rows)
        for r in results:
            print(f"{r['short_form']}: {r['label']}")

    elif args.command == "crosswalk":
        terms = Path(args.terms_file).read_text().strip().split("\n")
        crosswalk = build_crosswalk(terms, args.ontology, args.delay)
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(crosswalk, indent=2))
        resolved = sum(1 for v in crosswalk.values() if v["code"])
        print(f"Crosswalk: {resolved}/{len(crosswalk)} terms resolved -> {args.output}")

    elif args.command == "verify":
        report = verify_crosswalk(args.crosswalk, args.ontology, args.delay)
        print(f"Verified: {report['verified']}, Mismatched: {report['mismatched']}, Failed: {report['failed']}")


if __name__ == "__main__":
    main()
