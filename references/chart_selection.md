# Chart selection logic (as implemented in build_report.py)

This is the reasoning `build_charts()` follows, spelled out so you can
extend it or explain a choice without re-reading the code line by line.

| Column shape | Chart | Why |
|---|---|---|
| A detected date/datetime column + at least one numeric column | Line chart, metric over time | A trend over time is almost always the headline finding when a date exists — surface it first. |
| Numeric column (any) | Histogram | Shows the shape of the distribution (skew, multi-modality, spread) that a mean/median alone hides. Capped at 6 columns so the report doesn't drown in near-duplicate charts on wide tables. |
| Object/string column with 2-30 distinct values | Horizontal bar chart of top values | Enough categories to be worth a chart, few enough to stay readable. Above 30 distinct values it's likely a near-unique field (name, free text, ID) — charting it as categories would be noise, not signal. |
| 3+ numeric columns together | Correlation heatmap | Pairwise correlation only becomes worth a dedicated chart once there's enough numeric structure that eyeballing a table of numbers stops working. Two columns: just say the correlation number in the narrative instead. |

## Things this logic deliberately does NOT do

- **No automatic outlier removal in charts.** Outliers are flagged in
  `clean_report.json` for a human judgment call, and histograms show them
  as-is — an extreme bar is often the most informative thing on the chart,
  not noise to hide.
- **No pie charts.** Bar charts are easier to compare accurately; pies are
  avoided per general chart-design practice, not because they're
  unsupported.
- **No forced chart on ID-like numeric columns.** `split_id_like_columns()`
  (in `scripts/column_heuristics.py`, shared with `clean_data.py`) excludes
  these from the numeric distribution charts and the correlation heatmap
  — noted in the report's overview instead of silently vanishing. Two
  rules, added at two different points because one wasn't enough:
  1. **Every non-null value is unique** — a row's own id, an order
     number. Detected structurally regardless of naming convention or
     language. This was originally left as a "remember to check the
     column names" note for whoever runs the report, until testing
     against a real dataset (Titanic) showed it wasn't hypothetical:
     `PassengerId` got histogrammed *and* pushed a more informative
     column (`Fare`) out of the capped chart slots.
  2. **Name ends in `_id` (or is exactly `id`) AND cardinality is high
     (>50% distinct) but not perfect.** Needed for foreign-key-style
     columns — `host_id` in a listings table repeats once per extra
     listing that host owns, so rule 1 alone doesn't catch it. Found on
     a real 49k-row Airbnb dataset: `host_id` got histogrammed, polluted
     the correlation heatmap with a meaningless variable, AND had 1,526
     "IQR outliers" flagged in `clean_report.json` — a number that looks
     like a finding but is really just IQR math applied to arbitrary
     large integers. This rule does rely on naming convention on purpose:
     uniqueness alone genuinely can't tell "host_id" apart from a real
     measurement that happens to vary a lot.

## Extending it

If a dataset needs a chart type this doesn't cover (e.g. a scatter plot
for two correlated numeric columns, a box plot per category), add it as a
new block in `build_charts()` in `scripts/build_report.py` following the
same pattern: check the column shape that triggers it, build the
matplotlib figure, append a `{"title", "img", "note"}` dict to the list.
