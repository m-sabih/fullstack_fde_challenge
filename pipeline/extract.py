import csv
import difflib
import os
import sys
from functools import cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from openpyxl import load_workbook
from pydantic import BaseModel
from pypdf import PdfReader
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

CUSTOMERS_CSV = Path(__file__).resolve().parent.parent / "ridgeline-quote-desk-data-pack" / "customers.csv"
FILE_MIME_TYPES = {".pdf": "application/pdf", ".png": "image/png"}

PROMPT = """Extract every requested item from this RFQ.
Rules:
- customer_name is the company requesting the quote, never Ridgeline Industrial Supply.
- One line per requested item, in the order it appears in the RFQ.
- Copy as_written exactly from the source, character for character.
- part_number is only a catalog code: a Ridgeline number (RL followed by digits) or a supplier/competitor code (e.g. APX-VB-B55, NF-220420, MRD984642). Sizes and specs such as 6204-2RS, A42 or 1/2-13 are not part numbers; put them in description and leave part_number null.
- description is the full item text without quantity and unit, keeping every size, spec, material, grade and style word (e.g. "6204-2RS sealed ball bearing", "1/2-13 x 2 in grade 8 hex bolt"). If a line refers to another line (e.g. "same as above but 1/2\""), write out the complete resulting description.
- unit is the unit the RFQ states, as EA (each), BX (box), PK (pack), CS (case), RL (roll), PR (pair) or FT (foot). Never convert between units. If the stated unit is none of these, leave unit null, add the flag "unknown_unit" and put the stated unit in note.
- In forwarded chains, apply the later edits and record each change in note.
- Never guess a quantity or unit. If it is not explicit, leave it null and add the flag "missing_quantity" or "missing_unit".
- If a line refers to a previous order (e.g. "same as last order"), add the flag "needs_human_review".
- non_item_rows holds only rows inside the item list or table that are not items (shipping, delivery, totals, comments). Ignore greetings, signatures and email headers.
- Never output prices."""

Unit = Literal["EA", "BX", "PK", "CS", "RL", "PR", "FT"]


class ExtractedLine(BaseModel):
    as_written: str
    quantity: int | None
    unit: Unit | None
    part_number: str | None
    description: str | None
    flags: list[str] = []
    note: str | None = None


class ExtractedRFQ(BaseModel):
    customer_name: str | None
    lines: list[ExtractedLine]
    non_item_rows: list[str] = []


def load_source(path: Path) -> tuple[str | types.Part, str | None]:
    """Return (content for the model, source text for the as_written check or None if unreadable)."""
    suffix = path.suffix.lower()
    if suffix == ".txt":
        text = path.read_text(encoding="utf-8")
        return text, text
    if suffix == ".xlsx":
        # Tab-joined, not csv.writer: csv quoting doubles the inch mark in 1" and breaks the verbatim check.
        rows = (row for sheet in load_workbook(path, data_only=True).worksheets for row in sheet.iter_rows(values_only=True))
        text = "\n".join("\t".join("" if v is None else str(v) for v in row) for row in rows if any(v is not None for v in row))
        return text, text
    if suffix in FILE_MIME_TYPES:
        part = types.Part.from_bytes(data=path.read_bytes(), mime_type=FILE_MIME_TYPES[suffix])
        text = "\n".join(page.extract_text() for page in PdfReader(path).pages) if suffix == ".pdf" else None
        return part, text
    raise ValueError(f"Unsupported RFQ format: {path.suffix}")


@cache
def _client() -> genai.Client:
    # Must outlive the request: an unreferenced Client is garbage-collected and closes its HTTP connection mid-call.
    return genai.Client()


@retry(retry=retry_if_exception_type(errors.APIError), stop=stop_after_attempt(3), wait=wait_exponential(max=10), reraise=True)
def _generate(contents: list[str | types.Part]) -> types.GenerateContentResponse:
    return _client().models.generate_content(
        model=os.environ["GEMINI_MODEL"],
        contents=contents,
        config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json", response_schema=ExtractedRFQ),
    )


def _failed(reason: str) -> tuple[ExtractedRFQ, list[tuple[int, ExtractedLine]]]:
    line = ExtractedLine(
        as_written="entire RFQ", quantity=None, unit=None, part_number=None, description=None,
        flags=["extraction_failed", "needs_review"], note=reason,
    )
    return ExtractedRFQ(customer_name=None, lines=[line]), [(1, line)]


def _normalize(text: str) -> str:
    return "".join(text.split()).lower()


def verify_as_written(lines: list[ExtractedLine], source_text: str) -> None:
    source = _normalize(source_text)
    for line in lines:
        written = _normalize(line.as_written)
        if not written or written not in source:
            line.flags.append("not_in_source")


def resolve_customer(name: str | None) -> tuple[dict[str, str] | None, list[str]]:
    with CUSTOMERS_CSV.open(newline="", encoding="utf-8") as f:
        customers = {row["name"].lower(): row for row in csv.DictReader(f)}
    match = difflib.get_close_matches((name or "").lower(), customers, n=1)
    return (customers[match[0]], []) if match else (None, ["customer_not_found"])


def extract(path: str | Path) -> tuple[ExtractedRFQ, list[tuple[int, ExtractedLine]]]:
    """Extract an RFQ. Line numbers come from enumerate, never from the model, so a skipped number can't misalign lines."""
    path = Path(path)
    content, source_text = load_source(path)
    try:
        rfq = _generate([PROMPT, content]).parsed
    except errors.APIError as exc:
        return _failed(f"Gemini API error: {exc}")
    if not isinstance(rfq, ExtractedRFQ):
        return _failed("Gemini response did not parse as ExtractedRFQ")
    if source_text is not None:
        verify_as_written(rfq.lines, source_text)
    if path.suffix.lower() == ".png":
        for line in rfq.lines:
            line.flags += ["source_photo", "needs_review"]
    return rfq, list(enumerate(rfq.lines, start=1))


if __name__ == "__main__":
    rfq, _ = extract(sys.argv[1])
    print(rfq.model_dump_json(indent=2))
    print(resolve_customer(rfq.customer_name))
