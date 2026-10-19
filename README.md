# Backstitch

**Plan a cross-stitch piece from one plain-text chart: exact floss, skeins, fabric size and stitching time, offline.**

Backstitch reads a simple text chart and tells you what to buy and how long it will take. It covers the outlines and details too, and it prints or exports a chart you can take to the frame. It uses only the Python standard library. There are no servers, accounts, network calls or API keys.

## Features

- **Plain-text chart format.** One file holds the settings, the colour palette, the chart grid and any backstitch lines.
- **Line-numbered lint.** Every error is reported as `file:line:col`, covering unknown symbols, ragged rows, duplicate palette symbols, bad settings and out-of-bounds backstitch points.
- **CI-friendly checks.** `check` exits 0 when the chart is clean and 1 on errors. `--strict` also fails on warnings such as unused palette colours.
- **Stitch counts per colour.** Full cross stitches for each palette symbol, with each colour's share of the piece.
- **Floss length estimate.** Strand length for each colour, from stitch count, backstitch length, strand count and a waste allowance.
- **Skein calculator.** Skeins needed per colour, rounded up from your skein length and strands per skein.
- **Fabric size.** The minimum cut size in inches, from the chart width and height, the fabric count and a margin on every side.
- **Stitching time.** An hour estimate from your stitches-per-hour rate, counting backstitch cells too.
- **Text chart.** A printable grid with row numbers, a column ruler and a colour legend.
- **SVG export.** Coloured cells with symbols printed inside them, 10-cell gridlines and backstitch lines in their thread colours.
- **Progress tracking.** Report the percentage of stitches done for any set of completed rows, with a per-colour breakdown.
- **Backstitch support.** Polyline backstitch paths with exact Euclidean length, so diagonals are counted correctly.

## Quick start

Save this as `little-house.bst`, or use the sample in `examples/little-house.bst`:

```text
title: Little House
count: 14
strands: 2
waste: 15
margin: 3
skein_yd: 8.7
strands_per_skein: 6
rate: 50

[palette]
# SYMBOL CODE NAME [#HEX]
R 321 Red #c8102e
W blanc White #ffffff
B 798 Delft Blue #1f4e79
G 3363 Pine Green #4a6b3a
K 310 Black #000000

[chart]
............
.....KK.....
....KRRK....
...KRRRRK...
..KRRRRRRK..
.KRRRRRRRRK.
KKKKKKKKKKKK
KWWWWGGWWWWK
KWBBWGGWBBWK
KWBBWWWWBBWK
KWBBWWWWBBWK
KKKKKKKKKKKK

[backstitch]
# SYMBOL then x,y corner points on the grid lines
K 0,6 12,6
K 0,12 12,12
K 6,0 6,2
```

Then run:

```sh
python3 backstitch.py check examples/little-house.bst
python3 backstitch.py summary examples/little-house.bst
python3 backstitch.py materials examples/little-house.bst
python3 backstitch.py chart examples/little-house.bst
python3 backstitch.py svg examples/little-house.bst -o little-house.svg
python3 backstitch.py progress examples/little-house.bst --done 1-6
```

Counting the sample by hand gives 102 cross stitches: 42 black, 20 red, 24 white, 12 Delft blue and 4 pine green. Run `summary` to see the same counts from the tool.

## Chart file format

- **Settings.** Lines of `key: value` before the first section. The keys are `title`, `count` (threads per inch on the fabric), `strands`, `waste` (percent), `margin` (inches of spare fabric per side), `skein_yd`, `strands_per_skein` and `rate` (stitches per hour). Any setting you leave out takes its default. The defaults are count 14, strands 2, waste 15, margin 3, skein 8.7 yd, 6 strands per skein and rate 60.
- **`[palette]`.** One entry per line: `SYMBOL CODE NAME [#RRGGBB]`. The symbol is one character, and it can't be `.`, `#` or `[`. The hex colour is optional.
- **`[chart]`.** Each line is one row of cells with one symbol per stitch, and `.` for an empty cell. Every row must be the same width.
- **`[backstitch]`.** `SYMBOL x,y x,y ...` lists the corner points of a backstitch path on the grid lines. Points must lie within the chart.
- **Comments.** Lines that start with `#` are ignored.

## How to run

Requires Python 3.10 or newer. There is nothing to install for the tool itself.

```sh
python3 backstitch.py <command> <chart.bst> [options]
```

| Command | What it does |
| --- | --- |
| `check FILE [--strict]` | Lint the chart. Exit 1 on errors, or on warnings with `--strict`. |
| `summary FILE` | Stitch counts and share per colour. |
| `materials FILE` | Fabric size, stitch time, and floss and skein needs per colour. |
| `chart FILE` | Print the chart as text with a legend. |
| `svg FILE [-o OUT] [--cell PX]` | Write an SVG chart (to stdout if `-o` is omitted). |
| `progress FILE --done RANGES` | Percent complete for rows such as `1-5,8`. |

## How to test

The tests use pytest and cover parsing, lint messages with line numbers, stitch and backstitch counting, skein and fabric arithmetic, progress ranges, the text and SVG renderers, and the CLI exit codes.

```sh
pip install pytest
python3 -m pytest tests
```

## Estimates and limits

The floss and time figures are planning estimates, not measurements. Thread per cross stitch is set by `CROSS_FACTOR` in `backstitch.py`, and backstitch thread by `BACK_FACTOR`. Both are documented in the code. Tune them against a real sample of your own if you need precision. Skeins assume each skein gives `strands_per_skein` strands of `skein_yd` each. Colour matching to a brand's thread numbers is up to you: the palette records the codes you enter and does not look them up.
