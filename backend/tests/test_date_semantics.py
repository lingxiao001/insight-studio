import pandas as pd

from app.analysis import analyze


def test_snapshot_date_buckets_are_not_labeled_historical_price_trends():
    df = pd.DataFrame({"last_review":pd.to_datetime(["2019-01-01","2019-01-02",None,"2019-01-04",None]),
                       "price":[100.,200.,300.,200.,400.]})
    original = df.copy(deep=True)
    source = {"filename":"real-upload.csv","is_demo":False,"analyzed_rows":5,"total_rows":5,
              "sampled":False,"sheet":None,"notes":[]}
    result,aggregates = analyze(df,source,"last_review是快照最近评论日，不是历史价格。","price",lambda *args:None)
    pd.testing.assert_frame_equal(df,original)
    assert result["source"]["is_demo"] is False and result["overview"]["rows"] == 5
    study = result["eda"]["time"][0]
    notes = " ".join(study["notes"])
    assert "日期有效记录 3 / 全体 5 行" in notes and "缺失日期的 2 行" in notes
    assert "当前记录按日期条件" in notes and "不能默认解释为指标的历史轨迹" in notes
    line = next(chart for chart in result["charts"] if chart["type"] == "line")
    assert "按last_review分桶的均值/中位数" in line["title"] and "趋势" not in line["title"]
    assert "不默认代表历史观测" in line["description"]
    evidence = aggregates["eda_evidence"]["time"][0]
    assert evidence["notes"] == study["notes"]
    assert sum(point["rows"] for point in study["points"]) == 3


def test_221_categories_are_selected_but_true_high_cardinality_names_are_not():
    count = 2210
    df = pd.DataFrame({"neighbourhood":[f"area-{i%221}" for i in range(count)],
        "host_name":[f"host-{i%1105}" for i in range(count)],
        "name":[f"listing-{i}" for i in range(count)],"price":[100.+i%10 for i in range(count)]})
    source = {"filename":"raw.csv","is_demo":False,"analyzed_rows":count,"total_rows":count,"sampled":False,"sheet":None,"notes":[]}
    result,_ = analyze(df,source,"按地区比较price","price",lambda *args:None)
    fields = result["eda"]["coverage"]["selected_categorical_fields"]
    assert fields == ["neighbourhood"]
    study = result["eda"]["groups"][0]
    assert study["category"] == "neighbourhood" and study["metric"] == "price"
    assert len(study["groups"]) == 8 and study["omitted_groups"] == 213
    assert len(result["eda"]["categories"][0]["top_values"]) == 12


def test_model_group_evidence_covers_each_category_target_before_secondary_metrics():
    df = pd.DataFrame({"price":[100.+i%13 for i in range(120)],"secondary":[1.+i%7 for i in range(120)],
        **{f"category_{j}":[f"private-group-{i%(j+2)}" for i in range(120)] for j in range(5)}})
    source = {"filename":"raw.csv","is_demo":False,"analyzed_rows":120,"total_rows":120,"sampled":False,"sheet":None,"notes":[]}
    result,aggregates = analyze(df,source,"比较price","price",lambda *args:None)
    assert len(result["eda"]["groups"]) == 9
    sent = aggregates["eda_evidence"]["groups"]
    assert len(sent) == 5 and all(study["metric"] == "price" for study in sent)
    assert {study["category"] for study in sent} == {f"category_{j}" for j in range(5)}
    assert all("label" not in group for study in sent for group in study["groups"])
