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
- **No forced chart on ID-like numeric columns.** A numeric column where
  every non-null value is unique (customer ID, order number, row index)
  is structurally detected in `split_id_like_columns()` and excluded from
  the numeric distribution charts and the correlation heatmap — it's
  noted in the report's overview instead of silently vanishing. This was
  originally left as a "remember to check the column names" note for
  whoever runs the report, until testing against a real dataset (Titanic)
  showed it wasn't a hypothetical edge case: `PassengerId` got histogrammed
  *and* pushed a more informative column (`Fare`) out of the capped chart
  slots. Detecting structurally (uniqueness) rather than by name works
  regardless of naming convention or language, and needs no one to
  remember anything.

## Extending it

If a dataset needs a chart type this doesn't cover (e.g. a scatter plot
for two correlated numeric columns, a box plot per category), add it as a
new block in `build_charts()` in `scripts/build_report.py` following the
same pattern: check the column shape that triggers it, build the
matplotlib figure, append a `{"title", "img", "note"}` dict to the list.
