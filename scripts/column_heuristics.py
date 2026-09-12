"""column_heuristics.py — shared logic for telling an identifier column
apart from a real measurement.

Both clean_data.py (should it flag "outliers" in this column?) and
build_report.py (should it chart this column's distribution?) need the
same answer to "is this actually an ID, not data worth analyzing
numerically" — so the logic lives in one place rather than being
maintained twice and drifting apart.
"""
import re

import pandas as pd

# Matches "id", "host_id", "customer_id" etc. — deliberately conservative
# (requires the whole name or a "_id" suffix) so it doesn't misfire on
# words that merely contain "id" ("valid", "grid", "avoid", ...).
ID_NAME_PATTERN = re.compile(r"(^|_)id$", re.IGNORECASE)

# A column doesn't have to be perfectly unique to be an identifier — a
# foreign-key-style column like host_id repeats once per extra row that
# entity owns (one host, several listings), so it's high-cardinality
# without ever being 100% unique. Threshold picked to catch that pattern
# without flagging a genuine measurement that just happens to vary a lot.
ID_NAME_CARDINALITY_THRESHOLD = 0.5


def split_id_like_columns(df: pd.DataFrame, numeric_cols: list[str]) -> tuple[list[str], list[str]]:
    """Split numeric_cols into (real measurements, identifier-like columns).

    A column earns "identifier" one of two ways:

    1. Every non-null value is unique (PassengerId, an order number) —
       detected structurally, so it works regardless of naming convention
       or language.
    2. The name looks like a foreign-key id (ends in "_id") AND
       cardinality is high but not perfect — a host_id repeats exactly as
       many times as that host has listings, so it will never be 100%
       unique the way a row's own id is, but it's still an identifier,
       not a measurement. This one DOES rely on naming convention, on
       purpose: uniqueness alone can't distinguish "host_id" from a real
       repeated-but-varying measurement. Found missing on a real 49k-row
       dataset, where host_id got histogrammed and polluted a correlation
       heatmap before this rule existed.
    """
    id_like, real = [], []
    for c in numeric_cols:
        non_null = df[c].dropna()
        if len(non_null) <= 1:
            real.append(c)
            continue
        nunique = non_null.nunique()
        is_fully_unique = nunique == len(non_null)
        looks_like_id_by_name = bool(ID_NAME_PATTERN.search(str(c)))
        is_high_cardinality = (nunique / len(non_null)) > ID_NAME_CARDINALITY_THRESHOLD
        if is_fully_unique or (looks_like_id_by_name and is_high_cardinality):
            id_like.append(c)
        else:
            real.append(c)
    return real, id_like
