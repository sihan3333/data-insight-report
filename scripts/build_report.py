#!/usr/bin/env python3
"""
build_report.py — turns a cleaned dataset + clean_report.json into a single
self-contained HTML report (charts embedded as base64 PNGs, no external
files needed to view it).

Why a script and not free-form chart code each time: the chart *selection*
logic (which columns get a histogram vs a bar chart vs a correlation
heatmap) is a mechanical decision based on dtype and cardinality — doing
it in code guarantees consistent, sane choices instead of re-deriving them
from scratch (and re-writing boilerplate matplotlib setup) on every run.

Usage:
    python build_report.py <cleaned_csv> <clean_report_json> <output_html> [--title "My Report"]
"""
import argparse
import base64
import io
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from column_heuristics import split_id_like_columns

# A small, colorblind-friendly categorical palette — swap for brand colors
# if this report needs to match a specific look.
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B2", "#937860"]
MAX_NUMERIC_CHARTS = 6
MAX_CATEGORICAL_CHARTS = 4
MAX_CATEGORY_BARS = 10

# matplotlib's default font (DejaVu Sans) has no CJK glyphs — a column
# name, category, or narrative snippet in Chinese/Japanese/Korean would
# render as a row of missing-glyph boxes in every chart. Use whichever
# CJK-capable font this machine actually has (checked in a fixed order
# rather than picking arbitrarily) instead of silently producing charts
# with unreadable labels. If none of these are installed (e.g. a bare-bones
# Linux CI image), CJK text will still show as boxes — there's no way
# around that without bundling a font file, which trades a few KB of
# missing glyphs for several MB of repo size; not worth it for a skill
# meant to run on a normal desktop or dev machine.
_CJK_FONT_CANDIDATES = [
    "Microsoft YaHei", "SimHei", "Microsoft JhengHei", "SimSun",  # Windows
    "PingFang SC", "Heiti SC", "STHeiti",  # macOS
    "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Zen Hei",  # Linux
]
_installed_fonts = {f.name for f in fm.fontManager.ttflist}
_cjk_font = next((f for f in _CJK_FONT_CANDIDATES if f in _installed_fonts), None)
if _cjk_font:
    plt.rcParams["font.sans-serif"] = [_cjk_font, "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False  # CJK fonts often lack the typographic minus glyph


def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def detect_datetime_column(df: pd.DataFrame):
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return c
        if df[c].dtype == object:
            sample = df[c].dropna().head(20)
            if len(sample) == 0:
                continue
            parsed = pd.to_datetime(sample, errors="coerce", format=None)
            if parsed.notna().mean() > 0.9:
                return c
    return None


def build_charts(df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    charts = []
    numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns]
    numeric_cols, id_like_cols = split_id_like_columns(df, numeric_cols)
    categorical_cols = [
        c for c in df.select_dtypes(include=["object", "string"]).columns
        if 1 < df[c].nunique(dropna=True) <= 30
    ]
    date_col = detect_datetime_column(df)

    # Time series first — usually the headline story if a date exists.
    if date_col and numeric_cols:
        dates = pd.to_datetime(df[date_col], errors="coerce")
        metric = numeric_cols[0]
        series = df.assign(_date=dates).dropna(subset=["_date"]).sort_values("_date")
        if len(series) >= 3:
            fig, ax = plt.subplots(figsize=(7, 3.2))
            ax.plot(series["_date"], series[metric], color=PALETTE[0], linewidth=1.8)
            ax.set_title(f"{metric} over time")
            ax.set_xlabel(date_col)
            ax.set_ylabel(metric)
            fig.autofmt_xdate()
            charts.append({
                "title": f"{metric} over time",
                "img": fig_to_base64(fig),
                "note": f"Trend of {metric} ordered by {date_col}.",
            })

    # Distributions for numeric columns.
    for c in numeric_cols[:MAX_NUMERIC_CHARTS]:
        series = df[c].dropna()
        if series.empty:
            continue
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.hist(series, bins=min(30, max(5, int(len(series) ** 0.5))), color=PALETTE[1])
        ax.set_title(f"Distribution of {c}")
        ax.set_xlabel(c)
        ax.set_ylabel("count")
        charts.append({
            "title": f"Distribution of {c}",
            "img": fig_to_base64(fig),
            "note": f"mean={series.mean():.2f}, median={series.median():.2f}, std={series.std():.2f}",
        })

    # Top categories for categorical columns.
    for c in categorical_cols[:MAX_CATEGORICAL_CHARTS]:
        counts = df[c].value_counts().head(MAX_CATEGORY_BARS)
        fig, ax = plt.subplots(figsize=(5, 3))
        ax.barh(counts.index.astype(str)[::-1], counts.values[::-1], color=PALETTE[2])
        ax.set_title(f"Top values of {c}")
        ax.set_xlabel("count")
        charts.append({
            "title": f"Top values of {c}",
            "img": fig_to_base64(fig),
            "note": f"{df[c].nunique()} distinct values total; showing top {min(MAX_CATEGORY_BARS, df[c].nunique())}.",
        })

    # Correlation heatmap if there's enough numeric structure to show.
    if len(numeric_cols) >= 3:
        corr = df[numeric_cols].corr(numeric_only=True)
        fig, ax = plt.subplots(figsize=(5.5, 4.5))
        im = ax.imshow(corr, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(corr.columns)))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right")
        ax.set_yticks(range(len(corr.columns)))
        ax.set_yticklabels(corr.columns)
        fig.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("Correlation between numeric columns")
        charts.append({
            "title": "Correlation heatmap",
            "img": fig_to_base64(fig),
            "note": "Pearson correlation; values near ±1 indicate a strong linear relationship.",
        })

    return charts, id_like_cols

    return charts


HTML_TEMPLATE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background:#f7f7f8; color:#1d1d1f; margin:0; }}
  .wrap {{ max-width: 960px; margin: 0 auto; padding: 32px 24px 64px; }}
  h1 {{ font-size: 26px; margin-bottom: 4px; }}
  .subtitle {{ color:#6b6b70; margin-top:0; margin-bottom:28px; }}
  .card {{ background:#fff; border:1px solid #e4e4e7; border-radius:12px; padding:20px 24px; margin-bottom:20px; }}
  .card h2 {{ font-size:16px; margin-top:0; }}
  .card.narrative {{ border-left:4px solid #4C72B0; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap:16px; }}
  .grid .card img {{ max-width:100%; display:block; }}
  .note {{ font-size:13px; color:#6b6b70; margin-top:8px; }}
  table {{ border-collapse: collapse; width:100%; font-size:13px; }}
  th, td {{ text-align:left; padding:6px 10px; border-bottom:1px solid #eee; }}
  ul {{ margin:6px 0; padding-left: 20px; }}
  .tag {{ display:inline-block; background:#eef2ff; color:#3730a3; border-radius:6px; padding:2px 8px; font-size:12px; margin:2px 4px 2px 0; }}
  .tag.flag {{ background:#fef2f2; color:#991b1b; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>

  {narrative_html}

  <div class="card">
    <h2>Data cleaning summary</h2>
    {cleaning_html}
  </div>

  <div class="card">
    <h2>Overview</h2>
    {overview_html}
  </div>

  <div class="grid">
    {charts_html}
  </div>
</div>
</body>
</html>
"""


def render_cleaning_html(report: dict) -> str:
    parts = []
    parts.append(f"<p>{report['rows_in']} rows in &rarr; {report['rows_out']} rows out.</p>")
    if report["actions"]:
        parts.append("<p><strong>Auto-fixed:</strong></p><div>")
        for a in report["actions"]:
            parts.append(f'<span class="tag">{json.dumps(a, default=str, ensure_ascii=False)}</span>')
        parts.append("</div>")
    if report["flagged"]:
        parts.append("<p><strong>Flagged for your review (not auto-changed):</strong></p><div>")
        for f in report["flagged"]:
            parts.append(f'<span class="tag flag">{json.dumps(f, default=str, ensure_ascii=False)}</span>')
        parts.append("</div>")
    if not report["actions"] and not report["flagged"]:
        parts.append("<p>No issues found — data was already clean.</p>")
    return "\n".join(parts)


def render_overview_html(df: pd.DataFrame, id_like_cols: list[str]) -> str:
    rows = [f"<tr><td>Rows</td><td>{len(df)}</td></tr>",
            f"<tr><td>Columns</td><td>{len(df.columns)}</td></tr>"]
    dtypes = df.dtypes.astype(str).to_dict()
    dtype_list = ", ".join(f"{k} ({v})" for k, v in list(dtypes.items())[:12])
    rows.append(f"<tr><td>Column types</td><td>{dtype_list}</td></tr>")
    html = f"<table>{''.join(rows)}</table>"
    if id_like_cols:
        cols = ", ".join(id_like_cols)
        html += (
            f'<p class="note">Excluded from numeric charts as likely ID '
            f"columns (either every value is unique, or the name and high "
            f"cardinality look like a foreign key, e.g. host_id) — an "
            f"identifier isn't a measurement worth plotting a distribution "
            f"of: {cols}.</p>"
        )
    return html


def render_narrative_html(narrative_file: str | None) -> str:
    if not narrative_file:
        return ""
    text = Path(narrative_file).read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return f'<div class="card narrative"><h2>Key findings</h2>{text}</div>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cleaned_csv")
    ap.add_argument("clean_report_json")
    ap.add_argument("output_html")
    ap.add_argument("--title", default="Data Insight Report")
    ap.add_argument(
        "--narrative-file",
        default=None,
        help=(
            "Path to an HTML fragment with your written analysis (a few "
            "<p> paragraphs and/or a <ul><li> list — stick to the tags "
            "already used elsewhere in this report). Rendered as a "
            "'Key findings' card right at the top, above the cleaning "
            "summary. Write this file AFTER looking at the charts this "
            "script produces on a first run, then re-run with this flag "
            "to fold it in — the whole regenerate is cheap and "
            "deterministic, and it avoids hand-editing the generated "
            "HTML (fragile: easy to match the wrong anchor and corrupt "
            "the file)."
        ),
    )
    args = ap.parse_args()

    df = pd.read_csv(args.cleaned_csv)
    report = json.loads(Path(args.clean_report_json).read_text(encoding="utf-8"))

    charts, id_like_cols = build_charts(df)
    charts_html = "\n".join(
        f'<div class="card"><h2>{c["title"]}</h2>'
        f'<img src="data:image/png;base64,{c["img"]}" />'
        f'<div class="note">{c["note"]}</div></div>'
        for c in charts
    )

    html = HTML_TEMPLATE.format(
        title=args.title,
        subtitle=f"Generated from {Path(args.cleaned_csv).name} · {len(df)} rows · {len(df.columns)} columns",
        narrative_html=render_narrative_html(args.narrative_file),
        cleaning_html=render_cleaning_html(report),
        overview_html=render_overview_html(df, id_like_cols),
        charts_html=charts_html or "<p>No charts could be generated from this dataset.</p>",
    )

    Path(args.output_html).write_text(html, encoding="utf-8")
    tag = " (with narrative)" if args.narrative_file else " (no narrative yet)"
    print(f"wrote {args.output_html} with {len(charts)} charts{tag}")


if __name__ == "__main__":
    main()
