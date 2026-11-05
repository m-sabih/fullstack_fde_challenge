import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google.genai import errors

from pipeline import extract as ex

RFQS = ROOT / "ridgeline-quote-desk-data-pack" / "rfqs"


def line(as_written: str, unit: str | None = "EA") -> ex.ExtractedLine:
    return ex.ExtractedLine(as_written=as_written, quantity=1, unit=unit, part_number=None, description=None)


text, source = ex.load_source(RFQS / "rfq_03_tricounty.xlsx")
assert "Item #\tDesc.\tQty\tUOM\tNotes" in text and text == source
assert '1" brass ball valve FP' in text

lines = [line("- 20 ea 6204-2RS bearings"), line("10 X99 unicorn belts")]
ex.verify_as_written(lines, (RFQS / "rfq_01_email.txt").read_text())
assert lines[0].flags == [] and lines[1].flags == ["not_in_source"]

try:
    line("x", unit="GAL")
    raise AssertionError("invalid unit accepted")
except ValidationError:
    pass

parsed = ex.ExtractedRFQ(customer_name="Mesa Fabrication", lines=[line("RL159429 x 3"), line("- 10 A42 v-belts")])
ex._generate = lambda contents: SimpleNamespace(parsed=parsed)
_, numbered = ex.extract(RFQS / "rfq_01_email.txt")
assert [(n, l.as_written) for n, l in numbered] == [(1, "RL159429 x 3"), (2, "- 10 A42 v-belts")]


def api_down(contents):
    raise errors.APIError(503, {"error": {"message": "unavailable"}})


ex._generate = api_down
_, numbered = ex.extract(RFQS / "rfq_01_email.txt")
assert numbered[0][0] == 1 and numbered[0][1].flags == ["extraction_failed", "needs_review"]

assert ex.resolve_customer("Mesa Fabrication")[0]["customer_id"] == "C1003"
assert ex.resolve_customer("Nobody Inc") == (None, ["customer_not_found"])

print("ok")
