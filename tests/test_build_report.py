"""Tests for scripts/build_report.py.

Focused on the chart-selection logic (references/chart_selection.md
documents the reasoning) rather than pixel-level chart output — what
matters is that the right column ends up in the right bucket, not what
the PNG looks like.
"""
import pandas as pd

from scripts.build_report import build_charts, render_narrative_html, split_id_like_columns


def test_id_like_column_is_detected_by_uniqueness_not_name():
    # Every value distinct -> ID-like, regardless of what it's called.
    df = pd.DataFrame({
        "reference_code": [101, 102, 103, 104, 105],
        "score": [10, 12, 9, 11, 10],
    })
    real, id_like = split_id_like_columns(df, ["reference_code", "score"])

    assert id_like == ["reference_code"]
    assert real == ["score"]


def test_low_cardinality_numeric_column_is_not_treated_as_id():
    # Pclass-like column: numeric, repeats a lot -> a real measurement.
    df = pd.DataFrame({"pclass": [1, 2, 3, 1, 2, 3, 1, 1]})
    real, id_like = split_id_like_columns(df, ["pclass"])

    assert real == ["pclass"]
    assert id_like == []


def test_build_charts_excludes_id_column_from_numeric_charts():
    df = pd.DataFrame({
        "passenger_id": list(range(1, 21)),
        "age": [22, 38, 26, 35, 35, 27, 54, 2, 27, 14,
                4, 58, 20, 39, 14, 55, 2, 31, 35, 34],
        "fare": [7.25, 71.28, 7.92, 53.1, 8.05, 8.46, 51.86, 21.08, 11.13, 30.07,
                 16.7, 26.55, 8.05, 31.27, 7.85, 16.0, 29.12, 13.0, 18.0, 7.22],
    })
    charts, id_like = build_charts(df)

    titles = [c["title"] for c in charts]
    assert "passenger_id" in id_like
    assert not any("passenger_id" in t for t in titles)
    assert any("age" in t for t in titles)
    assert any("fare" in t for t in titles)


def test_build_charts_handles_dataframe_with_no_numeric_columns():
    df = pd.DataFrame({"category": ["a", "b", "a", "c", "b", "a"]})
    charts, id_like = build_charts(df)  # should not raise

    assert id_like == []
    assert any("category" in c["title"] for c in charts)


def test_render_narrative_html_empty_when_no_file_given():
    assert render_narrative_html(None) == ""


def test_render_narrative_html_wraps_content_in_card(tmp_path):
    narrative_file = tmp_path / "narrative.html"
    narrative_file.write_text("<p>Something worth noting.</p>", encoding="utf-8")

    html = render_narrative_html(str(narrative_file))

    assert "Key findings" in html
    assert "Something worth noting." in html


def test_render_narrative_html_empty_file_renders_nothing(tmp_path):
    narrative_file = tmp_path / "empty.html"
    narrative_file.write_text("   ", encoding="utf-8")

    assert render_narrative_html(str(narrative_file)) == ""
