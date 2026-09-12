#!/usr/bin/env python3
"""
clean_data.py — deterministic data cleaning pass for data-insight-report.

Why this exists as a script rather than left to free-form reasoning:
cleaning steps (duplicate detection, whitespace stripping, type coercion,
outlier flagging) are the same mechanical checks every time. Running them
as code is faster and more reliable than having a model eyeball a table,
and it produces a machine-readable diff of exactly what changed — which
the report generator and the human reviewing it both need.

Usage:
    python clean_data.py <input_file> <output_dir>

Produces in <output_dir>:
    cleaned.csv        - the cleaned dataset
    clean_report.json  - structured summary of every change made and every
                          issue that was flagged but NOT auto-fixed
                          (judgment calls belong to the person reading the
                          report, not to this script)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load(input_file: Path) -> pd.DataFrame:
    if input_file.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(input_file)
    # Let pandas sniff the delimiter; fall back to comma.
    try:
        return pd.read_csv(input_file, sep=None, engine="python")
    except Exception:
        return pd.read_csv(input_file)


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report = {"rows_in": len(df), "columns": list(df.columns), "actions": [], "flagged": []}
    df = df.copy()

    # 1. Drop fully-empty rows/columns — never informative, safe to remove.
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        report["actions"].append({"type": "drop_empty_columns", "columns": empty_cols})

    empty_rows = int(df.isna().all(axis=1).sum())
    if empty_rows:
        df = df.dropna(how="all")
        report["actions"].append({"type": "drop_empty_rows", "count": empty_rows})

    # 2. Strip whitespace on string columns — a very common source of
    # false "different" categories ("USA " vs "USA").
    str_cols = df.select_dtypes(include=["object", "string"]).columns
    stripped_cols = []
    for c in str_cols:
        stripped = df[c].astype(str).str.strip()
        if not stripped.equals(df[c].astype(str)):
            df[c] = stripped
            stripped_cols.append(c)
    if stripped_cols:
        report["actions"].append({"type": "strip_whitespace", "columns": list(stripped_cols)})

    # 3. Exact duplicate rows — safe to drop, always.
    dup_count = int(df.duplicated().sum())
    if dup_count:
        df = df.drop_duplicates()
        report["actions"].append({"type": "drop_exact_duplicates", "count": dup_count})

    # 4. Try to coerce object columns that are "actually numeric"
    # (e.g. "1,234" or "$50.00" stored as text). Only coerce when at
    # least 90% of non-null values convert cleanly — otherwise leave it
    # alone and flag it instead of silently corrupting real text data.
    for c in df.select_dtypes(include=["object", "string"]).columns:
        non_null = df[c].dropna()
        if non_null.empty:
            continue
        candidate = (
            non_null.astype(str)
            .str.replace(r"[,$%]", "", regex=True)
            .str.strip()
        )
        numeric = pd.to_numeric(candidate, errors="coerce")
        success_rate = numeric.notna().mean()
        if success_rate >= 0.9 and success_rate < 1.0 or (success_rate == 1.0 and (df[c].astype(str).str.contains(r"[,$%]")).any()):
            df[c] = pd.to_numeric(
                df[c].astype(str).str.replace(r"[,$%]", "", regex=True).str.strip(),
                errors="coerce",
            )
            report["actions"].append({
                "type": "coerce_to_numeric",
                "column": c,
                "success_rate": round(float(success_rate), 3),
            })

    # 5. Missing values — report, don't guess. Imputing silently would
    # hide a real data-quality problem from whoever reads the report.
    missing = df.isna().sum()
    missing = missing[missing > 0]
    if len(missing):
        report["flagged"].append({
            "type": "missing_values",
            "detail": {col: int(n) for col, n in missing.items()},
        })

    # 6. Outliers on numeric columns via IQR — flagged, not removed,
    # since a legitimate extreme value is often the most interesting
    # row in the dataset.
    for c in df.select_dtypes(include=[np.number]).columns:
        series = df[c].dropna()
        if len(series) < 8:
            continue
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = series[(series < lo) | (series > hi)]
        if len(outliers):
            report["flagged"].append({
                "type": "outliers",
                "column": c,
                "count": int(len(outliers)),
                "bounds": [round(float(lo), 3), round(float(hi), 3)],
            })

    # 7. Constant columns — carry no information, worth flagging so the
    # report can suggest dropping them (but don't drop automatically —
    # a constant column can be intentional, e.g. a fixed fiscal year).
    for c in df.columns:
        if df[c].nunique(dropna=True) == 1:
            report["flagged"].append({"type": "constant_column", "column": c})

    report["rows_out"] = len(df)
    return df, report


def main():
    if len(sys.argv) != 3:
        print("usage: clean_data.py <input_file> <output_dir>", file=sys.stderr)
        sys.exit(1)

    input_file = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])
    output_dir.mkdir(parents=True, exist_ok=True)

    df = load(input_file)
    cleaned, report = clean(df)

    cleaned.to_csv(output_dir / "cleaned.csv", index=False)
    (output_dir / "clean_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    print(f"cleaned {report['rows_in']} -> {report['rows_out']} rows; "
          f"{len(report['actions'])} auto-fixes, {len(report['flagged'])} items flagged for review")


if __name__ == "__main__":
    main()
