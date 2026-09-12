# data-insight-report

[![Tests](https://github.com/sihan3333/data-insight-report/actions/workflows/test.yml/badge.svg)](https://github.com/sihan3333/data-insight-report/actions/workflows/test.yml)

A [Claude Skill](https://www.anthropic.com/news/skills) that turns a raw,
messy tabular file (CSV / Excel) into a cleaned dataset and a visual
insight report — automatically, without a person writing pandas code by
hand for every new file.

Give Claude a spreadsheet and a request like *"clean this up and tell me
what's going on"*, and this skill drives a two-stage pipeline: a
deterministic cleaning pass, then chart generation, then Claude adds the
actual analysis on top.

## Why a "skill" instead of just asking an LLM to write pandas code each time

Two different kinds of decisions are involved in "analyze this data":

1. **Mechanical decisions** — is this row an exact duplicate? Is `"USA "`
   the same as `"USA"`? Is `$1,200.00` actually the number 1200? These
   should be answered the *same way every time*, and a bundled
   deterministic script guarantees that by construction rather than
   leaving it to be re-decided on every run. (An eval comparing this
   skill against an LLM writing the same cleaning logic from scratch each
   time found that claim harder to prove empirically than expected —
   see "Benchmarked against a baseline" below for the honest version.)
2. **Judgment decisions** — is that missing value worth worrying about
   for this dataset? Is this outlier a data-entry error or the most
   interesting row in the table? Those need context and understanding of
   what the person actually wants — that's where the LLM's reasoning adds
   real value, and where a script would just be guessing.

The skill is designed around that split: `scripts/clean_data.py` handles
(1) and produces a structured `clean_report.json` of exactly what it did
and didn't touch; the model handles (2) by reading that report and
deciding what's worth surfacing.

## What's in here

```
data-insight-report/
├── SKILL.md                    # the skill definition Claude reads
├── scripts/
│   ├── clean_data.py            # deterministic cleaning pass
│   └── build_report.py          # chart selection + HTML report generation
├── references/
│   └── chart_selection.md       # documents the chart-selection logic
└── examples/
    ├── sample_sales.csv         # a deliberately messy example input
    ├── sample_report.html       # the report generated from it
    └── sample_clean_report.json # the cleaning summary for that run
```

## Example

`examples/sample_sales.csv` is a small sales dataset seeded with the kind
of mess real exports actually have: a duplicated row, `"USA "` vs `"USA"`,
revenue stored as `"$1,200.00"` text, one missing revenue value, and one
outlier order. Running the pipeline on it:

```bash
python scripts/clean_data.py examples/sample_sales.csv /tmp/out
python scripts/build_report.py /tmp/out/cleaned.csv /tmp/out/clean_report.json /tmp/out/report.html --title "Sample Sales Report"
```

produces `clean_report.json` showing exactly what changed:

```json
{
  "actions": [
    {"type": "strip_whitespace", "columns": ["region"]},
    {"type": "drop_exact_duplicates", "count": 1},
    {"type": "coerce_to_numeric", "column": "revenue", "success_rate": 1.0}
  ],
  "flagged": [
    {"type": "missing_values", "detail": {"revenue": 1}},
    {"type": "outliers", "column": "revenue", "count": 2, "bounds": [-320.9, 2108.6]}
  ]
}
```

...and `report.html`, a single self-contained file (charts embedded as
base64 PNGs — nothing external to host) with a distribution histogram per
numeric column, a top-values bar chart per categorical column, a
correlation heatmap, and a time-series chart since the data has a date
column. See `examples/sample_report.html`.

## Tested against a real dataset, not just synthetic examples

`examples/sample_sales.csv` was hand-built to exercise specific cleaning
rules. To check the skill actually holds up outside of that, it was also
run against the [Titanic passenger
dataset](https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv)
(891 real historical records, genuinely messy — 20% of `Age` values and
77% of `Cabin` values are missing) — see `examples/titanic.csv` and
`examples/titanic_report.html`.

This surfaced a real bug the synthetic example never would have:
`PassengerId` (a row identifier, numeric but meaningless to plot) got
histogrammed as if it were a measurement, *and* crowded a genuinely
interesting column (`Fare`) out of the capped chart slots. Fixed in
`build_report.py` by detecting ID-like columns structurally — any numeric
column where every value is distinct — rather than relying on anyone to
remember to check column names by hand. Small case study in why testing
against real data (not just data written to satisfy your own test cases)
matters.

## Benchmarked against a baseline (with vs. without the skill)

Rather than assume the skill is better because it exists, it was compared
against the same model (Sonnet 5) doing the identical task with no skill
— just its own judgment and code written from scratch — across two
rounds of real subagent runs (not simulated). Full run outputs, grading,
and notes: `evals/evals.json` and the workspace directories under
`data-insight-report-workspace/` (not committed here, but reproducible —
see "Running an eval yourself" below).

**What held up across both rounds: efficiency.** Using the bundled,
already-debugged scripts instead of authoring pandas/matplotlib code from
scratch every time was consistently cheaper and faster:

| | Round 1 (2 evals) | Round 2 (1 eval, repeated) |
|---|---|---|
| Tokens | ~22-24% fewer | ~8% fewer |
| Time | ~34-40% less | ~47% less |

**What did NOT hold up: a "consistency" advantage.** Round 1 showed the
baseline impute missing values on one eval (Titanic) but decline to on
another (support tickets), and it was tempting to read that as "an LLM's
policy drifts run to run, the skill fixes that." Round 2 tested this
directly — the same baseline, run 4 independent times on a fresh dataset
with the identical prompt — and it declined to impute all 4 times,
matching the skill's behavior exactly. The apparent inconsistency in
round 1 looks more like Titanic specifically priming "prepare data for a
model" instincts than genuine run-to-run randomness. Correcting the
record here rather than keeping the more flattering version.

**Where both configurations tied: correctness.** On both rounds' factual
assertions (right missing-value counts, right survival-rate numbers,
avoiding a meaningless ID-column chart), the baseline matched the skill
5/5 and 2/2. Sonnet 5 is strong enough to get these specific facts right
unaided — the skill's value here is guaranteeing that behavior by
construction, not rescuing a weaker model, which is a real but more
modest claim than "the skill produces better analysis."

The honest takeaway: this skill's proven value is running faster and
cheaper on repeated invocations, plus giving reproducible cleaning rules
you can read and audit in code rather than trust to a model's judgment
call each time. It has not been shown (yet) to produce more consistent
or more correct output than a capable model working unaided — that would
need a larger eval to actually claim.

## Using it as a Claude Code skill

Copy (or symlink) this folder into your skills directory:

```bash
cp -r data-insight-report ~/.claude/skills/
```

Then in Claude Code, just hand it a data file: *"analyze sales.csv and
tell me what's interesting in it"*. Claude reads `SKILL.md`, runs the two
scripts, and writes the narrative on top of what they find.

## Running the scripts standalone

They don't require Claude at all — they're plain Python:

```bash
pip install -r requirements.txt
python scripts/clean_data.py <input.csv|.xlsx> <output_dir>
python scripts/build_report.py <output_dir>/cleaned.csv <output_dir>/clean_report.json <output_dir>/report.html --title "My Report"
```

## Running tests

```bash
pip install -r requirements-dev.txt
python -m pytest -v
```

Tests target the parts of the pipeline with an actual right answer —
does a duplicate row get dropped, does a mostly-text column stay
uncoerced, does an ID-like column get excluded from the numeric charts —
rather than asserting on exact chart pixels. They run in CI on every
push (see the badge above and `.github/workflows/test.yml`).

## Design notes / things deliberately left alone

- **Missing values are never silently imputed.** They're counted and
  reported so a human (or the model, reasoning about the specific
  dataset) decides what to do.
- **Outliers are flagged, not removed.** An extreme value in a
  business dataset is often the most important row, not noise.
- **No pie charts.** Bar charts are easier to read accurately.

See `references/chart_selection.md` for the full reasoning behind chart
selection, and `SKILL.md` for how Claude is instructed to use all of this.
