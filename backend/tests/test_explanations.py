import json

import numpy as np
import pandas as pd
import pytest

from app.analysis import analyze
from app.explanations import schema_description
from app.report import render_html, render_markdown


def run(df, goal="", target=None):
    source = {"filename":"students.csv", "is_demo":False, "analyzed_rows":len(df),
              "total_rows":len(df), "sampled":False, "sheet":None, "notes":[]}
    return analyze(df.copy(), source, goal, target, lambda *args:None)


def students():
    rng = np.random.default_rng(17)
    n = 60
    # A meaningful result appears after 60 irrelevant fields, as in wide course tables.
    df = pd.DataFrame({"student_id":[f"A{i}" for i in range(n)], "gpa_rank":np.arange(1,n+1),
                       "gender":["private-a","private-b"]*(n//2)})
    for i in range(60):
        df[f"course_{i}"] = rng.integers(60,101,n)
    df["internship"] = 100-np.arange(n)/2
    df["employment_ability_scale"] = df["internship"] + rng.normal(0,.2,n)
    return df


def test_wide_table_scans_tail_fields_and_prioritizes_target_charts():
    result, aggregate = run(students(), "理解就业能力与实习的关系")
    brief = result["brief"]
    assert brief["focus"]["column"] == "employment_ability_scale"
    assert brief["coverage"]["numeric_fields_scanned"] == 63
    assert brief["coverage"]["relationships_evaluated"] == 62
    pair = next(f for f in brief["findings"] if "internship" in f["fields"])
    assert pair["n"] == 60 and "不是实际就业率" in brief["focus"]["meaning"]
    assert pair["chart_ids"]
    assert "internship" in result["eda"]["coverage"]["selected_numeric_fields"]
    assert "private-a" not in json.dumps(aggregate,ensure_ascii=False)
    assert "private-b" not in json.dumps(aggregate,ensure_ascii=False)
    assert "student_id" not in [p["field"] for p in aggregate["explanation_evidence"]["target_relationships"]]
    assert len(result["charts"]) <= 60


def test_rank_direction_and_component_caveat_are_explicit():
    result, _ = run(students(), "理解学业表现")
    brief = result["brief"]
    assert brief["focus"]["column"] == "gpa_rank"
    assert brief["focus"]["lower_is_better"] is True
    finding = next(f for f in brief["findings"] if "internship" in f["fields"])
    assert "排名通常更靠前" in finding["title"]
    assert "共享计算来源" in finding["explanation"]
    assert not any(f["field"] == "gpa_rank" for f in result["eda"]["coverage"]["excluded_fields"])


def test_pairwise_missingness_and_ties_match_independent_rank_calculation():
    df = students()
    df.loc[:8,"internship"] = None
    df.loc[9:15,"employment_ability_scale"] = None
    result, aggregates = run(df, target="employment_ability_scale")
    pair = next(p for p in aggregates["explanation_evidence"]["target_relationships"] if p["field"] == "internship")
    complete = df[["internship","employment_ability_scale"]].dropna()
    assert pair["n"] == len(complete)
    assert pair["rho"] == pytest.approx(complete.iloc[:,0].rank().corr(complete.iloc[:,1].rank()))


def test_tiny_or_unrelated_samples_abstain_instead_of_claiming_a_driver():
    df = pd.DataFrame({"score":[-1.,0.,1.]*4,"feature":[1.,-2.,1.]*4})
    result, _ = run(df, target="score")
    assert not any(f["kind"] == "relationship" for f in result["brief"]["findings"])
    assert any(f["kind"] == "insufficient" for f in result["brief"]["findings"])


def test_schema_suggestions_are_local_and_names_need_not_be_typed():
    schema = schema_description(students(), {"notes":[]})
    assert schema["suggested_target"] == "gpa_rank"
    assert [q["target"] for q in schema["questions"]] == ["gpa_rank","employment_ability_scale"]
    assert not next(c for c in schema["columns"] if c["name"] == "student_id")["selectable"]
    assert next(c for c in schema["columns"] if c["name"] == "gpa_rank")["selectable"]


def test_exports_put_conclusions_before_methods_and_escape_dataset_text():
    df = pd.DataFrame({"category":["<img src=x onerror=alert(1)>"]*20+["other"]*20})
    result,_ = run(df)
    md = render_markdown(result, "question")
    html = render_html(result, md, "question")
    assert md.index("## 先看结论") < md.index("## 来源与范围")
    assert html.index("<h2>先看结论</h2>") < html.index("<h2>数据洞察</h2>")
    assert "<img src=x" not in html and "&lt;img src=x" in html


def test_all_constant_input_and_old_reports_remain_readable():
    result,_ = run(pd.DataFrame({"constant":[1]*25}))
    assert result["brief"]["findings"][0]["kind"] == "insufficient"
    result.pop("brief")
    assert "先看结论" not in render_markdown(result, "")
    render_html(result, "", "")


def test_question_comparison_and_cross_section_have_exact_denominators():
    n = 80
    index = np.arange(n)
    df = pd.DataFrame({"score":index.astype(float), "first":index+.1*np.sin(index),
                       "second":np.roll(index,12).astype(float)})
    result,_ = run(df, "compare first and second", "score")
    assert "相比" in result["brief"]["headline"]
    contrast = next(f for f in result["brief"]["findings"] if f["kind"] == "contrast")
    field = contrast["fields"][0]
    complete = df[[field,"score"]].dropna()
    high = complete[field].ge(complete[field].quantile(.75))
    both = high & complete.score.le(complete.score.quantile(.25))
    assert f"交叉计数={int(both.sum())}/{int(high.sum())}" in contrast["evidence"]
    assert contrast["n"] == len(complete)
