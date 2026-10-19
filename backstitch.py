#!/usr/bin/env python3
"""Backstitch: offline cross-stitch pattern planner.

Reads one plain-text chart file and reports stitch counts, floss and skein
needs, fabric size, stitching time and progress. Standard library only.
"""

from __future__ import annotations

import argparse
import html
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

EMPTY = "."
SECTIONS = ("palette", "chart", "backstitch")
META_KEYS = ("title", "count", "strands", "waste", "margin",
             "skein_yd", "strands_per_skein", "rate")
INT_KEYS = ("strands", "strands_per_skein")

# Thread used by one cross stitch, per strand, as a multiple of the cell side:
# two diagonals of sqrt(2) each plus about 60% for wraps and carrying across.
# This is an estimate; tune it against a real sample if you need precision.
CROSS_FACTOR = 2 * math.sqrt(2) * 1.6
# Thread per cell of backstitch length, per strand (loops and returns).
BACK_FACTOR = 1.2
HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
POINT_RE = re.compile(r"(-?\d+),(-?\d+)")


@dataclass
class Issue:
    line: int  # 0 means the problem is about the whole file
    message: str
    col: int | None = None

    def format(self, label: str) -> str:
        where = label
        if self.line:
            where += f":{self.line}"
            if self.col is not None:
                where += f":{self.col}"
        return f"{where}: {self.message}"


@dataclass
class Floss:
    symbol: str
    code: str
    name: str
    hex: str | None = None


@dataclass
class Backstitch:
    line: int
    symbol: str
    points: list[tuple[int, int]]


@dataclass
class Design:
    title: str = "Untitled"
    count: float = 14.0
    strands: int = 2
    waste: float = 15.0
    margin: float = 3.0
    skein_yd: float = 8.7
    strands_per_skein: int = 6
    rate: float = 60.0
    palette: dict[str, Floss] = field(default_factory=dict)
    rows: list[str] = field(default_factory=list)
    backstitches: list[Backstitch] = field(default_factory=list)

    @property
    def width(self) -> int:
        return len(self.rows[0]) if self.rows else 0

    @property
    def height(self) -> int:
        return len(self.rows)


@dataclass
class Material:
    symbol: str
    code: str
    name: str
    stitches: int
    back_cells: float
    strand_yd: float  # length of each strand, including waste
    skeins: int


def _setting_error(key: str, num: float) -> str | None:
    if key in INT_KEYS and num != int(num):
        return f"{key} must be a whole number"
    if key == "strands" and not 1 <= num <= 6:
        return "strands must be between 1 and 6"
    if key == "strands_per_skein" and num < 1:
        return "strands_per_skein must be at least 1"
    if key in ("count", "rate", "skein_yd") and num <= 0:
        return f"{key} must be greater than zero"
    if key in ("waste", "margin") and num < 0:
        return f"{key} cannot be negative"
    return None


def parse_design(text: str) -> tuple[Design, list[Issue]]:
    """Parse a chart file. Returns the design and every problem found."""
    design = Design()
    issues: list[Issue] = []
    section = "meta"
    seen_meta: set[str] = set()
    seen_palette_chars: set[str] = set()
    chart_rows: list[tuple[int, str]] = []
    backstitch_lines: list[tuple[int, str, list[tuple[int, int]]]] = []

    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("["):
            name = stripped.strip("[]").strip().lower()
            if stripped.endswith("]") and name in SECTIONS:
                section = name
            else:
                issues.append(Issue(lineno, f"unknown section {stripped!r}"))
                section = None
            continue

        if section == "meta":
            key, sep, value = stripped.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if not sep or key not in META_KEYS:
                issues.append(Issue(lineno, f"expected a 'key: value' setting, got {stripped!r}"))
                continue
            if key in seen_meta:
                issues.append(Issue(lineno, f"duplicate setting {key!r}"))
                continue
            seen_meta.add(key)
            if key == "title":
                design.title = value or "Untitled"
                continue
            try:
                num = float(value)
            except ValueError:
                num = math.nan
            if not math.isfinite(num):
                issues.append(Issue(lineno, f"{key} must be a finite number, got {value!r}"))
                continue
            problem = _setting_error(key, num)
            if problem:
                issues.append(Issue(lineno, problem))
                continue
            setattr(design, key, int(num) if key in INT_KEYS else num)

        elif section == "palette":
            parts = stripped.split(None, 2)
            if len(parts) < 2:
                issues.append(Issue(lineno, "palette entry needs SYMBOL CODE [NAME] [#HEX]"))
                continue
            symbol, code = parts[0], parts[1]
            rest = parts[2] if len(parts) > 2 else ""
            if len(symbol) != 1 or symbol in (EMPTY, "#", "["):
                issues.append(Issue(lineno, f"symbol {symbol!r} must be one character other than '.', '#' or '['"))
                continue
            if symbol in design.palette:
                issues.append(Issue(lineno, f"duplicate palette symbol {symbol!r}"))
                continue
            hex_value = None
            words = rest.split()
            if words and HEX_RE.fullmatch(words[-1]):
                hex_value = words.pop()
            name = " ".join(words) or code
            design.palette[symbol] = Floss(symbol, code, name, hex_value)
            seen_palette_chars.add(symbol)

        elif section == "chart":
            if len(stripped.split()) != 1:
                issues.append(Issue(lineno, "chart rows must contain one symbol per cell, with no spaces"))
                continue
            chart_rows.append((lineno, stripped))

        elif section == "backstitch":
            parts = stripped.split()
            if len(parts) < 3:
                issues.append(Issue(lineno, "backstitch needs SYMBOL and at least two x,y points"))
                continue
            points: list[tuple[int, int]] = []
            bad = None
            for token in parts[1:]:
                match = POINT_RE.fullmatch(token)
                if not match:
                    bad = token
                    break
                points.append((int(match.group(1)), int(match.group(2))))
            if bad is not None:
                issues.append(Issue(lineno, f"bad point {bad!r}, expected x,y"))
                continue
            backstitch_lines.append((lineno, parts[0], points))

        else:
            # Section was unknown; its lines were already reported.
            continue

    if not design.palette:
        issues.append(Issue(0, "palette is missing or empty"))

    if not chart_rows:
        issues.append(Issue(0, "chart is missing or empty"))
    else:
        width = len(chart_rows[0][1])
        for lineno, row in chart_rows:
            if len(row) != width:
                issues.append(Issue(lineno, f"row has {len(row)} cells, expected {width}"))
            for col, ch in enumerate(row, start=1):
                if ch != EMPTY and ch not in design.palette:
                    issues.append(Issue(lineno, f"symbol {ch!r} is not in the palette", col))
        design.rows = [row for _, row in chart_rows]

    for lineno, symbol, points in backstitch_lines:
        if symbol not in design.palette:
            issues.append(Issue(lineno, f"backstitch symbol {symbol!r} is not in the palette"))
            continue
        bad_point = next(
            ((x, y) for x, y in points
             if not (0 <= x <= design.width and 0 <= y <= design.height)),
            None,
        )
        if bad_point is not None:
            x, y = bad_point
            issues.append(Issue(lineno, f"point {x},{y} is outside the {design.width}x{design.height} chart"))
            continue
        design.backstitches.append(Backstitch(lineno, symbol, points))

    return design, issues


def load_design(path: Path) -> tuple[Design, list[Issue]]:
    return parse_design(path.read_text(encoding="utf-8"))


def stitch_counts(design: Design) -> Counter:
    """Full cross stitches per palette symbol (zero for unused symbols)."""
    counts: Counter = Counter({sym: 0 for sym in design.palette})
    for row in design.rows:
        counts.update(ch for ch in row if ch != EMPTY)
    return counts


def backstitch_cells(design: Design) -> Counter:
    """Backstitch length per palette symbol, in cell-side units."""
    lengths: Counter = Counter({sym: 0.0 for sym in design.palette})
    for stitch in design.backstitches:
        for (x1, y1), (x2, y2) in zip(stitch.points, stitch.points[1:]):
            lengths[stitch.symbol] += math.hypot(x2 - x1, y2 - y1)
    return lengths


def materials(design: Design) -> list[Material]:
    """Thread length and skeins for each palette symbol that is used."""
    stitches = stitch_counts(design)
    backs = backstitch_cells(design)
    side_in = 1.0 / design.count
    waste = 1 + design.waste / 100
    plan = []
    for sym, floss in design.palette.items():
        if not stitches[sym] and not backs[sym]:
            continue
        strand_in = (stitches[sym] * CROSS_FACTOR + backs[sym] * BACK_FACTOR) * side_in * waste
        strand_yd = strand_in / 36
        # Each skein holds strands_per_skein strands of skein_yd each. Every
        # working thread takes `strands` strands of the same length.
        needed_yd = strand_yd * design.strands
        skeins = math.ceil(needed_yd / (design.skein_yd * design.strands_per_skein) - 1e-9)
        plan.append(Material(sym, floss.code, floss.name, stitches[sym],
                             backs[sym], strand_yd, skeins))
    return plan


def fabric_size(design: Design) -> tuple[float, float]:
    """Finished fabric size in inches, including margins on every side."""
    width = design.width / design.count + 2 * design.margin
    height = design.height / design.count + 2 * design.margin
    return width, height


def stitch_hours(design: Design) -> float:
    total = sum(stitch_counts(design).values())
    total += sum(backstitch_cells(design).values())
    return total / design.rate


def parse_ranges(text: str, max_row: int) -> set[int]:
    """Parse '1-10,12' into a set of 1-based row numbers."""
    rows: set[int] = set()
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        low, _, high = token.partition("-")
        try:
            start = int(low)
            end = int(high) if high else start
        except ValueError:
            raise ValueError(f"bad row range {token!r}") from None
        if start > end:
            raise ValueError(f"row range {token!r} runs backwards")
        if start < 1 or end > max_row:
            raise ValueError(f"row range {token!r} is outside 1-{max_row}")
        rows.update(range(start, end + 1))
    return rows


def progress(design: Design, done_rows: set[int]) -> tuple[int, int, dict[str, tuple[int, int]]]:
    """Done and total cross stitches, plus per-symbol (done, total)."""
    total = Counter()
    done = Counter()
    for y, row in enumerate(design.rows, start=1):
        for ch in row:
            if ch == EMPTY:
                continue
            total[ch] += 1
            if y in done_rows:
                done[ch] += 1
    per_symbol = {sym: (done[sym], total[sym]) for sym in design.palette if total[sym]}
    return sum(done.values()), sum(total.values()), per_symbol


def render_text(design: Design) -> str:
    if not design.rows:
        return ""
    label_w = len(str(design.height))
    ruler = "".join(str(((x + 1) // 10) % 10) if (x + 1) % 10 == 0 else " "
                    for x in range(design.width))
    lines = [" " * (label_w + 1) + ruler]
    for y, row in enumerate(design.rows, start=1):
        lines.append(f"{y:>{label_w}} {row}")
    lines.append("")
    for sym, floss in design.palette.items():
        lines.append(f"  {sym}  {floss.code:<8} {floss.name}")
    return "\n".join(lines)


def _text_colour(hex_value: str) -> str:
    r, g, b = (int(hex_value[i:i + 2], 16) for i in (1, 3, 5))
    return "#000000" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "#ffffff"


def render_svg(design: Design, cell: int = 12) -> str:
    width_px = design.width * cell
    height_px = design.height * cell
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width_px}" height="{height_px}" '
        f'viewBox="0 0 {width_px} {height_px}">',
        f"<title>{html.escape(design.title)}</title>",
        f'<rect width="{width_px}" height="{height_px}" fill="#ffffff"/>',
    ]
    for y, row in enumerate(design.rows):
        for x, ch in enumerate(row):
            if ch == EMPTY:
                continue
            floss = design.palette[ch]
            fill = floss.hex or "#cccccc"
            text_fill = _text_colour(fill) if floss.hex else "#000000"
            px, py = x * cell, y * cell
            parts.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" fill="{fill}"/>')
            parts.append(
                f'<text x="{px + cell / 2}" y="{py + cell / 2}" font-family="monospace" '
                f'font-size="{cell * 0.7:.1f}" text-anchor="middle" dominant-baseline="central" '
                f'fill="{text_fill}">{html.escape(ch)}</text>'
            )
    for x in range(10, design.width, 10):
        parts.append(f'<line x1="{x * cell}" y1="0" x2="{x * cell}" y2="{height_px}" stroke="#999999" stroke-width="0.5"/>')
    for y in range(10, design.height, 10):
        parts.append(f'<line x1="0" y1="{y * cell}" x2="{width_px}" y2="{y * cell}" stroke="#999999" stroke-width="0.5"/>')
    for stitch in design.backstitches:
        floss = design.palette[stitch.symbol]
        colour = floss.hex or "#000000"
        for (x1, y1), (x2, y2) in zip(stitch.points, stitch.points[1:]):
            parts.append(
                f'<line x1="{x1 * cell}" y1="{y1 * cell}" x2="{x2 * cell}" y2="{y2 * cell}" '
                f'stroke="{colour}" stroke-width="{max(1.0, cell / 6):.1f}" stroke-linecap="round"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def lint_warnings(design: Design) -> list[str]:
    warnings = []
    used = {sym for sym, n in stitch_counts(design).items() if n}
    used |= {b.symbol for b in design.backstitches}
    for sym, floss in design.palette.items():
        if sym not in used:
            warnings.append(f"palette symbol {sym!r} ({floss.code}) is never used")
    if design.rows and not sum(stitch_counts(design).values()):
        warnings.append("chart has no cross stitches")
    return warnings


def _fail_on_issues(path: Path, issues: list[Issue]) -> bool:
    for issue in issues:
        print(issue.format(str(path)), file=sys.stderr)
    return bool(issues)


def cmd_check(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        print(f"{len(issues)} error(s) found", file=sys.stderr)
        return 1
    warnings = lint_warnings(design)
    for warning in warnings:
        print(f"{path}: warning: {warning}")
    if args.strict and warnings:
        return 1
    print(f"{path}: OK ({design.width}x{design.height}, {len(design.palette)} colours)")
    return 0


def cmd_summary(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        return 1
    counts = stitch_counts(design)
    total = sum(counts.values())
    print(f"{design.title}")
    print(f"  chart:      {design.width} x {design.height} stitches")
    print(f"  cross stitches: {total}")
    print(f"  backstitch segments: {len(design.backstitches)}")
    print("  colours:")
    for sym, floss in design.palette.items():
        share = (100 * counts[sym] / total) if total else 0
        print(f"    {sym}  {floss.code:<8} {floss.name:<20} {counts[sym]:>6}  {share:5.1f}%")
    return 0


def cmd_materials(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        return 1
    width, height = fabric_size(design)
    print(f"{design.title}")
    print(f"  fabric: {design.count:g}-count, cut at least {width:.1f} x {height:.1f} in")
    print(f"  stitch time: about {stitch_hours(design):.1f} h at {design.rate:g}/h")
    print(f"  {'SYM':<4}{'CODE':<9}{'NAME':<18}{'STITCHES':>9}{'BACK in':>9}{'STRAND yd':>11}{'SKEINS':>8}")
    total_skeins = 0
    for m in materials(design):
        back_in = m.back_cells / design.count
        total_skeins += m.skeins
        print(f"  {m.symbol:<4}{m.code:<9}{m.name[:17]:<18}{m.stitches:>9}"
              f"{back_in:>9.1f}{m.strand_yd:>11.2f}{m.skeins:>8}")
    print(f"  total skeins: {total_skeins}  (waste {design.waste:g}%, "
          f"{design.strands} strands, {design.strands_per_skein} strands per skein)")
    return 0


def cmd_chart(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        return 1
    print(render_text(design))
    return 0


def cmd_svg(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        return 1
    svg = render_svg(design, cell=args.cell)
    if args.output:
        Path(args.output).write_text(svg, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(svg)
    return 0


def cmd_progress(args) -> int:
    path = Path(args.file)
    design, issues = load_design(path)
    if _fail_on_issues(path, issues):
        return 1
    try:
        done_rows = parse_ranges(args.done, design.height)
    except ValueError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1
    done, total, per_symbol = progress(design, done_rows)
    percent = 100 * done / total if total else 0
    print(f"{design.title}: {done} of {total} stitches done ({percent:.1f}%)")
    print(f"rows complete: {len(done_rows)} of {design.height}")
    for sym, (d, t) in per_symbol.items():
        floss = design.palette[sym]
        print(f"  {sym}  {floss.code:<8} {floss.name:<20} {d:>6} / {t:<6}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backstitch", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="lint a chart file; exit 1 on errors")
    p.add_argument("file")
    p.add_argument("--strict", action="store_true", help="treat warnings as errors")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("summary", help="stitch counts per colour")
    p.add_argument("file")
    p.set_defaults(func=cmd_summary)

    p = sub.add_parser("materials", help="floss lengths, skeins, fabric and time")
    p.add_argument("file")
    p.set_defaults(func=cmd_materials)

    p = sub.add_parser("chart", help="print the chart as text")
    p.add_argument("file")
    p.set_defaults(func=cmd_chart)

    p = sub.add_parser("svg", help="write an SVG chart with backstitch lines")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="output path (default: stdout)")
    p.add_argument("--cell", type=int, default=12, help="cell size in pixels")
    p.set_defaults(func=cmd_svg)

    p = sub.add_parser("progress", help="report stitched rows and percent complete")
    p.add_argument("file")
    p.add_argument("--done", default="", help="completed rows, e.g. 1-5,8")
    p.set_defaults(func=cmd_progress)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
