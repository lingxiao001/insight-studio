import json

import numpy as np
import pandas as pd
import pytest

from app.analysis import analyze
from app.ingest import demo_dataset
from app.report import render_markdown, render_html


def run(df, target=None):
    source = {"filename":"test.csv","is_demo":False,"analyzed_rows":len(df),"total_rows":len(df),
              "sampled":False,"sheet":None,"notes":[]}
    return analyze(df, source, "探索关注字段", target, lambda *args:None)


def test_demo_deep_coverage_has_seven_topics_and_distinct_evidence():
    df,source = demo_dataset()
    result,aggregates = analyze(df,source,"探索销售额","销售额",lambda *args:None)
    eda = result["eda"]
    assert eda["version"] == 2 and 35 <= len(result["charts"]) <= 55
    assert len(eda["sections"]) == 7 and all(s["chart_ids"] for s in eda["sections"])
    ids = {c["id"] for c in result["charts"]}
    assert set(cid for s in eda["sections"] for cid in s["chart_ids"]) == ids
    assert eda["coverage"]["chart_count"] == len(ids) <= 60
    assert len(eda["distributions"]) == 7 and len(eda["groups"]) >= 6 and len(eda["time"]) >= 3
    assert len(result["insights"]) > 10
    assert any(item["field"] == "订单编号" for item in eda["coverage"]["excluded_fields"])
    json.dumps(result,allow_nan=False)
    encoded = json.dumps(aggregates,ensure_ascii=False,allow_nan=False)
    for raw_category in ["华东","华南","数码配件","线上商城","ORD-100001"]:
        assert raw_category not in encoded
    assert aggregates["eda_evidence"]["groups"][0]["groups"][0]["group_id"].startswith("G")


def test_spearman_uses_pairwise_complete_ranks_with_missing_and_ties():
    df = pd.DataFrame({"x":[4.,1.,2.,2.,8.,7.,None,12.],"y":[1.,8.,3.,3.,6.,None,9.,2.]})
    result,_ = run(df,"x")
    pair = result["eda"]["correlations"]["spearman"][0]
    complete = df.dropna()
    expected = complete["x"].rank().corr(complete["y"].rank())
    assert pair["n"] == len(complete) and pair["r"] == pytest.approx(expected)


def test_groups_include_reproducible_n_median_quartiles_and_local_aliases():
    df = pd.DataFrame({"region":["private-east"]*8+["private-west"]*8+["small"]*2,
                       "measure":[1.,3.,2.,8.,4.,7.,6.,5.]*2+[11.,12.]})
    result,aggregates = run(df,"measure")
    study = result["eda"]["groups"][0]
    assert study["omitted_groups"] == 1
    for group in study["groups"]:
        values = df.loc[df.region == group["label"],"measure"]
        assert group["n"] == len(values) == 8
        assert group["mean"] == values.mean() and group["median"] == values.median()
        assert group["q25"] == values.quantile(.25) and group["q75"] == values.quantile(.75)
        assert group["group_id"].startswith("G")
    sent = json.dumps(aggregates,ensure_ascii=False)
    assert "private-east" not in sent and "private-west" not in sent


def test_time_keeps_date_window_and_true_gap_with_missing_metric_edges():
    df = pd.DataFrame({"date":pd.to_datetime(["2026-01-01","2026-01-02","2026-01-04","2026-01-05"]),
                       "value":[None,2.,4.,None]})
    result,_ = run(df,"value")
    study = result["eda"]["time"][0]
    assert study["total_buckets"] == 5 and study["empty_buckets"] == 1
    assert study["coverage_pct"] == 80
    assert study["points"][0]["rows"] == 1 and study["points"][0]["n"] == 0
    assert study["points"][0]["mean"] is None and study["points"][0]["sum"] is None
    assert study["points"][2]["rows"] == 0 and study["points"][2]["sum"] is None
    assert study["points"][-1]["rows"] == 1 and study["points"][-1]["sum"] is None


def test_explicit_second_date_field_is_prioritized():
    df = pd.DataFrame({"first_date":pd.date_range("2026-01-01",periods=6),
                       "focus_date":pd.date_range("2026-05-01",periods=6),"value":[1.,3.,2.,5.,4.,7.]})
    result,_ = run(df,"focus_date")
    assert result["eda"]["coverage"]["selected_datetime_fields"] == ["focus_date"]
    assert result["eda"]["target"]["kind"] == "datetime"
    assert result["eda"]["target"]["chart_ids"]


def test_tiny_values_retain_precision_in_profiles_box_and_outliers():
    df = pd.DataFrame({"tiny":[1e-8,2e-8,3e-8,4e-8,5e-8,20e-8]})
    result,aggregates = run(df,"tiny")
    d = result["eda"]["distributions"][0]
    assert d["p25"] == pytest.approx(df.tiny.quantile(.25),rel=1e-12)
    assert d["iqr"] > 0 and d["outlier_count"] == 1
    assert result["columns"][0]["mean"] == pytest.approx(df.tiny.mean(),rel=1e-12)
    box = next(c for c in result["charts"] if c["type"] == "box")["figure"]["data"][0]
    assert box["q1"][0] > 0 and box["lowerfence"][0] == 1e-8
    assert aggregates["outliers"]["tiny"]["upper"] > 0


def test_large_values_have_finite_scale_invariant_higher_moments():
    values = pd.Series([-4.,-1.,0.,0.,0.,2.,3.])
    result,_ = run(pd.DataFrame({"huge":values*1e100}),"huge")
    d = result["eda"]["distributions"][0]
    assert d["skew"] == pytest.approx(values.skew())
    assert d["kurtosis"] == pytest.approx(values.kurt())
    # Floating representation can leave a tiny residual relative to 1e100;
    # this is distinct from higher-moment overflow and must not be rounded away.
    assert abs(d["mean"]) / 1e100 < 1e-15 and d["median"] == 0
    assert values.mean() == values.median() == 0
    assert not any("呈正态" in insight["body"] or "呈对称" in insight["body"] for insight in result["insights"])
    json.dumps(result,allow_nan=False)


def test_long_category_and_field_labels_keep_unique_plot_identities():
    prefix = "long-label-"*7
    first,second = prefix+"A",prefix+"B"
    df = pd.DataFrame({"category":[first]*8+[second]*8,
        first:[1.,3.,2.,4.,6.,5.,8.,7.]*2,second:[8.,6.,7.,3.,5.,4.,2.,1.]*2})
    result,_ = run(df,first)
    bar = next(c for c in result["charts"] if c["type"] == "bar")["figure"]["data"][0]
    assert len(set(bar["x"])) == 2
    heatmap = next(c for c in result["charts"] if c["type"] == "heatmap")["figure"]["data"][0]
    assert set(heatmap["x"]) == {first,second}
    assert len(result["eda"]["categories"][0]["top_values"]) == 2


def test_boolean_target_gets_balance_and_group_evidence_without_numeric_encoding():
    df = pd.DataFrame({"Survived":[True]*10+[False]*10,"measure":[1.,3.,2.,5.,4.,7.,6.,9.,8.,11.]*2})
    result,_ = run(df,"Survived")
    eda = result["eda"]
    assert eda["target"]["kind"] == "boolean" and eda["target"]["chart_ids"]
    assert eda["coverage"]["selected_categorical_fields"][0] == "Survived"
    assert any(study["category"] == "Survived" for study in eda["groups"])
    assert not any("Survived" in {p["a"],p["b"]} for p in eda["correlations"]["pearson"])


def test_unusable_small_data_has_reasons_and_no_fabricated_comparisons():
    result,_ = run(pd.DataFrame({"id":[1,2,3],"empty":[None]*3,"constant":[2]*3}),"constant")
    assert not result["eda"]["groups"] and not result["eda"]["time"]
    assert not result["eda"]["correlations"]["pearson"]
    assert {"distributions","relationships","groups","time","target"} <= {r["section"] for r in result["eda"]["coverage"]["not_applicable"]}
    assert all(c["section"] == "quality" for c in result["charts"])


def test_reports_include_topic_organization_evidence_and_lazy_offline_charts():
    df,source = demo_dataset()
    result,_ = analyze(df,source,"关注销售额","销售额",lambda *args:None)
    markdown = render_markdown(result,"关注销售额")
    html = render_html(result,markdown,"关注销售额")
    for text in ["深度 EDA 覆盖与选择","分组证据","时间证据","Spearman","G01","算术和"]:
        assert text in markdown and text in html
    assert html.count('class="chart-canvas"') == len(result["charts"])
    assert "IntersectionObserver" in html and "prepare-print" in html and "Promise.allSettled" in html
    assert '<script src=' not in html


def test_chart_ceiling_keeps_every_topic_and_target_when_candidates_exceed_sixty():
    import plotly.graph_objects as go
    from app.deep_eda import Charts, TOPICS
    builder = Charts()
    for key,_,_ in TOPICS:
        for i in range(12):
            builder.add(key,f"chart {i}","description","bar",go.Figure(go.Bar(x=[1],y=[2])))
    selected = builder.selected()
    assert len(selected) == len({c["id"] for c in selected}) == 60
    assert {c["section"] for c in selected} == {key for key,_,_ in TOPICS}
    assert [c["id"] for c in selected] == [c["id"] for c in builder.selected()]


def test_old_report_with_explicit_null_eda_still_exports():
    result,_ = run(pd.DataFrame({"value":[1.,3.,2.,4.,6.,5.]}))
    result["eda"] = None
    markdown = render_markdown(result,"")
    assert "图表目录" in markdown
    assert "离线可用分析报告" in render_html(result,markdown)
