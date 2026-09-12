"""Tests for scripts/clean_data.py.

These pin down the contract clean() promises in its docstring: mechanical
issues get fixed and recorded, judgment-call issues get flagged and left
alone. That split is the whole point of the skill (see SKILL.md), so it's
worth protecting with tests more than almost anything else here.
"""
import numpy as np
import pandas as pd
import pytest

from scripts.clean_data import clean


def test_exact_duplicate_rows_are_dropped_and_counted():
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    cleaned, report = clean(df)

    assert len(cleaned) == 2
    assert {"type": "drop_exact_duplicates", "count": 1} in report["actions"]


def test_whitespace_is_stripped_on_string_columns():
    df = pd.DataFrame({"region": ["USA ", " EU", "APAC"], "value": [1, 2, 3]})
    cleaned, report = clean(df)

    assert list(cleaned["region"]) == ["USA", "EU", "APAC"]
    assert any(a["type"] == "strip_whitespace" for a in report["actions"])


def test_currency_like_text_is_coerced_to_numeric():
    df = pd.DataFrame({
        "revenue": ["$1,200.00", "$950.50", "$2,300.00", "$430.00"],
        "n": [1, 2, 3, 4],
    })
    cleaned, report = clean(df)

    assert pd.api.types.is_numeric_dtype(cleaned["revenue"])
    assert cleaned["revenue"].iloc[0] == pytest.approx(1200.00)
    assert any(a["type"] == "coerce_to_numeric" and a["column"] == "revenue"
               for a in report["actions"])


def test_mostly_text_column_is_not_coerced():
    # Only 1 of 5 values looks numeric — coercing would silently corrupt
    # real text data, so clean() must leave it alone. (Checking
    # "not numeric" rather than "is object" since pandas' string dtype
    # varies by version/backend — object on some, StringDtype on others.)
    df = pd.DataFrame({"note": ["100", "widget A", "widget B", "widget C", "widget D"]})
    cleaned, report = clean(df)

    assert not pd.api.types.is_numeric_dtype(cleaned["note"])
    assert not any(a["type"] == "coerce_to_numeric" for a in report["actions"])


def test_missing_values_are_flagged_not_imputed():
    df = pd.DataFrame({"a": [1, 2, None, 4], "b": [1, 2, 3, 4]})
    cleaned, report = clean(df)

    # Still there — never silently filled in.
    assert cleaned["a"].isna().sum() == 1
    flagged_types = [f["type"] for f in report["flagged"]]
    assert "missing_values" in flagged_types


def test_outliers_are_flagged_not_removed():
    # An "id" column keeps every row distinct so the repeated `value`s
    # (9, 10, 11 each appear twice) aren't themselves treated as exact
    # duplicate rows and dropped before the outlier check ever runs.
    df = pd.DataFrame({
        "id": range(8),
        "value": [10, 11, 9, 10, 12, 11, 9, 500],
    })
    cleaned, report = clean(df)

    # The extreme value stays in the data...
    assert 500 in list(cleaned["value"])
    # ...but shows up as something to look at.
    outlier_flags = [f for f in report["flagged"] if f["type"] == "outliers"]
    assert len(outlier_flags) == 1
    assert outlier_flags[0]["column"] == "value"
    assert outlier_flags[0]["count"] == 1


def test_foreign_key_style_id_column_is_not_flagged_for_outliers():
    # host_id-style: numeric, ends in "_id", high cardinality, some
    # repeats (a host with 2 listings) — every value is an arbitrary
    # large-ish number, so a naive IQR pass finds "outliers" that mean
    # nothing. Found on a real 49k-row dataset before this exclusion
    # existed: host_id got flagged with 1,526 "outliers".
    host_ids = [1001, 1002, 1003, 1001, 1004, 1005, 1006, 1007, 9999999]
    df = pd.DataFrame({"host_id": host_ids, "n": range(len(host_ids))})
    _, report = clean(df)

    outlier_cols = [f["column"] for f in report["flagged"] if f["type"] == "outliers"]
    assert "host_id" not in outlier_cols


def test_constant_column_is_flagged():
    df = pd.DataFrame({"fiscal_year": [2024, 2024, 2024], "value": [1, 2, 3]})
    _, report = clean(df)

    assert any(f["type"] == "constant_column" and f["column"] == "fiscal_year"
               for f in report["flagged"])


def test_fully_empty_columns_and_rows_are_dropped():
    df = pd.DataFrame({
        "a": [1, 2, 3],
        "empty_col": [np.nan, np.nan, np.nan],
    })
    df.loc[len(df)] = [np.nan, np.nan]  # an all-empty row
    cleaned, report = clean(df)

    assert "empty_col" not in cleaned.columns
    assert len(cleaned) == 3
    assert any(a["type"] == "drop_empty_columns" for a in report["actions"])
    assert any(a["type"] == "drop_empty_rows" for a in report["actions"])


def test_clean_data_on_already_clean_input_makes_no_changes():
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    cleaned, report = clean(df)

    assert len(cleaned) == 3
    assert report["actions"] == []
    assert report["flagged"] == []
