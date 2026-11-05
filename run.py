import json
import sys
from pathlib import Path

from pipeline.extract import extract, resolve_customer
from pipeline.match import match_line

ROOT = Path(__file__).resolve().parent
RFQS = ROOT / "ridgeline-quote-desk-data-pack" / "rfqs"
OUTPUTS = ROOT / "outputs"
REVIEW_THRESHOLD = 0.8
NON_BLOCKING_FLAGS = {"unit_from_catalog"}


def build_draft(path: Path) -> dict:
    rfq, numbered = extract(path)
    customer, customer_flags = resolve_customer(rfq.customer_name)
    lines = []
    for number, line in numbered:
        if "extraction_failed" in line.flags:
            part_number, method, confidence, unit, match_flags, match_note = None, None, 0.0, None, ["stub"], None
        else:
            part_number, method, confidence, unit, match_flags, match_note = match_line(line)
        flags = [f for f in line.flags if f != "needs_review" and not (f == "missing_unit" and unit)] + match_flags
        lines.append({
            "line": number,
            "as_written": line.as_written,
            "quantity": line.quantity,
            "unit": unit,
            "ridgeline_part_number": part_number,
            "match_method": method,
            "confidence": confidence,
            "needs_review": "needs_review" in line.flags or confidence < REVIEW_THRESHOLD
                            or any(f not in NON_BLOCKING_FLAGS for f in flags),
            "flags": flags,
            "note": "; ".join(filter(None, [line.note, match_note])) or None,
        })
    return {
        "rfq_id": path.stem,
        "customer_id": customer["customer_id"] if customer else None,
        "customer_name": rfq.customer_name,
        "flags": customer_flags,
        "lines": lines,
        "non_item_rows": rfq.non_item_rows,
    }


if __name__ == "__main__":
    OUTPUTS.mkdir(exist_ok=True)
    for path in [Path(p) for p in sys.argv[1:]] or sorted(RFQS.glob("rfq_*")):
        draft = build_draft(path)
        (OUTPUTS / f"{path.stem}.json").write_text(json.dumps(draft, indent=2) + "\n")
        flagged = sum(line["needs_review"] for line in draft["lines"])
        print(f"{path.stem}: {len(draft['lines'])} lines, {flagged} need review")
