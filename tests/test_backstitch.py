import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import backstitch as bs  # noqa: E402

EXAMPLE = ROOT / "examples" / "little-house.bst"

BASE = """\
title: Test
count: 10
strands: 2
waste: 0
margin: 0
skein_yd: 8.7
strands_per_skein: 6
rate: 60

[palette]
X 310 Black #000000
O 321 Red

[chart]
XX.
.OX
"""


def parse_ok(text=BASE):
    design, issues = bs.parse_design(text)
    assert issues == []
    return design


def messages(text):
    _, issues = bs.parse_design(text)
    return [(i.line, i.col, i.message) for i in issues]


def test_parses_settings_palette_and_chart():
    design = parse_ok()
    assert design.title == "Test"
    assert design.count == 10
    assert design.strands == 2
    assert design.palette["X"].code == "310"
    assert design.palette["X"].hex == "#000000"
    assert design.palette["O"].name == "Red"
    assert design.rows == ["XX.", ".OX"]
    assert (design.width, design.height) == (3, 2)


def test_bad_symbol_reports_line_and_column():
    text = BASE.replace(".OX", ".OZ")
    assert (16, 3, "symbol 'Z' is not in the palette") in messages(text)


def test_ragged_row_reports_its_line():
    text = BASE.replace(".OX", ".OXX")
    msgs = messages(text)
    assert any(line == 16 and "row has 4 cells, expected 3" in msg for line, _, msg in msgs)


def test_duplicate_palette_symbol_is_an_error():
    text = BASE.replace("O 321 Red", "X 321 Red")
    assert any("duplicate palette symbol 'X'" in msg for _, _, msg in messages(text))


def test_unknown_section_and_bad_setting_are_reported():
    text = BASE.replace("[chart]", "[charts]").replace("strands: 2", "strands: 9")
    msgs = [msg for _, _, msg in messages(text)]
    assert any("unknown section" in msg for msg in msgs)
    assert any("strands must be between 1 and 6" in msg for msg in msgs)


def test_backstitch_outside_chart_is_rejected():
    text = BASE + "\n[backstitch]\nX 0,0 9,9\n"
    assert any("outside the 3x2 chart" in msg for _, _, msg in messages(text))


def test_stitch_counts_skip_empty_cells():
    design = parse_ok()
    counts = bs.stitch_counts(design)
    assert counts["X"] == 3
    assert counts["O"] == 1


def test_backstitch_length_uses_euclidean_distance():
    text = BASE + "\n[backstitch]\nX 0,0 1,1 1,2\n"
    design = parse_ok(text)
    lengths = bs.backstitch_cells(design)
    assert lengths["X"] == pytest.approx(math.sqrt(2) + 1)


def test_skein_count_matches_hand_calculation():
    # 10 count: one cell is 0.1 in. 10000 cross stitches on 2 strands.
    design = parse_ok(BASE)
    design.rows = ["X" * 100] * 100
    plan = {m.symbol: m for m in bs.materials(design)}
    per_strand_yd = 10000 * bs.CROSS_FACTOR * 0.1 / 36
    assert plan["X"].strand_yd == pytest.approx(per_strand_yd)
    needed_yd = per_strand_yd * 2
    assert plan["X"].skeins == math.ceil(needed_yd / (8.7 * 6))


def test_waste_increases_thread_length():
    design = parse_ok()
    before = bs.materials(design)[0].strand_yd
    design.waste = 50
    assert bs.materials(design)[0].strand_yd == pytest.approx(before * 1.5)


def test_fabric_size_includes_margins():
    design = parse_ok()
    design.rows = ["X" * 140] * 70
    design.margin = 3
    width, height = bs.fabric_size(design)
    assert width == pytest.approx(14 + 6)
    assert height == pytest.approx(7 + 6)


def test_stitch_hours_uses_rate():
    design = parse_ok()
    design.rate = 4
    # Fixture has 4 cross stitches and no backstitch: 4 stitches at 4 per hour.
    assert bs.stitch_hours(design) == pytest.approx(1.0)


def test_parse_ranges_accepts_lists_and_rejects_bad_input():
    assert bs.parse_ranges("1-3,5", 6) == {1, 2, 3, 5}
    assert bs.parse_ranges("", 6) == set()
    with pytest.raises(ValueError, match="outside"):
        bs.parse_ranges("7", 6)
    with pytest.raises(ValueError, match="backwards"):
        bs.parse_ranges("4-2", 6)
    with pytest.raises(ValueError, match="bad row range"):
        bs.parse_ranges("a-b", 6)


def test_progress_counts_done_rows_per_colour():
    design = parse_ok()
    done, total, per_symbol = bs.progress(design, {1})
    assert (done, total) == (2, 4)
    assert per_symbol == {"X": (2, 3), "O": (0, 1)}


def test_text_chart_has_row_numbers_and_legend():
    text = bs.render_text(parse_ok())
    assert "1 XX." in text
    assert "310" in text and "Black" in text


def test_svg_is_well_formed_and_draws_every_stitch():
    design = parse_ok()
    svg = bs.render_svg(design)
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    cells = [r for r in root.iter(f"{ns}rect") if r.get("width") == "12"]
    assert len(cells) == 4  # background rect is the only other rect


def test_svg_escapes_title():
    design = parse_ok()
    design.title = "<b>&"
    ET.fromstring(bs.render_svg(design))


def test_example_file_is_clean_and_consistent():
    design, issues = bs.load_design(EXAMPLE)
    assert issues == []
    assert bs.lint_warnings(design) == []
    total = sum(bs.stitch_counts(design).values())
    assert total == sum(1 for row in design.rows for ch in row if ch != ".")


def test_cli_check_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.bst"
    good.write_text(BASE, encoding="utf-8")
    bad = tmp_path / "bad.bst"
    bad.write_text(BASE.replace(".OX", ".OZ"), encoding="utf-8")
    assert bs.main(["check", str(good)]) == 0
    assert bs.main(["check", str(bad)]) == 1
    assert f"{bad}:16:3: symbol 'Z'" in capsys.readouterr().err


def test_cli_progress_rejects_out_of_range_rows(tmp_path):
    path = tmp_path / "p.bst"
    path.write_text(BASE, encoding="utf-8")
    assert bs.main(["progress", str(path), "--done", "9"]) == 1


def test_cli_svg_writes_file(tmp_path):
    src = tmp_path / "s.bst"
    src.write_text(BASE, encoding="utf-8")
    out = tmp_path / "s.svg"
    assert bs.main(["svg", str(src), "-o", str(out)]) == 0
    ET.parse(out)
