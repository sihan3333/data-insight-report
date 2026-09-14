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
    python clean_data.py <input_file> <output_dir> [--sheet NAME_OR_INDEX]

Produces in <output_dir>:
    cleaned.csv        - the cleaned dataset
    clean_report.json  - structured summary of every change made and every
                          issue that was flagged but NOT auto-fixed
                          (judgment calls belong to the person reading the
                          report, not to this script). Also carries
                          encoding_used / multiple_sheets when the input
                          wasn't a plain single-sheet UTF-8 file — see
                          load() below.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from column_heuristics import split_id_like_columns


# Tried in order until one decodes without error. utf-8 covers the vast
# majority of modern exports; gbk/big5 cover Chinese-locale Windows
# exports (a very common real-world source of "this file won't open"
# reports); latin-1 never raises a decode error at all (every byte maps
# to *some* character), so it's the guaranteed-to-terminate last resort
# rather than a confident guess — which is why the encoding actually used
# gets recorded in load_info rather than applied silently.
CSV_ENCODING_CANDIDATES = ["utf-8-sig", "utf-8", "gbk", "big5", "latin-1"]


# utf-8-sig decodes a plain (BOM-less) UTF-8 file just as well as a
# BOM'd one — it's tried first because it's the strictly safer of the
# two, not because it's unusual. Only note the encoding when it's
# something OTHER than plain UTF-8, so a completely ordinary file
# doesn't get flagged just because utf-8-sig happened to be the one
# that succeeded.
_ORDINARY_UTF8_ENCODINGS = {"utf-8", "utf-8-sig"}


def _read_csv_with_encoding_fallback(input_file: Path) -> tuple[pd.DataFrame, str | None]:
    last_err: Exception | None = None
    for enc in CSV_ENCODING_CANDIDATES:
        try:
            # Let pandas sniff the delimiter first...
            df = pd.read_csv(input_file, sep=None, engine="python", encoding=enc)
            return df, (enc if enc not in _ORDINARY_UTF8_ENCODINGS else None)
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception:
            # ...not an encoding problem (e.g. sniffing failed on an
            # unusual delimiter) — retry once as plain comma-separated
            # under this same encoding before moving on.
            try:
                df = pd.read_csv(input_file, encoding=enc)
                return df, (enc if enc not in _ORDINARY_UTF8_ENCODINGS else None)
            except UnicodeDecodeError as e2:
                last_err = e2
                continue
    raise last_err  # pragma: no cover — latin-1 above never actually gets here


def load(input_file: Path, sheet: str | int | None = None) -> tuple[pd.DataFrame, dict]:
    """Returns (dataframe, load_info) — load_info notes anything that
    wasn't a simple, unambiguous "just read the file" (a non-UTF-8
    encoding, or a choice made between multiple Excel sheets) so it can
    be surfaced in clean_report.json instead of silently applied."""
    load_info: dict = {}

    if input_file.suffix.lower() in (".xlsx", ".xls"):
        xl = pd.ExcelFile(input_file)
        sheet_names = xl.sheet_names
        if sheet is not None:
            chosen = sheet
        elif len(sheet_names) == 1:
            chosen = sheet_names[0]
        else:
            # A workbook with multiple sheets very often has a small
            # "notes"/"readme"/cover sheet ahead of the actual data (this
            # exact pattern — a notes sheet before the real data — showed
            # up on a real test file). Defaulting to "the first sheet"
            # would silently pick that notes sheet; "the sheet with the
            # most rows" is a much better guess at which one is the data,
            # and either way the choice gets flagged so it isn't silent.
            row_counts = {name: xl.parse(name).shape[0] for name in sheet_names}
            chosen = max(row_counts, key=row_counts.get)
            load_info["multiple_sheets"] = {
                "used": chosen,
                "available": sheet_names,
                "note": "picked the sheet with the most rows; pass --sheet to choose a different one",
            }
        df = xl.parse(chosen)
        load_info.setdefault("sheet_used", chosen)
        return df, load_info

    df, encoding_used = _read_csv_with_encoding_fallback(input_file)
    if encoding_used:
        load_info["encoding_used"] = encoding_used
    return df, load_info


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
    # row in the dataset. Skip identifier-like columns first (host_id,
    # a row's own id, ...): "1,526 outliers" in an arbitrary ID number is
    # not a finding, it's IQR math applied somewhere it doesn't mean
    # anything — found on a real dataset where this actually happened.
    numeric_cols = list(df.select_dtypes(include=[np.number]).columns)
    measurement_cols, _id_like_cols = split_id_like_columns(df, numeric_cols)
    for c in measurement_cols:
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
    ap = argparse.ArgumentParser()
    ap.add_argument("input_file", type=Path)
    ap.add_argument("output_dir", type=Path)
    ap.add_argument(
        "--sheet",
        default=None,
        help="Excel sheet name or index to read, for a workbook with more "
             "than one sheet. Omit to auto-pick the sheet with the most "
             "rows (see 'multiple_sheets' in clean_report.json for what "
             "else was available).",
    )
    args = ap.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    sheet = args.sheet
    if sheet is not None and sheet.isdigit():
        sheet = int(sheet)

    df, load_info = load(args.input_file, sheet=sheet)
    cleaned, report = clean(df)
    report.update(load_info)  # encoding_used / multiple_sheets, if any

    cleaned.to_csv(args.output_dir / "cleaned.csv", index=False)
    (args.output_dir / "clean_report.json").write_text(
        json.dumps(report, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )
    print(f"cleaned {report['rows_in']} -> {report['rows_out']} rows; "
          f"{len(report['actions'])} auto-fixes, {len(report['flagged'])} items flagged for review")
    if load_info.get("encoding_used"):
        print(f"note: read using '{load_info['encoding_used']}' encoding (not utf-8)")
    if "multiple_sheets" in load_info:
        ms = load_info["multiple_sheets"]
        print(f"note: workbook had {len(ms['available'])} sheets {ms['available']}; "
              f"used '{ms['used']}' (most rows) — pass --sheet to pick a different one")


if __name__ == "__main__":
    main()
