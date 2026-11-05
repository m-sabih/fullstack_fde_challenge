"""Score outputs/ against the answer keys. The only code allowed to read answer_key/."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from run import NON_BLOCKING_FLAGS, OUTPUTS, REVIEW_THRESHOLD

ANSWER_KEY = ROOT / "ridgeline-quote-desk-data-pack" / "answer_key"
THRESHOLDS = [round(0.5 + 0.05 * i, 2) for i in range(10)]


def needs_review(line: dict, threshold: float) -> bool:
    return line["confidence"] < threshold or any(f not in NON_BLOCKING_FLAGS for f in line["flags"])


def pairs() -> list[tuple[dict, dict | None]]:
    """(expected, predicted) per answer-key line, joined on line number; None when the pipeline missed the line."""
    result = []
    for key_file in sorted(ANSWER_KEY.glob("*.json")):
        expected = json.loads(key_file.read_text())
        predicted = {line["line"]: line for line in json.loads((OUTPUTS / key_file.name).read_text())["lines"]}
        result += [(line, predicted.get(line["line"])) for line in expected["lines"]]
    return result


def auto_accept_stats(rows: list[tuple[dict, dict | None]], threshold: float) -> dict:
    accepted = [(e, p) for e, p in rows if p and not needs_review(p, threshold)]
    correct = sum(p["ridgeline_part_number"] == e["expected_part_number"] for e, p in accepted)
    return {
        "threshold": threshold,
        "auto_accepted": len(accepted),
        "auto_accept_precision": round(correct / len(accepted), 3) if accepted else None,
        "review_rate": round(1 - len(accepted) / len(rows), 3),
    }


def evaluate() -> dict:
    rows = pairs()
    found = [(e, p) for e, p in rows if p]
    extraction_correct = sum(p["quantity"] == e["quantity"] and p["unit"] == e["unit"] for e, p in found)
    predicted_parts = [(e, p) for e, p in found if p["ridgeline_part_number"]]
    expected_parts = [(e, p) for e, p in rows if e["expected_part_number"]]
    no_part_expected = [(e, p) for e, p in rows if not e["expected_part_number"]]

    sweep = [auto_accept_stats(rows, t) for t in THRESHOLDS]
    safe = [s["threshold"] for s in sweep if s["auto_accept_precision"] in (1.0, None)]
    return {
        "threshold": REVIEW_THRESHOLD,
        "extraction_accuracy": round(extraction_correct / len(rows), 3),
        "match_precision": round(sum(p["ridgeline_part_number"] == e["expected_part_number"] for e, p in predicted_parts) / len(predicted_parts), 3),
        "match_recall": round(sum(p and p["ridgeline_part_number"] == e["expected_part_number"] for e, p in expected_parts) / len(expected_parts), 3),
        "additional_metrics": {
            "lines_scored": len(rows),
            "lines_missing_from_output": len(rows) - len(found),
            "quantity_accuracy": round(sum(p["quantity"] == e["quantity"] for e, p in found) / len(rows), 3),
            "unit_accuracy": round(sum(p["unit"] == e["unit"] for e, p in found) / len(rows), 3),
            "no_match_lines_flagged_not_guessed": f"{sum(bool(p) and p['ridgeline_part_number'] is None and p['needs_review'] for e, p in no_part_expected)}/{len(no_part_expected)}",
            "match_accuracy_by_method": {
                method: f"{sum(p['ridgeline_part_number'] == e['expected_part_number'] for e, p in group)}/{len(group)}"
                for method in ("ridgeline_part_number", "cross_reference", "description")
                if (group := [(e, p) for e, p in found if e["match_method"] == method])
            },
            "at_threshold": auto_accept_stats(rows, REVIEW_THRESHOLD),
            "lowest_threshold_with_no_wrong_auto_accepts": min(safe) if safe else None,
            "threshold_sweep": sweep,
        },
    }


if __name__ == "__main__":
    results = evaluate()
    (ROOT / "evaluation" / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    for name in ("threshold", "extraction_accuracy", "match_precision", "match_recall"):
        print(f"{name:22} {results[name]}")
    extra = results["additional_metrics"]
    for name in ("quantity_accuracy", "unit_accuracy", "no_match_lines_flagged_not_guessed", "match_accuracy_by_method", "at_threshold"):
        print(f"{name:22} {extra[name]}")
    print("\nthreshold  auto_accepted  auto_accept_precision  review_rate")
    for s in extra["threshold_sweep"]:
        print(f"{s['threshold']:<10} {s['auto_accepted']:<14} {s['auto_accept_precision']!s:<22} {s['review_rate']}")
    print(f"\nlowest threshold with no wrong auto-accepts: {extra['lowest_threshold_with_no_wrong_auto_accepts']}")
