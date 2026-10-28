"""Build licensed public snapshots from the prepared CSV; publish aggregates only."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np

from app.analysis import analyze
from app.explanations import label, numeric_fields, target_pairs
from app.ingest import read_dataset

PROVENANCE = {
    "citation": "Wang, Dongxuan (2025), Graduation, Mendeley Data, V1",
    "url": "https://data.mendeley.com/datasets/c8ypkyswv3/1",
    "doi": "10.17632/c8ypkyswv3.1",
    "license": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/",
    "population": "来源描述为河北农业大学2020届计算机专业253名毕业生；本例不代表全国高校。",
    "preprocessing": "保留253行；原86列中的五期就业指导、七期形势与政策分别取等权均值，得到76列；统一表头，未填补、删行或标准化。",
    "publication": "公开页和下载报告仅包含聚合统计与解释，未附学生编号、逐行预览或个人散点。代码许可AGPL-3.0与数据许可分别适用。",
}
CASES = [
    ("employability", "就业能力：实习成绩能说明什么？", "就业能力自评", "employment_ability_scale",
     "就业能力自评与实习成绩、主动学习及课程成绩有什么关系？请解释实际含义。"),
    ("academic", "学业表现：哪些课程与排名更同步？", "学业排名", "gpa_rank",
     "哪些课程成绩与GPA排名更相关？这些关系能说明什么，不能说明什么？"),
]


def chart(cid, title, description, x, y, *, horizontal=False, fields=()):
    kind = "spearman" if horizontal else "group_comparison" if cid == "public-contrast" else "histogram"
    return {"id": cid, "title": title, "description": description, "type": kind, "fields": [label(f) for f in fields],
            "figure": {"data": [{"type": "bar", "x": x, "y": y,
                                  "orientation": "h" if horizontal else "v"}],
                       "layout": {"xaxis": {"title": {"text": "Spearman 排序相关" if horizontal else "区间 / 分组"}},
                                  "yaxis": {"title": {"text": "" if horizontal else "记录数"}}}},
            "sample_notes": ["仅展示聚合统计。关联不表示因果；分位划分不表示合格标准。"]}


def public_snapshot(df, result, key, title, topic):
    brief = deepcopy(result["brief"])
    target = brief["focus"]["column"]
    counts, edges = np.histogram(df[target].dropna(), bins=8)
    bins = [f"{a:g}–{b:g}{'（含右端）' if i == 7 else '（不含右端）'}"
            for i, (a, b) in enumerate(zip(edges[:-1], edges[1:]))]
    charts = [chart("public-distribution", f"{label(target)}的分布", "253条有效记录的分箱计数。",
                    bins, counts.tolist(), fields=[target])]
    pairs = {p["field"]: p for p in target_pairs(df, target, numeric_fields(df, target))}
    related = list(dict.fromkeys(f["fields"][0] for f in brief["findings"]
                                if f["kind"] in {"relationship", "measurement"}))
    if related:
        charts.append(chart("public-relationships", "主要发现对应的排序关联", "每组均使用253条成对有效记录；数值保留四位小数。GPA名次越小越靠前。" if key == "academic" else "每组均使用253条成对有效记录；数值保留四位小数。自评量表的同步变化不等于实际就业结果。",
                            [round(pairs[f]["rho"], 4) for f in related], [label(f) for f in related],
                            horizontal=True, fields=related + [target]))
    if any(f["kind"] == "contrast" for f in brief["findings"]):
        high = df["internship"] >= df["internship"].quantile(.75)
        low = df[target] <= df[target].quantile(.25)
        joint, total = int((high & low).sum()), int(high.sum())
        charts.append(chart("public-contrast", "实习成绩较高组中的就业能力自评分布",
                            f"分母是实习成绩≥92的{total}条记录；就业能力自评≤78的有{joint}条。包含分位边界值。",
                            ["就业能力自评≤78", "就业能力自评>78"], [joint, total-joint],
                            fields=["internship", target]))
    for finding in brief["findings"]:
        finding["chart_ids"] = [{"overview": "public-distribution", "contrast": "public-contrast"}.get(finding["kind"], "public-relationships")]
    source = deepcopy(result["source"])
    source["public_example"] = True
    source["notes"] += [PROVENANCE[k] for k in ("population", "preprocessing", "publication")]
    source["notes"] += ["原始来源：" + PROVENANCE["url"], "数据许可：CC BY 4.0；" + PROVENANCE["license_url"]]
    # Explicit allowlist: no rows, original chart traces, profiles, categories or jobs.
    public_result = {"title": title, "summary": brief["answer"], "source": source,
                     "overview": deepcopy(result["overview"]), "brief": brief, "charts": charts,
                     "columns": [], "insights": [], "recommendations": brief["next_questions"],
                     "preview": {"columns": [], "rows": []},
                     "agent": {"mode": "statistical", "model": None, "notes": ["预先计算的公开聚合示例，浏览与下载不创建任务、不调用模型。"]},
                     "duration_seconds": 0}
    return {"slug": "graduation-" + key, "title": title, "topic": topic,
            "description": brief["headline"], "provenance": PROVENANCE, "result": public_result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[1] / "backend/app/example_data")
    args = parser.parse_args()
    df, source = read_dataset(args.input, args.input.name, args.input.name)
    source["notes"].append(f"数据来源：{PROVENANCE['citation']}，DOI {PROVENANCE['doi']}，CC BY 4.0。")
    if df.shape != (253, 76):
        parser.error("公开Graduation案例应使用253行、76列的预处理数据。")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for key, title, topic, target, goal in CASES:
        result, _ = analyze(df, source, goal, target, lambda *args: None)
        snapshot = public_snapshot(df, result, key, title, topic)
        (args.output_dir / f"{snapshot['slug']}.json").write_text(json.dumps(snapshot, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
