"""Reproduce six aggregate-only examples using four pinned, real Kaggle sources.

Run with PYTHONPATH=backend. Raw data and full analysis reports stay under the
ignored --data-dir. Only an explicit aggregate allowlist enters example_data.
"""
import argparse
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from app.analysis import analyze
from app.ingest import read_dataset
from app.report import render_html, render_markdown


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "hotel": ("jessemostipak/hotel-booking-demand", 1, "hotel_bookings.csv",
              "7c2ae42a7353905ea136e5c2287f17c92c5435826598bfbb8491c6f0c7b1fc06", (119390, 32)),
    "credit": ("uciml/default-of-credit-card-clients-dataset", 1, "UCI_Credit_Card.csv",
               "a0f0ab49d6326671d6cd83be5c88dcf18007025fe9a53ecd699119c871176ca1", (30000, 25)),
    "heart": ("andrewmvd/heart-failure-clinical-data", 1, "heart_failure_clinical_records_dataset.csv",
              "9c73cea7468ff5d517801ec050fe9993da5912fce4b56f296f8df3b38dd75912", (299, 13)),
    "netflix": ("shivamb/netflix-shows", 5, "netflix_titles.csv",
                "df1f4ad2027a5a14c3a33932ef0d4054565ff88adf92b7f263601b70fdc6f3f3", (8807, 12)),
}


def source_frame(data_dir, key, download=False):
    slug, version, filename, digest, shape = SOURCES[key]
    folder = data_dir / slug.split("/")[1]
    path = folder / filename
    if not path.exists():
        if not download:
            raise ValueError(f"Missing {filename}; use --download to fetch its pinned Kaggle version.")
        folder.mkdir(parents=True, exist_ok=True)
        url = f"https://www.kaggle.com/api/v1/datasets/download/{slug}?datasetVersionNumber={version}"
        request = urllib.request.Request(url, headers={"User-Agent": "InsightStudio-example-reproduction/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            archive = response.read(100 * 1024 * 1024 + 1)
        if len(archive) > 100 * 1024 * 1024:
            raise ValueError("Archive exceeds reproduction download limit")
        with zipfile.ZipFile(BytesIO(archive)) as zipped:
            matches = [info for info in zipped.infolist() if Path(info.filename).name == filename]
            if len(matches) != 1 or matches[0].file_size > 50 * 1024 * 1024:
                raise ValueError("Unexpected Kaggle archive contents")
            payload = zipped.read(matches[0])
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("Source checksum differs from the reviewed version")
        path.write_bytes(payload)
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f"Unreviewed source contents: {filename}")
    df = pd.read_csv(path, low_memory=False)
    if df.shape != shape:
        raise ValueError(f"Unexpected shape for {filename}: {df.shape}")
    return df


def definition(label, meaning):
    return {"label": label, "meaning": meaning}


def cases(frames):
    hotel_fields = ["is_canceled", "lead_time", "market_segment", "distribution_channel", "customer_type",
                    "adults", "children", "babies", "meal", "is_repeated_guest", "previous_cancellations",
                    "previous_bookings_not_canceled", "reserved_room_type", "arrival_date_year",
                    "arrival_date_month", "stays_in_weekend_nights", "stays_in_week_nights"]
    hotel_context = {"domain": "business", "event": {"column": "is_canceled", "value": 1, "label": "取消预订",
        "meaning": "is_canceled=1表示该历史预订最终取消，0表示未取消；比例以本例酒店的预订记录为分母，不是营收损失率。"},
        "categorical_fields": ["is_canceled", "is_repeated_guest", "arrival_date_year"],
        "field_definitions": {
            "is_canceled": definition("预订取消记录", "1=最终取消，0=未取消；每行一笔预订，不是一个独立旅客。"),
            "lead_time": definition("提前预订天数", "录入预订至计划到店相隔的天数；分位分组不是业务风险等级。"),
            "market_segment": definition("客源渠道", "来源原有客源类别；Groups为团队、Direct为直订、Online TA为在线旅行代理。并非随机分配的渠道试验。"),
            "distribution_channel": definition("分销渠道", "酒店记录的分销渠道类别，不能据此归因于渠道政策。"),
            "customer_type": definition("预订客户类型", "原有Group/Transient/Transient-Party/Contract分类；与客源渠道中的Groups不是同一字段。"),
        }}
    hotel_context["field_definitions"]["market_segment"]["value_labels"] = {
        "Groups": "团队（Groups）", "Direct": "直订（Direct）", "Online TA": "在线旅行代理（Online TA）",
        "Offline TA/TO": "线下旅行代理／运营商（Offline TA/TO）", "Corporate": "企业（Corporate）",
        "Complementary": "免费招待（Complementary）", "Aviation": "航空（Aviation）", "Undefined": "未定义（Undefined）"}
    hotel_limits = ("两家葡萄牙酒店、计划到店日期2015年7月至2017年8月的历史记录；取到店前快照，不是纯粹预订创建时点。"
                    "未控制价格、渠道或客户构成，不能把组间差异当作改政策的效果。agent/company空值表示不适用；本例不纳入它们。"
                    "剔除订金、实际分房、预订变更、特别要求和最终预订状态等时点可能靠后的字段；不计算取消造成的营收损失。")
    for slug, hotel_type, title in [
        ("hotel-city-cancellations", "City Hotel", "城市酒店：哪些预订更常被取消？"),
        ("hotel-resort-cancellations", "Resort Hotel", "度假酒店：提前很久订房，取消更多吗？"),
    ]:
        frame = frames["hotel"].loc[frames["hotel"]["hotel"].eq(hotel_type), hotel_fields].copy()
        yield {"slug": slug, "title": title, "domain": "商业", "topic": "酒店预订", "source_key": "hotel",
               "target": "is_canceled", "goal": "提前预订天数、客源渠道与预订取消记录有什么关系？请给出各组取消数量、分母和相差的百分点。",
               "frame": frame, "context": deepcopy(hotel_context), "limits": hotel_limits,
               "population": f"{hotel_type}完整子群{len(frame):,}笔；两例合起来覆盖原始119,390笔，来自同一数据源。",
               "preprocessing": f"先按hotel={hotel_type}选取完整子群，未按文件前缀截断；保留17个选定字段，未删行、去重、填补或缩放。"}
    credit = frames["credit"].drop(columns=["ID"]).copy()
    credit_context = {"domain": "finance", "event": {"column": "default.payment.next.month", "value": 1,
        "label": "下月违约记录", "meaning": "原资料明确1=下月违约、0=未违约；这里是历史已观察比例，不是未来个人违约概率。"},
        "categorical_fields": ["SEX", "EDUCATION", "MARRIAGE", "PAY_0", "PAY_2", "PAY_3", "PAY_4", "PAY_5", "PAY_6"],
        "field_definitions": {
            "default.payment.next.month": definition("下月违约记录", "1=违约，0=未违约；2005年台湾历史客户样本。"),
            "PAY_0": definition("9月还款状态编码", "-1=按时还款，正值1至8=延迟相应月数，9=九个月及以上；原字典未完整解释-2和0，保持原码，不能把所有非正值统称正常。"),
            "LIMIT_BAL": definition("信用额度（新台币）", "原给定信用额度，单位NTD，包含个人及附属家庭信用；不是美元，也不能据此证明提高额度能减少违约。"),
            "SEX": definition("性别编码", "原有类别编码，不是连续数值，不作为个体信贷分配建议。"),
            "EDUCATION": definition("教育程度编码", "原字典1研究生、2大学、3高中、4其他；0/5/6未完整定义，保留原码。"),
            "MARRIAGE": definition("婚姻状态编码", "原字典1已婚、2单身、3其他；0未定义，保留原码。"),
        }}
    credit_context["field_definitions"]["PAY_0"]["value_labels"] = {
        "-2": "-2（原字典未说明）", "-1": "-1（按时还款）", "0": "0（原字典未说明）",
        **{str(n): f"{n}（延迟{n}个月）" for n in range(1, 9)}, "9": "9（延迟9个月及以上）"}
    yield {"slug": "credit-card-default", "title": "信用卡：近期还款记录能告诉我们什么？", "domain": "金融", "topic": "历史还款",
           "source_key": "credit", "target": "default.payment.next.month",
           "goal": "9月还款状态编码、信用额度（新台币）与下月违约记录有什么关系？请保留编码含义和各组分母。",
           "frame": credit, "context": credit_context,
           "population": "30,000名台湾信用卡客户，解释变量主要覆盖2005年4月至9月；不是当下金融风险调查。",
           "preprocessing": "剔除客户ID，保留全部30,000行和24列；不同ID即使其他值相同也不去重。类别编码不当作连续数量。",
           "limits": "未控制混杂或独立验证，历史组内比例不等于未来违约概率；不用于投资、审批或拒绝个人信贷。未知编码保持原样，不把所有非正还款编码解释为正常。"}
    heart = frames["heart"].copy()
    heart_context = {"domain": "health", "event": {"column": "DEATH_EVENT", "value": 1, "label": "随访期死亡记录",
        "meaning": "DEATH_EVENT=1表示随访期间记录死亡，0表示没有记录死亡。每人的随访时长不同，不是统一30天或一年死亡风险。"},
        "categorical_fields": ["anaemia", "diabetes", "high_blood_pressure", "sex", "smoking", "DEATH_EVENT"],
        "exclude_fields": {"time": "随访时长在随访中形成，死亡可能终止随访；不能当作入组时已知的预测因素或保护因素。"},
        "field_definitions": {
            "DEATH_EVENT": definition("随访期死亡记录", "1=随访期记录死亡，0=未记录死亡；没有做删失分析或生存模型。"),
            "ejection_fraction": definition("射血分数（%）", "每次心脏收缩时射出的血液占比，百分比单位；仅比较本队列记录。"),
            "serum_creatinine": definition("血清肌酐（mg/dL）", "血清肌酐实验室记录，单位mg/dL；不能由单一指标进行个体诊断。"),
            "time": definition("随访时长（天）", "4至285天不等，属于随访过程信息，已经排除初始风险解释候选。"),
        }}
    yield {"slug": "heart-failure-followup", "title": "心衰随访：看懂观察差异，也看懂局限", "domain": "医疗", "topic": "临床观察",
           "source_key": "heart", "target": "DEATH_EVENT", "goal": "射血分数（%）、血清肌酐（mg/dL）与随访期死亡记录有什么关系？为什么不能把随访时长（天）视为保护因素？",
           "frame": heart, "context": heart_context,
           "population": "巴基斯坦Faisalabad两家医疗机构2015年的299名心衰患者，选择性小队列，不代表一般人群。",
           "preprocessing": "保留299行13列，未填补或删行；time保留为随访背景，但从解释和模型证据候选排除。",
           "limits": "随访4至285天不等，记录死亡96例；二值分组不是生存分析。没有个体诊断、治疗建议或一般人群死亡风险估计。观察到的差异不能解释为治疗或保护效果。"}
    netflix = frames["netflix"]
    frame = netflix[["type", "release_year", "rating"]].copy()
    frame["release_decade"] = (frame["release_year"] // 10 * 10).astype(str) + "年代"
    # Three duration strings were placed in rating in the source; never call
    # those an age classification or silently move them to the duration field.
    frame.loc[frame["rating"].str.fullmatch(r"\d+ min", na=False), "rating"] = pd.NA
    netflix_context = {"domain": "entertainment", "event": {"column": "type", "value": "Movie", "label": "电影条目",
        "meaning": "type=Movie为电影、TV Show为剧集；这里只是历史片库条目构成，不代表播放量、偏好、评分或当前可观看性。"},
        "field_definitions": {
            "type": definition("作品类型", "Movie=电影、TV Show=剧集；作品目录条目不等于观众观看记录。"),
            "release_decade": definition("作品发行年代", "由作品发行年按十年分组；不是Netflix上架年代，也不说明平台采购趋势。"),
            "release_year": definition("原始发行年份", "作品自身发行年，不是平台上架年；年代组来源于该字段。"),
            "rating": definition("内容分级标签", "TV-MA/PG等内容分级，不是观众打分；3条误放片长和原有空值保留为缺失。"),
        }}
    limits = ("2021年历史片库快照，目录不含播放量、评分、营收或完整下架历史。作品发行年不是平台上架年；"
              "2021上架时间不完整，不能与完整年度总量比较。country是制作地不是观众地域，题材和制作地可多标签；本例未展开它们。")
    yield {"slug": "netflix-catalog", "title": "Netflix片库：电影和剧集怎么分？", "domain": "娱乐", "topic": "历史片库",
           "source_key": "netflix", "target": "type", "goal": "作品发行年代与作品类型的构成有什么关系？这里能否看出观众更喜欢什么？",
           "frame": frame, "context": netflix_context, "population": "8,807条历史Netflix作品目录，6,131部电影和2,676部剧集；不是观看行为调查。",
           "preprocessing": "保留全部8,807条；提取type/release_year/rating并派生发行年代，共4列；3条rating误放片长改为缺失，不补值；不发布作品名、演员或描述。",
           "limits": limits}
    movie = frame.loc[netflix["type"].eq("Movie")].drop(columns="type").copy()
    movie["movie_minutes"] = pd.to_numeric(netflix.loc[movie.index, "duration"].str.extract(r"^(\d+) min$", expand=False), errors="coerce")
    movie_context = deepcopy(netflix_context)
    movie_context.pop("event")
    movie_context["field_definitions"]["movie_minutes"] = definition("电影时长（分钟）", "仅解析Movie且duration严格形如‘数字 min’；TV Show的季数不能混入分钟。电影6131条，6128条片长有效，3条保留缺失。")
    yield {"slug": "netflix-movie-length", "title": "挑部电影：通常需要留出多久？", "domain": "娱乐", "topic": "电影时长",
           "source_key": "netflix", "target": "movie_minutes", "goal": "电影时长（分钟）的典型范围是多少？作品发行年代与电影时长（分钟）有什么关系？",
           "frame": movie, "context": movie_context, "population": "同一Netflix快照的完整6,131部电影子群，6,128条可解析片长；与片库案例共用数据源。",
           "preprocessing": "完整Movie子群，保留发行年/内容分级/发行年代，增加按‘数字 min’解析的分钟数，共4列；3条原始缺失片长不修复、不填补。",
           "limits": limits + "时长不是作品质量；年代比较可能混合题材和地区构成。"}


def bar(cid, title, description, x, y, fields, y_label="记录数"):
    return {"id": cid, "title": title, "description": description, "type": "group_comparison",
            "fields": fields, "sample_notes": ["聚合统计；组间差异不表示因果，分组界限不是诊断或业务阈值。"],
            "figure": {"data": [{"type": "bar", "x": x, "y": y}],
                       "layout": {"xaxis": {"title": {"text": "区间 / 原始类别"}},
                                  "yaxis": {"title": {"text": y_label}, "rangemode": "tozero"}}}}


def snapshot(case, df, result):
    """Publish only bounded groups, statistical bins, and local explanations."""
    brief = deepcopy(result["brief"])
    target = case["target"]
    clean = df[target].dropna()
    event = case["context"].get("event")
    if event:
        names = [f"{event['label']}（{event['value']}）", "其他记录"]
        values = [int(clean.eq(event["value"]).sum()), int(clean.ne(event["value"]).sum())]
        charts = [bar("public-distribution", "先看总体构成", f"{len(clean):,}条目标有效记录；缺失{len(df)-len(clean)}条。", names, values, [target])]
    else:
        values, edges = np.histogram(clean, bins=10)
        names = [f"[{a:g}, {b:g}{']' if i == 9 else ')'}" for i,(a,b) in enumerate(zip(edges[:-1],edges[1:]))]
        charts = [bar("public-distribution", "关注指标的分布", f"{len(clean):,}条有效记录，等宽分箱；缺失{len(df)-len(clean)}条。", names, values.tolist(), [target])]
    for index, answer in enumerate(brief.get("question_answers", []), 1):
        groups = answer.get("groups", [])
        supported = [g for g in groups if g.get("supported")]
        if not supported:
            continue
        rate = answer.get("method") in {"event_rate", "category_share"}
        notes = "; ".join(f"{g['label']}: " + (f"{g['events']}/{g['n']}" if rate else f"n={g['n']}, median={g['median']:.6g}") for g in supported)
        charts.append(bar(f"public-question-{index}", answer["question"], notes + "。仅展示每组至少20条的组；其他组计数见问题依据。",
                          [g["label"] for g in supported], [g["rate_pct"] if rate else g["mean"] for g in supported], answer["fields"],
                          "组内比例（%）" if rate else "均值（目标原单位）"))
    for finding in brief["findings"]:
        finding["chart_ids"] = [c["id"] for c in charts if set(finding["fields"]).issubset(c["fields"])][:2]
    # Domain scope comes from verified source documentation, not model output.
    brief["caveats"].insert(0, case["limits"])
    provenance = provenance_for(case)
    public_source = {key: deepcopy(result["source"][key]) for key in
                     ("filename", "is_demo", "analyzed_rows", "total_rows", "sampled", "sheet", "notes")}
    public_source["public_example"] = True
    public_source["quality_scope"] = "selected_fields"
    public_source["notes"] += [provenance[k] for k in ("population", "preprocessing", "publication")]
    public_source["notes"] += [case["limits"], "原始来源：" + provenance["url"], "Kaggle来源：" + provenance["kaggle_url"],
                               "数据许可：" + provenance["license"], "来源署名：" + provenance["citation"]]
    overview = next(f for f in brief["findings"] if f["kind"] == "overview")
    report = {"title": case["title"], "summary": brief["answer"], "source": public_source,
              "overview": {k: deepcopy(v) for k,v in result["overview"].items() if k not in {"duplicate_rows", "quality_score"}},
              "brief": brief, "charts": charts,
              "columns": [], "insights": [], "recommendations": brief["next_questions"], "preview": {"columns": [], "rows": []},
              "agent": {"mode": "statistical", "model": None, "notes": ["真实Kaggle固定版本经本项目完整统计流程生成；未调用付费模型。公开报告只含聚合证据，浏览与下载不创建任务。"]},
              "duration_seconds": 0}
    return {"slug": case["slug"], "title": case["title"], "description": case["population"], "finding": overview["takeaway"],
            "domain": case["domain"], "topic": case["topic"], "provenance": provenance, "result": report}


def provenance_for(case):
    key = case["source_key"]
    slug, version, filename, digest, shape = SOURCES[key]
    attribution = {
        "hotel": ("Antonio, de Almeida & Nunes (2019), Hotel booking demand datasets; Kaggle curator Jesse Mostipak; CSV compilation Thomas Mock & Antoine Bichat", "https://doi.org/10.1016/j.dib.2018.11.126", "CC BY 4.0"),
        "credit": ("I-Cheng Yeh; Yeh & Che-hui Lien (2009), Default of Credit Card Clients, UCI; Kaggle mirror UCI ML", "https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients", "Kaggle标记CC0；原始UCI现标记CC BY 4.0，保留原作者署名并遵循CC BY 4.0要求"),
        "heart": ("Ahmad et al. (2017); Chicco & Jurman (2020), Heart Failure Clinical Records, UCI; Kaggle curator Andrew MVD", "https://archive.ics.uci.edu/dataset/519/heart+failure+clinical+records", "CC BY 4.0"),
        "netflix": ("Shivam Bansal, Netflix Movies and TV Shows, Kaggle, V5", "https://www.kaggle.com/datasets/shivamb/netflix-shows", "CC0: Public Domain"),
    }
    citation, url, license_name = attribution[key]
    return {"citation": citation, "url": url, "license": license_name,
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/" if key == "netflix" else "https://creativecommons.org/licenses/by/4.0/",
            "kaggle_url": "https://www.kaggle.com/datasets/" + slug, "dataset_version": version, "accessed_at": "2026-10-28",
            "source_sha256": digest, "population": case["population"], "preprocessing": case["preprocessing"],
            "publication": "公开页与下载仅含聚合统计、分箱计数和解释，未捆绑原始行、个人标识或散点。代码AGPL-3.0与各来源数据许可分别适用。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local/cross-domain")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "backend/app/example_data")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frames = {key: source_frame(args.data_dir, key, args.download) for key in SOURCES}
    report_dir = args.data_dir / "reports"
    report_dir.mkdir(exist_ok=True)
    manifest = []
    for case in cases(frames):
        input_path = args.data_dir / (case["slug"] + ".csv")
        case["frame"].to_csv(input_path, index=False)
        df, source = read_dataset(input_path, input_path.name, input_path.name)
        assert len(df) == len(case["frame"]) and not source["sampled"]
        source["analysis_context"] = case["context"]
        source["quality_scope"] = "selected_fields"
        source["notes"] += [case["limits"], case["preprocessing"]]
        result, _ = analyze(df, source, case["goal"], case["target"], lambda *args: None)
        # Full intermediate EDA is local and deliberately not redistributed.
        md = render_markdown(result, case["goal"])
        (report_dir / (case["slug"] + ".md")).write_text(md, encoding="utf-8")
        (report_dir / (case["slug"] + ".html")).write_text(render_html(result, md, case["goal"]), encoding="utf-8")
        public = snapshot(case, df, result)
        output = args.output_dir / (case["slug"] + ".json")
        output.write_text(json.dumps(public, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
        manifest.append({"slug": case["slug"], "input_sha256": hashlib.sha256(input_path.read_bytes()).hexdigest(),
                         "rows": len(df), "columns": len(df.columns), "full_chart_count": len(result["charts"]),
                         "public_chart_count": len(public["result"]["charts"]), "model_requests": 0})
        print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)
    (args.data_dir / "generation-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
