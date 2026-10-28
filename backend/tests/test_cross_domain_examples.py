"""Acceptance checks against independently reviewed real-source aggregates."""
import pytest

from app.public_examples import load_example
from app.report import render_markdown, render_html


@pytest.mark.parametrize("slug,rows,fields,events", [
    ("hotel-city-cancellations", 79330, 17, 33102),
    ("hotel-resort-cancellations", 40060, 17, 11122),
    ("credit-card-default", 30000, 24, 6636),
    ("heart-failure-followup", 299, 13, 96),
    ("netflix-catalog", 8807, 4, 6131),
])
def test_public_case_population_and_event_denominators(slug, rows, fields, events):
    item = load_example(slug)
    result = item["result"]
    assert result["overview"]["rows"] == rows
    assert result["overview"]["columns"] == fields
    assert result["source"]["sampled"] is False
    trace = result["charts"][0]["figure"]["data"][0]
    assert trace["y"] == [events, rows-events]
    assert result["preview"] == {"columns": [], "rows": []}
    assert result["columns"] == []
    assert result["agent"]["model"] is None
    for question in result["brief"]["question_answers"]:
        groups = question.get("groups", [])
        for group in groups:
            assert group["rate_pct"] == pytest.approx(group["events"] / group["n"] * 100)
            assert group["supported"] == (group["n"] >= 20)
        if groups:
            assert sum(group["n"] for group in groups) == question["n"]
        if question.get("method") == "event_rate":
            compared = [g["rate_pct"] for g in groups if g["supported"]]
            assert question["difference_pp"] == pytest.approx(max(compared) - min(compared))


def test_source_specific_interpretation_boundaries_survive_public_export():
    heart = load_example("heart-failure-followup")["result"]
    time = next(q for q in heart["brief"]["question_answers"] if "time" in q["fields"])
    assert time["method"] == "excluded"
    assert not time.get("groups")
    assert all("time" not in chart["fields"] for chart in heart["charts"])
    assert "随访" in time["explanation"]
    credit = load_example("credit-card-default")["result"]
    pay = next(q for q in credit["brief"]["question_answers"] if "PAY_0" in q["fields"])
    group = next(g for g in pay["groups"] if g["label"].startswith("2（"))
    assert (group["events"], group["n"]) == (1844, 2667)
    assert "-2（原字典未说明）" in {g["label"] for g in pay["groups"]}
    for result in (heart, credit):
        md = render_markdown(result, result["brief"]["goal"])
        html = render_html(result, md, result["brief"]["goal"])
        for text in (md, html):
            assert "CC BY 4.0" in text
            assert "分母" in text
            assert "不能" in text
        assert "群体" in md or "个人" in md


def test_movie_minutes_are_not_series_seasons_or_imputed_ratings():
    item = load_example("netflix-movie-length")
    result = item["result"]
    assert result["overview"]["rows"] == 6131
    assert result["overview"]["columns"] == 4
    histogram = result["charts"][0]["figure"]["data"][0]
    assert sum(histogram["y"]) == 6128
    overview = next(f for f in result["brief"]["findings"] if f["kind"] == "overview")
    assert overview["n"] == 6128
    assert "中位数=98" in overview["evidence"]
    assert "Q1=87" in overview["evidence"] and "Q3=114" in overview["evidence"]
    assert "3条" in item["provenance"]["preprocessing"]
    assert result["brief"]["focus"]["column"] == "movie_minutes"


def test_new_snapshots_have_only_bounded_aggregate_charts_and_public_sources():
    for slug in ("hotel-city-cancellations", "hotel-resort-cancellations", "credit-card-default",
                 "heart-failure-followup", "netflix-catalog", "netflix-movie-length"):
        item = load_example(slug)
        provenance = item["provenance"]
        assert "quality_score" not in item["result"]["overview"]
        assert "duplicate_rows" not in item["result"]["overview"]
        assert len(provenance["source_sha256"]) == 64
        assert provenance["dataset_version"] in (1, 5)
        assert provenance["kaggle_url"].startswith("https://www.kaggle.com/datasets/")
        for chart in item["result"]["charts"]:
            assert not {"ID", "show_id", "title", "cast", "director", "time"} & set(chart["fields"])
            for trace in chart["figure"]["data"]:
                assert trace["type"] == "bar"
                assert len(trace["x"]) == len(trace["y"]) <= 12
                assert not {"customdata", "text", "hovertext", "ids"} & trace.keys()


def test_projection_does_not_claim_duplicate_records_or_poor_source_quality():
    result = load_example("netflix-catalog")["result"]
    md = render_markdown(result, result["brief"]["goal"])
    html = render_html(result, md, result["brief"]["goal"])
    for text in (md, html):
        assert "同值记录不等于同一业务记录" in text
        assert "完全重复行" not in text
        assert "启发式质量评分" not in text
        assert "质量评分 =" not in text
