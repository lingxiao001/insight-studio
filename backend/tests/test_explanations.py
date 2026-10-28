import json

import numpy as np
import pandas as pd
import pytest

from app.analysis import analyze
from app.explanations import choose_focus, schema_description
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


def test_named_weak_relationship_is_answered_before_unrequested_strong_pair():
    df = pd.DataFrame({"score": [-1., 0., 1.] * 20,
                       "weak": [1., -2., 1.] * 20,
                       "unrequested": [-1.1, 0.1, 1.1] * 20})
    result, aggregates = run(df, "请解释 weak 与 score 的关系", "score")
    brief = result["brief"]
    answer = brief["question_answers"][0]
    assert answer["fields"] == ["weak", "score"]
    assert answer["status"] == "partial" and answer["rho"] == pytest.approx(0)
    assert "未显示weak与score之间清晰的单调关系" in brief["answer"]
    assert "unrequested" not in brief["headline"]
    assert "不等于二者无关" in answer["explanation"]
    assert aggregates["explanation_evidence"]["question_answers"][0]["status"] == "partial"


def test_each_named_question_survives_small_samples_and_constant_fields():
    n = 60
    df = pd.DataFrame({"score": np.sin(np.arange(n)),
                       "sparse": [1., 3., 2., 4., 6., 5., 7.] + [np.nan] * (n-7),
                       "constant": [4.] * n})
    result, _ = run(df, "sparse 与 constant 分别能说明什么？", "score")
    answers = result["brief"]["question_answers"]
    assert [a["fields"][0] for a in answers] == ["sparse", "constant"]
    assert all(a["status"] == "insufficient" for a in answers)
    assert answers[0]["n"] == 7 and "n=7/60" in answers[0]["evidence"]
    assert answers[1]["n"] == 60 and answers[1]["rho"] is None
    assert "常量" in answers[1]["explanation"]
    assert result["brief"]["coverage"]["questions_answered"] == 2


@pytest.mark.parametrize("target,values", [("constant", [1.] * 30),
                                          ("sparse", [1., 3., 2.] + [np.nan] * 27)])
def test_unanalyzable_explicit_focus_is_retained_and_answered(target, values):
    df = pd.DataFrame({target: values, "category": ["a", "b"] * 15})
    result, _ = run(df, target=target)
    brief = result["brief"]
    assert brief["focus"]["column"] == target and brief["focus"]["analyzable"] is False
    assert brief["question_answers"][0]["status"] == "insufficient"
    assert not any(f["kind"] == "composition" for f in brief["findings"])
    schema = schema_description(df, {"notes": []})
    selected = next(c for c in schema["columns"] if c["name"] == target)
    assert not selected["selectable"] and selected["selection_note"]


def test_rank_as_explanatory_field_uses_rank_direction_and_measurement_limits():
    n = 60
    df = pd.DataFrame({"gpa_rank": np.arange(1, n+1),
                       "employment_ability_scale": 100 - np.arange(n) * .3 + np.sin(np.arange(n)) * .01})
    result, _ = run(df, "gpa_rank 与就业能力自评有什么关系？", "employment_ability_scale")
    item = result["brief"]["question_answers"][0]
    assert "GPA排名更靠前" in item["answer"]
    assert "就业能力自评通常较高" in item["answer"]
    assert "不是实际就业率" in result["brief"]["answer"]
    assert "共享评分来源" in item["caveat"]


def test_shared_scale_sources_are_caveated_and_ascii_names_do_not_substring_match():
    n = 60
    df = pd.DataFrame({"employment_ability_scale": np.sin(np.arange(n)),
                       "active_knowledge_acquisition_scale": np.sin(np.arange(n)) + .01,
                       "a": np.cos(np.arange(n))})
    result, _ = run(df, "主动学习与就业能力的关系；explain data", "employment_ability_scale")
    answers = result["brief"]["question_answers"]
    assert len(answers) == 1 and answers[0]["fields"][0] == "active_knowledge_acquisition_scale"
    assert "共享作答者、题目或计分方法" in answers[0]["caveat"]
    assert "先核对是否独立采集" in answers[0]["explanation"]
    assert "a" not in [item["fields"][0] for item in answers]


def test_focus_selection_respects_ascii_field_boundaries():
    df = pd.DataFrame({"a": np.sin(np.arange(30)), "score": np.cos(np.arange(30))})
    assert choose_focus(df, "explain data")[0] == "score"
    assert choose_focus(df, "explain a")[0] == "a"


def test_question_answers_and_specific_next_steps_are_in_both_exports():
    result, _ = run(students(), "实习与就业能力的关系", "employment_ability_scale")
    md = render_markdown(result, "")
    html = render_html(result, md, "")
    for text in (md, html):
        assert "对问题逐项回答" in text
        assert "实习列记录的是成绩" in text
        assert "下一步：" in text
    assert html.index("对问题逐项回答") < html.index("先看懂就业能力自评")


def test_bounded_question_answers_disclose_unanswered_comparisons():
    n = 40
    df = pd.DataFrame({"score": np.sin(np.arange(n))})
    for index in range(13):
        df[f"x{index}"] = np.cos(np.arange(n) + index)
    result, _ = run(df, " ".join(f"x{index}" for index in range(13)), "score")
    brief = result["brief"]
    assert len(brief["question_answers"]) == 12
    assert brief["coverage"]["questions_detected"] == 13
    assert brief["coverage"]["questions_omitted"] == 1
    assert any("其余1项尚未回答" in caveat for caveat in brief["caveats"])
    finding_ids = {item["id"] for item in brief["findings"]}
    assert all(set(item["finding_ids"]) <= finding_ids for item in brief["question_answers"])


def test_named_category_distinguishes_method_scope_from_sample_shortage():
    df = pd.DataFrame({"score": np.sin(np.arange(60)), "gender": ["a", "b"] * 30})
    result, aggregates = run(df, "性别与成绩有什么关系", "score")
    item = result["brief"]["question_answers"][0]
    assert item["status"] == "partial" and item["status_label"] == "当前方法不适用"
    assert item["n"] == 60 and item["rho"] is None
    assert "未做类别间差异比较" in item["explanation"]
    assert "样本不足" not in item["answer"] and "样本不足" not in item["explanation"]
    assert aggregates["explanation_evidence"]["question_answers"][0]["method"] == "not_applicable"
