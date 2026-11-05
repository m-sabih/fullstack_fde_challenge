import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.extract import ExtractedLine
from pipeline.match import PRODUCTS, match_line


def line(part_number: str | None = None, description: str | None = None, unit: str | None = "EA") -> ExtractedLine:
    return ExtractedLine(as_written="x", quantity=1, unit=unit, part_number=part_number, description=description)


m = match_line(line("RL159429", unit=None))
assert (m.part_number, m.method, m.confidence, m.unit, m.flags) == ("RL159429", "ridgeline_part_number", 0.99, "BX", ["unit_from_catalog"])

m = match_line(line("APX-HF-JIC08-90"))
assert m.part_number == "RL120374" and "discontinued_replaced" in m.flags and m.confidence <= 0.7

m = match_line(line("NF-610338"))
assert m.flags[0] == "ambiguous_cross_reference" and m.confidence == 0.4

m = match_line(line("NF-118204"))
assert m.part_number == "RL124050" and m.confidence == 0.8 and "check thickness" in m.note

m = match_line(line(description="6204-2RS sealed ball bearing"))
assert m.part_number == "RL171482" and m.method == "description"

m = match_line(line(description="6205 sealed bearing"))
assert "6205-2RS" in PRODUCTS[m.part_number]["description"]

m = match_line(line(description="20x20x2 pleated filter MERV 8", unit="CS"))
assert m.part_number == "RL149009" and m.flags == []

assert match_line(line(description="hydraulic return element 10 micron cellulose")).part_number == "RL194646"
assert match_line(line(description="#40 chain 10ft", unit="BX")).part_number == "RL159429"
assert match_line(line(description="3/8 x 1 1/2 gr5 bolts", unit="BX")).part_number == "RL142504"
assert match_line(line(description="3/8 x 1 1/2 gr5 bolts", unit=None)).flags == ["unit_unconfirmed"]
assert match_line(line(description="6205 2RS brgs")).part_number == "RL104165"
assert match_line(line(description="1/2 in brass ball valve full port")).part_number == "RL172063"

m = match_line(line(description="nitrile gloves L", unit=None))
assert "ambiguous_match" in m.flags

m = match_line(line("NF-778812", description="forklift tire 18x7-8"))
assert m.part_number is None and m.flags == ["not_carried", "part_number_not_found"]

m = match_line(line(description="1/2-13 x 2 in grade 8 hex bolt", unit="BX"))
assert m.part_number == "RL165435" and m.flags == []
assert "unit_mismatch" in match_line(line(description="1/2-13 x 2 in grade 8 hex bolt", unit="EA")).flags

print("ok")
