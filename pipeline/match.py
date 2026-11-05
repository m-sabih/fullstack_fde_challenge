import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Literal, NamedTuple

from pipeline.extract import ExtractedLine

DATA = Path(__file__).resolve().parent.parent / "ridgeline-quote-desk-data-pack"

MatchMethod = Literal["ridgeline_part_number", "cross_reference", "description"] | None

STOPWORDS = {"x", "in", "ea", "of", "the", "and", "for", "with", "pc", "pcs"}
# Customer wording -> catalog wording. Tuning knob: specialists' corrections should grow this table.
SYNONYMS = {"sealed": "2rs", "shielded": "zz", "bolt": "screw", "hyd": "hydraulic", "gr": "grade", "brg": "bearing"}
STYLE_CODES = {"2rs", "zz"}
SIZE_WITH_UNIT = re.compile(r"(\d+)(ft|in|mm|hp|gal|ml|oz|lb)|(gr)(\d+)")
NOT_CARRIED_BELOW = 0.5
AMBIGUOUS_MARGIN = 0.05


class Match(NamedTuple):
    part_number: str | None
    method: MatchMethod
    confidence: float
    unit: str | None
    flags: list[str]
    note: str | None


def _read(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


PRODUCTS = {row["part_number"]: row for row in _read("products.csv")}
CROSS_REFERENCE: dict[str, list[dict[str, str]]] = defaultdict(list)
for _row in _read("cross_reference.csv"):
    CROSS_REFERENCE[_row["competitor_part_number"].upper()].append(_row)


def _tokens(text: str) -> tuple[set[str], set[str]]:
    """Split into (spec tokens with a digit, plain words). Dimensions like 20x20x2 stay whole so 16x20x2 can't match."""
    raw = []
    for token in re.findall(r"\d+(?:x\d+)+|\d+/\d+|\d+\.\d+|[a-z0-9]+", text.lower()):
        sized = SIZE_WITH_UNIT.fullmatch(token)
        raw += [g for g in sized.groups() if g] if sized else [token]
    words = {t[:-1] if len(t) > 3 and t.endswith("s") else t for t in raw}
    words |= {SYNONYMS[t] for t in words if t in SYNONYMS}
    specs = {t for t in words if any(c.isdigit() for c in t) or t in STYLE_CODES}
    return specs, words - specs - STOPWORDS


PRODUCT_TOKENS = {pn: _tokens(row["description"]) for pn, row in PRODUCTS.items()}


def _similarity(query: tuple[set[str], set[str]], product: tuple[set[str], set[str]]) -> float:
    """Share of the query's sizes found, minus 0.1 per extra size in the product, scaled by how many query words match.

    Multiplying (not adding) means a product that shares a size but no words (a "10 ml" threadlocker
    for a "10 micron" filter) can't score high.
    """
    q_specs, q_words = query
    p_specs, p_words = product
    word_score = len(q_words & p_words) / len(q_words) if q_words else 0.0
    if not q_specs:
        return 0.8 * word_score
    spec_score = max(0.0, len(q_specs & p_specs) / len(q_specs) - 0.1 * len(p_specs - q_specs))
    return spec_score * (0.4 + 0.6 * word_score)


def _by_description(description: str) -> Match:
    # ponytail: linear token scan over ~200 products; at 40k use BM25/embeddings with a reranker.
    query = _tokens(description)
    ranked = sorted(((_similarity(query, toks), pn) for pn, toks in PRODUCT_TOKENS.items()), reverse=True)
    (best, part_number), (runner_up, runner_pn) = ranked[0], ranked[1]
    if best < NOT_CARRIED_BELOW:
        return Match(None, None, 0.0, None, ["not_carried"], None)
    confidence = 0.85 * best
    if best - runner_up < AMBIGUOUS_MARGIN:
        return Match(part_number, "description", round(confidence * 0.6, 2), None, ["ambiguous_match"], f"close alternative: {runner_pn}")
    return Match(part_number, "description", round(confidence, 2), None, [], None)


def _by_cross_reference(rows: list[dict[str, str]]) -> Match:
    candidates = {row["ridgeline_part_number"] for row in rows}
    row = next((r for r in rows if not r["notes"]), rows[0])
    if len(candidates) > 1:
        return Match(row["ridgeline_part_number"], "cross_reference", 0.4, None, ["ambiguous_cross_reference"],
                     f"cross-reference maps to {', '.join(sorted(candidates))}")
    confidence = 0.95 - (0.15 if row["notes"] else 0) - (0.05 if not row["last_verified"] else 0)
    note = f"cross-reference note: {row['notes']}" if row["notes"] else None
    return Match(row["ridgeline_part_number"], "cross_reference", round(confidence, 2), None, ["cross_reference_note"] if note else [], note)


def match_line(line: ExtractedLine) -> Match:
    part_number = (line.part_number or "").strip().upper()
    if part_number in PRODUCTS:
        match = Match(part_number, "ridgeline_part_number", 0.99, None, [], None)
    elif part_number in CROSS_REFERENCE:
        match = _by_cross_reference(CROSS_REFERENCE[part_number])
    else:
        match = _by_description(line.description or line.as_written)
        if part_number:
            match = match._replace(flags=match.flags + ["part_number_not_found"])
    if match.part_number is None:
        return match._replace(unit=line.unit)

    product = PRODUCTS[match.part_number]
    flags, note, confidence = list(match.flags), match.note, match.confidence
    if product["status"] == "discontinued" and product["replaced_by"]:
        note = "; ".join(filter(None, [note, f"{product['part_number']} discontinued, replaced by {product['replaced_by']}"]))
        product = PRODUCTS[product["replaced_by"]]
        flags.append("discontinued_replaced")
        confidence = min(confidence, 0.7)

    unit = line.unit
    if unit is None:
        unit = product["unit"]
        # Filling BX/CS/PK turns "300 bolts" into 300 boxes; only safe for EA or when the customer used our part number.
        safe = unit == "EA" or match.method == "ridgeline_part_number"
        flags.append("unit_from_catalog" if safe else "unit_unconfirmed")
    elif unit != product["unit"]:
        flags.append("unit_mismatch")
        note = "; ".join(filter(None, [note, f"RFQ unit {unit}, catalog sells by {product['unit']}"]))
    return Match(product["part_number"], match.method, confidence, unit, flags, note)
