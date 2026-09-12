---
name: data-insight-report
description: Cleans a messy raw dataset (CSV/Excel/TSV) and generates a data insight report with charts and a summary of data-quality issues. Use this whenever the user shares a data file and wants it analyzed, summarized, visualized, or turned into a report/dashboard — including requests like "clean this data", "what's in this spreadsheet", "find issues in this data", "analyze this csv/excel file", "give me a report on this data", or "make a chart/summary from this file", even if they don't use the words "clean" or "report" explicitly. Also use when a dataset looks messy (missing values, inconsistent formatting, duplicate rows) and the user asks any analysis question about it — cleaning should happen before analysis, not be treated as a separate ask.
---

# Data Insight Report

Turns a raw, possibly messy tabular file into two things: a defensibly-clean
dataset, and a report that shows what's in it and what's worth noticing.

## Why this is two stages, not one

Cleaning and analysis are different kinds of judgment. Cleaning decisions
(dropping an all-empty column, stripping whitespace, merging "USA " and
"USA") are mechanical and should be applied the same way every time — that
belongs in code, not left to per-run reasoning. Analysis decisions (which
finding matters, how to phrase it, what the user actually wants to know)
require understanding the specific dataset and the specific person asking
— that's where your judgment as the model does the real work. Keep them
separate: run the cleaning script, then reason freely over what it found.

## Workflow

1. **Locate the input file.** If the user didn't give a path, ask for it or
   look for an obvious candidate (a recently mentioned file, something in
   the working directory). Don't guess at a file you haven't confirmed
   exists.

2. **Clean it deterministically.**
   ```bash
   python scripts/clean_data.py <input_file> <output_dir>
   ```
   This writes `cleaned.csv` and `clean_report.json` to `<output_dir>`.
   Read `clean_report.json` — it lists every auto-fix applied (dropped
   duplicates, stripped whitespace, coerced numeric-looking text) and
   every issue it *flagged but didn't touch* (missing values, outliers,
   constant columns). The flagged items are judgment calls: decide, given
   this dataset and this user's goal, whether they matter enough to
   mention or act on. Never silently impute missing values yourself either
   — if it's worth filling in, say so and explain the method you used.

3. **Generate the report — twice.** The first run is so you can see what
   the data actually looks like; the second folds your analysis in.
   ```bash
   python scripts/build_report.py <output_dir>/cleaned.csv <output_dir>/clean_report.json <output_dir>/report.html --title "<a title describing the dataset>"
   ```
   This picks charts based on column types (numeric distributions,
   category bar charts, a correlation heatmap once there are 3+ numeric
   columns, a time series if it finds a date-like column) and embeds them
   as a single self-contained HTML file — nothing external to host.

4. **Decide the deliverable format** based on context, not by default habit:
   - **Default: hand back the HTML report as-is** (or publish it as an
     Artifact if you're in an environment that supports that) — it's
     interactive-feeling, renders charts natively, and needs no extra
     conversion step. This is right for "analyze this data", "what's
     going on in this file", exploratory requests.
   - **Convert to Word/PDF** when the user's framing implies a formal
     deliverable someone else will read passively — "report for my
     manager", "send this to the client", "I need a PDF/doc". Use the
     `docx` or `pdf` skill if available for the conversion rather than
     hand-rolling one.
   - **Convert to slides** if they say "deck" or "presentation" — use the
     `pptx` skill if available, pulling the same charts and findings.
   - If genuinely unsure, produce the HTML report and ask which final
     format they want rather than guessing and redoing work.

5. **Write the narrative, then fold it back in — don't hand-edit the HTML.**
   The scripts produce charts and raw numbers, not conclusions. Look at the
   report from step 3 and at `clean_report.json`, then write 3-6 sentences
   of actual analysis — what stands out, what's surprising, what looks
   like a data-entry artifact vs. a real pattern, what you'd check next. A
   report with charts and no interpretation is half the deliverable.

   Put that analysis in a small HTML fragment file (a `<p>` or two, maybe
   a `<ul><li>` list — stick to tags already used elsewhere in the
   report), then re-run the same command with `--narrative-file`:
   ```bash
   python scripts/build_report.py <output_dir>/cleaned.csv <output_dir>/clean_report.json <output_dir>/report.html --title "..." --narrative-file <path-to-your-fragment>
   ```
   This renders it as a "Key findings" card at the top of the report.
   Regenerating from scratch is cheap and deterministic — do this instead
   of grepping the generated `report.html` for an insertion point and
   editing it by hand. That approach works until it doesn't: the anchor
   you match on can appear more than once, or not quite where you
   expected, and a bad edit silently produces a corrupted report instead
   of an error you'd notice.

## Edge cases worth handling deliberately

- **File too large to load comfortably**: sample it (e.g.
  `pd.read_csv(..., nrows=200_000)`) and say so in the report rather than
  letting the process hang or silently truncate.
- **No numeric columns at all**: the charts will lean on categorical bar
  charts only — that's fine, don't force a histogram onto nothing.
- **A column that's actually an ID** (unique per row, e.g. `user_id`,
  `order_number`): `build_report.py` detects this automatically (every
  non-null value distinct) and excludes it from the numeric charts,
  noting it in the overview instead of silently dropping it. You don't
  need to catch this by hand — this was originally a "remember to check
  column names" instruction, found to be an actual problem (not just a
  hypothetical one) the first time this skill ran against a real dataset
  (Titanic's `PassengerId` both got a meaningless histogram and crowded a
  more interesting column out of the chart cap), and fixed structurally
  instead of relying on every future run to remember it.
- **Sensitive data** (names, emails, financial account numbers): don't
  put raw sensitive values into chart labels or the narrative beyond what's
  needed to make the point — aggregate instead of exposing rows.

## Files in this skill

- `scripts/clean_data.py` — deterministic cleaning pass (see docstring for
  exactly what it does and does not auto-fix)
- `scripts/build_report.py` — chart selection + self-contained HTML report
  generation
- `references/chart_selection.md` — the reasoning behind which chart type
  gets picked for which column shape, useful if you need to add a new
  chart type or explain a choice to the user
