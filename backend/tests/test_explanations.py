import json

import numpy as np
import pandas as pd
import pytest

from app.analysis import analyze
from app.explanations import choose_focus, schema_description
from app.report import render_html, render_markdown


def run(df, goal="", target=None, context=None):
    source = {"filename":"students.csv", "is_demo":False, "analyzed_rows":len(df),
              "total_rows":len(df), "sampled":False, "sheet":None, "notes":[]}
    if context is not None:
        source["analysis_context"] = context
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


def test_named_category_compares_numeric_means_and_medians_with_exact_support():
    df = pd.DataFrame({"score": np.sin(np.arange(60)), "gender": ["a", "b"] * 30})
    result, aggregates = run(df, "性别与成绩有什么关系", "score")
    item = result["brief"]["question_answers"][0]
    assert item["status"] == "supported" and item["method"] == "group_summary"
    assert item["n"] == 60 and item["rho"] is None
    assert "中位数" in item["explanation"] and "均值" in item["answer"]
    assert sorted(g["n"] for g in item["groups"]) == [30, 30]
    assert "样本不足" not in item["answer"] and "样本不足" not in item["explanation"]
    assert aggregates["explanation_evidence"]["question_answers"][0]["method"] == "group_summary"


def test_event_rate_requires_explicit_encoding_and_uses_percentage_points():
    df = pd.DataFrame({"outcome": [0]*10+[1]*30+[0]*30+[1]*10,
                       "region": ["private-region-a"]*40+["private-region-b"]*40})
    context = {"domain": "finance", "event": {"column": "outcome", "value": 0, "label": "已记录违约"},
               "field_definitions": {"outcome": {"label": "历史记录状态", "meaning": "此样本的历史状态"}}}
    result, aggregate = run(df, "region 与 outcome", "outcome", context)
    item = result["brief"]["question_answers"][0]
    assert item["method"] == "event_rate" and item["status"] == "supported"
    assert result["brief"]["headline"] == "按region分组，已记录违约比例相差50.0个百分点"
    assert item["difference_pp"] == pytest.approx(50)
    assert sorted((g["events"], g["n"]) for g in item["groups"]) == [(10,40),(30,40)]
    assert "个百分点" in item["answer"] and "30/40" in item["answer"]
    assert "投资建议" in item["caveat"] and "不能认定因果" in item["caveat"]
    assert result["brief"]["focus"]["label"] == "历史记录状态"
    assert aggregate["explanation_evidence"]["event"]["count"] == 40
    assert "private-region" not in json.dumps(aggregate, ensure_ascii=False)
    assert "G01" in json.dumps(aggregate)


def test_binary_codes_are_not_silently_given_event_meanings_and_invalid_metadata_abstains():
    df = pd.DataFrame({"outcome": [0,1]*40, "category": ["a"]*40+["b"]*40})
    for context in ({}, {"event": {"column": "outcome", "value": 2, "label": "发生死亡"}}):
        result, aggregate = run(df, "category 与 outcome", "outcome", context)
        brief = result["brief"]
        assert brief["focus"]["kind"] == "categorical"
        assert "不会把1自动解释" in brief["findings"][0]["explanation"]
        assert brief["question_answers"][0]["method"] == "category_share"
        assert "event" not in aggregate["explanation_evidence"]
        assert "发生死亡" not in brief["answer"]
    # Context is request-local, including labels and business semantics.
    assert "原始" in result["brief"]["answer"]


def test_event_rates_keep_missing_rows_small_groups_and_duplicate_indices_exact():
    df = pd.DataFrame({"outcome": [1]*20+[0]*20+[1]*4+[None]*6,
                       "group": ["a"]*20+["b"]*20+["small"]*4+["missing"]*6}, index=[0]*50)
    context = {"event": {"column": "outcome", "value": 1, "label": "目标事件"}}
    result, _ = run(df, "group 与 outcome", "outcome", context)
    item = result["brief"]["question_answers"][0]
    assert item["n"] == 44 and sum(g["n"] for g in item["groups"]) == 44
    assert "6条记录" in item["evidence"] and "1组共4条" in item["evidence"]
    assert item["difference_pp"] == pytest.approx(100)
    assert next(g for g in item["groups"] if g["label"] == "small")["supported"] is False


def test_numeric_event_groups_explain_actual_quartile_boundaries_and_small_support():
    df = pd.DataFrame({"outcome": [0,1]*40, "age": np.tile(np.arange(20,60),2)})
    context = {"domain": "health", "event": {"column": "outcome", "value": 1, "label": "随访期记录事件"}}
    result, _ = run(df, "age 与 outcome", "outcome", context)
    item = result["brief"]["question_answers"][0]
    assert len(item["groups"]) == 4 and all(g["n"] == 20 for g in item["groups"])
    assert item["groups"][0]["label"] == "20 至29.75（含两端）"
    assert item["groups"][1]["label"] == "大于29.75 至39.5（含上界）"
    assert "实际分界=" in item["evidence"] and "左开右闭" in item["evidence"]
    assert "不是个体诊断" in item["caveat"]
    tiny = df.iloc[:12]
    result, _ = run(tiny, "age 与 outcome", "outcome", context)
    assert result["brief"]["question_answers"][0]["status"] == "insufficient"


def test_quartile_groups_are_displayed_in_numeric_order_despite_original_row_order():
    df = pd.DataFrame({"outcome": [0,1]*40, "age": np.tile(np.arange(20,60),2)})
    df = df.sample(frac=1, random_state=21)
    context = {"event": {"column": "outcome", "value": 1, "label": "事件"}}
    result, _ = run(df, "age 与 outcome", "outcome", context)
    groups = result["brief"]["question_answers"][0]["groups"]
    assert [g["label"] for g in groups] == ["20 至29.75（含两端）", "大于29.75 至39.5（含上界）",
                                            "大于39.5 至49.25（含上界）", "大于49.25 至59（含上界）"]


def test_post_outcome_fields_are_excluded_and_named_question_explains_why():
    df = pd.DataFrame({"outcome": [0,1]*40, "time": np.tile(np.arange(20,60),2),
                       "group": ["a"]*40+["b"]*40})
    context = {"domain": "health", "event": {"column": "outcome", "value": 1, "label": "随访期记录事件"},
               "exclude_fields": {"time": "随访时长是在结果观察过程中形成，不能作为入组时的预测依据。"}}
    result, aggregate = run(df, "time 和 group 与 outcome", "outcome", context)
    item = result["brief"]["question_answers"][0]
    assert item["method"] == "excluded" and item["status"] == "insufficient"
    assert "随访时长是在结果观察过程中形成" in item["explanation"]
    assert not item["groups"] and item["rho"] is None
    assert all("time" not in f["fields"] for f in result["brief"]["findings"])
    assert result["brief"]["coverage"]["group_comparisons_evaluated"] == 1
    assert aggregate["explanation_evidence"]["question_answers"][0]["method"] == "excluded"
    assert all(c["name"] != "time" for c in aggregate["columns"])
    assert all("time" not in (p["a"],p["b"]) for p in aggregate["correlations"])
    assert all(d["column"] != "time" for d in aggregate["eda_evidence"]["distributions"])
    assert "time" not in aggregate["outliers"]
    assert all(s["metric"] != "time" and s["category"] != "time" for s in aggregate["eda_evidence"]["groups"])
    assert all("time" not in (p["a"],p["b"]) for p in aggregate["eda_evidence"]["correlations"]["spearman"])
    assert any("time" in chart["fields"] for chart in result["charts"])  # Local basic EDA is retained.
    assert aggregate["excluded_explanatory_fields"][0]["field"] == "time"


def test_context_labels_do_not_leak_to_other_requests_and_categories_are_selectable():
    df = pd.DataFrame({"duration": np.tile([80.,90.,110.,120.],20), "type": ["Movie"]*40+["TV Show"]*40})
    context = {"domain": "entertainment", "field_definitions": {"duration": {"label": "电影片长", "meaning": "仅电影，单位分钟"}}}
    result, _ = run(df, "type 与 duration", "duration", context)
    assert result["brief"]["focus"]["label"] == "电影片长"
    assert "仅电影" in result["brief"]["focus"]["meaning"]
    other, _ = run(df, "type 与 duration", "duration")
    assert other["brief"]["focus"]["label"] == "duration"
    schema = schema_description(df, {"notes": [], "analysis_context": context})
    assert next(c for c in schema["columns"] if c["name"] == "type")["selectable"]
    assert choose_focus(df, "explain type")[0] == "type"


def test_two_named_numeric_target_categories_do_not_invoke_rho_strength_comparison():
    df = pd.DataFrame({"score": np.sin(np.arange(80)), "first": ["a"]*40+["b"]*40,
                       "second": ["c","d"]*40})
    result, _ = run(df, "first 和 second", "score")
    assert len(result["brief"]["question_answers"]) == 2
    assert all(item["rho"] is None for item in result["brief"]["question_answers"])


def test_context_focus_labels_and_explicit_group_value_labels_are_respected():
    df = pd.DataFrame({"result": [0,1]*40, "contract": [0]*40+[1]*40})
    context = {"field_definitions": {"result": {"label": "实际取消记录"},
                                      "contract": {"label": "合约方式", "value_labels": {"0": "标准合约", "1": "特殊合约"}}},
               "categorical_fields": ["contract"],
               "event": {"column": "result", "value": 1, "label": "取消"}}
    result, _ = run(df, "实际取消记录与合约方式", context=context)
    assert result["brief"]["focus"]["column"] == "result"
    assert result["brief"]["question_answers"][0]["groups"][0]["label"] == "标准合约"


def test_group_exports_include_all_counts_status_and_escape_labels():
    df = pd.DataFrame({"result": [1]*20+[0]*20+[1]*3,
                       "group": ["<script>alert(1)</script>"]*20+["b"]*20+["small"]*3})
    context = {"event": {"column": "result", "value": 1, "label": "目标事件"}}
    result, _ = run(df, "group 与 result", "result", context)
    markdown = render_markdown(result, "")
    html = render_html(result, markdown, "")
    assert "分组依据" in markdown and "事件数" in markdown and "不足20条" in markdown
    assert "样本分组比较" in html and "B03" in html
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_unknown_string_event_value_never_enters_model_payload():
    df = pd.DataFrame({"result": ["private-event-value", "other"]*40, "group": ["a"]*40+["b"]*40})
    context = {"event": {"column": "result", "value": "private-event-value", "label": "来源明确事件"}}
    _, aggregate = run(df, "group 与 result", "result", context)
    assert "private-event-value" not in json.dumps(aggregate, ensure_ascii=False)


def test_explicit_numeric_category_codes_use_groups_not_continuous_correlations():
    df = pd.DataFrame({"score": np.tile([60.,70.,80.],30), "education": np.tile([1,2,3],30),
                       "other": np.tile([3.,1.,2.],30)})
    context = {"categorical_fields": ["education"]}
    result, aggregate = run(df, "education 和 score", "score", context)
    item = result["brief"]["question_answers"][0]
    assert item["method"] == "group_summary" and item["rho"] is None
    assert len(item["groups"]) == 3 and all(g["n"] == 30 for g in item["groups"])
    assert all(p["field"] != "education" for p in aggregate["explanation_evidence"]["target_relationships"])
    assert all("education" not in (p["a"],p["b"]) for p in aggregate["correlations"])
    assert all("education" not in (p["a"],p["b"]) for p in aggregate["eda_evidence"]["correlations"]["spearman"])
    assert "education" not in result["eda"]["coverage"]["selected_numeric_fields"]
    assert "education" in result["eda"]["coverage"]["selected_categorical_fields"]
    assert result["brief"]["headline"] == "按education分组，score均值有所不同"
