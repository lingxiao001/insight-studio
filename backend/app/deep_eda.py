"""Bounded, reproducible EDA v2. All summaries use analyzed rows, never chart samples."""
import json
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from .analysis import COLORS, finite, short

TOPICS = [
    ("quality", "数据质量", "缺失分布、缺失共现与潜在极端值；不推断缺失机制。"),
    ("distributions", "数值分布", "各选中度量的完整分布、分位数、尾部与 IQR。"),
    ("categories", "类别结构", "类别支持数与集中度；类别原值仅留在本地报告。"),
    ("relationships", "变量关系", "Pearson 与 Spearman 成对完整样本相关，不代表因果。"),
    ("groups", "分组比较", "有效样本量、均值、中位数与四分位范围；不声称显著差异。"),
    ("time", "日期分桶比较", "按记录日期分桶比较指标与支持数；是否代表事件时间取决于字段业务定义。"),
    ("target", "关注字段专项", "优先围绕显式关注字段组织可验证的描述性证据。"),
]
MAX_CHARTS = 60


def number(value):
    return finite(value)


def display(value):
    return "—" if value is None else f"{value:.6g}"


def distribution(series, name):
    values = series.dropna()
    n = len(values)
    quantiles = values.quantile([.05, .25, .5, .75, .95]) if n else pd.Series([np.nan] * 5)
    q05, q1, median, q3, q95 = [number(x) for x in quantiles]
    iqr = q3 - q1 if q1 is not None and q3 is not None else None
    scale = float(values.abs().max()) if n else 0
    scaled = values / scale if scale > 0 else values
    skew = number(scaled.skew()) if n >= 3 and values.nunique() > 1 else None
    kurtosis = number(scaled.kurt()) if n >= 4 and values.nunique() > 1 else None
    outlier_count = int(((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).sum()) if n >= 4 and iqr and iqr > 0 else None
    return {"column": name, "n": n, "mean": number(values.mean()), "median": median,
            "std": number(values.std()), "min": number(values.min()), "max": number(values.max()),
            "p05": q05, "p25": q1, "p50": median, "p75": q3, "p95": q95,
            "skew": skew, "kurtosis": kurtosis, "iqr": number(iqr), "outlier_count": outlier_count,
            "outlier_pct": round(outlier_count / n * 100, 3) if outlier_count is not None and n else None,
            "zero_count": int(values.eq(0).sum()), "negative_count": int(values.lt(0).sum())}


def pair_statistics(df, fields, method):
    eligible = [name for name in fields if df[name].notna().sum() >= 5 and df[name].nunique() > 1]
    corr = df[eligible].corr(method=method, min_periods=5) if eligible else pd.DataFrame()
    pairs = []
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            value = number(corr.loc[a, b])
            if value is not None:
                value = 0.0 if abs(value) < 1e-12 else value
                pairs.append({"a": a, "b": b, "r": value, "n": int(df[[a, b]].notna().all(axis=1).sum())})
    return sorted(pairs, key=lambda p: abs(p["r"]), reverse=True), corr


class Charts:
    def __init__(self):
        self.candidates = []

    def add(self, section, title, description, kind, figure, fields=(), notes=(), wide=False):
        for axis in ("x", "y"):
            for trace in figure.data:
                coordinates = getattr(trace, axis, None)
                if coordinates is not None and len(coordinates) and all(isinstance(value, str) and value in fields for value in coordinates):
                    figure.update_layout(**{axis + "axis": {"tickmode":"array","tickvals":list(coordinates),"ticktext":[short(value) for value in coordinates]}})
                    break
        figure.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)", font={"family": "Arial, sans-serif", "color": "#625F59", "size": 12},
            colorway=COLORS, margin={"l": 60, "r": 25, "t": 25, "b": 65}, height=340,
            hoverlabel={"namelength": 60})
        figure.update_xaxes(gridcolor="#E4E0D8", zeroline=False, automargin=True)
        figure.update_yaxes(gridcolor="#E4E0D8", zeroline=False, automargin=True)
        self.candidates.append({"id": f"eda-{len(self.candidates) + 1}", "title": title,
            "description": description, "type": kind, "section": section, "fields": list(fields),
            "sample_notes": list(notes), "wide": wide,
            "figure": json.loads(json.dumps(figure.to_plotly_json(), cls=PlotlyJSONEncoder))})

    def selected(self):
        # Round-robin gives every applicable topic a slot before a second pass;
        # a large distribution panel can never consume the target/time budget.
        queues = {key: [c for c in self.candidates if c["section"] == key] for key, _, _ in TOPICS}
        chosen = []
        order = ["target", "quality", "distributions", "categories", "relationships", "groups", "time"]
        while len(chosen) < MAX_CHARTS:
            added = False
            for key in order:
                if queues[key] and len(chosen) < MAX_CHARTS:
                    chosen.append(queues[key].pop(0))
                    added = True
            if not added:
                break
        ids = {c["id"] for c in chosen}
        return [c for c in self.candidates if c["id"] in ids]


def build_eda(df, kinds, profiles, numeric, identifiers, target, goal):
    charts = Charts()
    excluded = []
    eligible = []
    profile_map = {p["name"]: p for p in profiles}
    all_distributions = {}
    for name in df.columns:
        profile = profile_map[name]
        profile.update(quantiles=None, skew=None, kurtosis=None, iqr=None, outlier_count=None, outlier_pct=None)
        if kinds[name] == "numeric":
            item = distribution(df[name], name)
            all_distributions[name] = item
            profile.update(**{key:item[key] for key in ("mean","median","std","min","max")})
            profile.update(quantiles={key: item[key] for key in ("p05", "p25", "p50", "p75", "p95")},
                           skew=item["skew"], kurtosis=item["kurtosis"], iqr=item["iqr"],
                           outlier_count=item["outlier_count"], outlier_pct=item["outlier_pct"])
        if name in identifiers:
            excluded.append({"field": name, "reason": "疑似标识符，不参与度量关系与分布选择。"})
        elif profile["unique"] == 0:
            excluded.append({"field": name, "reason": "全缺失，无法生成分布或变量关系。"})
        elif profile["unique"] == 1:
            excluded.append({"field": name, "reason": "常量字段，没有可比较的变异。"})
        elif kinds[name] == "numeric" and df[name].notna().sum() < 2:
            excluded.append({"field": name, "reason": "有效数值少于 2 个，仅保留字段画像。"})
        elif name in numeric:
            eligible.append(name)
    selected = ([target] if target in eligible else []) + [name for name in eligible if name != target]
    selected = selected[:10]
    distributions = [all_distributions[name] for name in selected]
    category_candidates = [name for name in df.columns if kinds[name] in {"categorical", "boolean"}
        and name not in identifiers and 1 < df[name].nunique() <= 500
        and df[name].nunique() / max(df[name].notna().sum(), 1) <= .7 and df[name].notna().sum() >= 5]
    selected_categories = ([target] if target in category_candidates else []) + [name for name in category_candidates if name != target]
    selected_categories = selected_categories[:5]
    for name in df.columns:
        if (kinds[name] in {"categorical", "boolean"} and name not in category_candidates
                and name not in {item["field"] for item in excluded}):
            excluded.append({"field":name,"reason":"类别支持数、基数或唯一比例未满足探索阈值，保留画像与预览。"})
    date_candidates = [name for name in df.columns if kinds[name] == "datetime" and name not in identifiers
             and df[name].notna().sum() >= 2 and df[name].nunique() > 1]
    dates = (([target] if target in date_candidates else []) + [name for name in date_candidates if name != target])[:1]
    selection_notes = [
        f"从 {len(eligible)} 个合理数值度量中确定性选择 {len(selected)} 个（上限 10，显式关注字段优先，其余按源列顺序）。",
        f"类别字段选择 {len(selected_categories)} / {len(category_candidates)} 个合格候选（上限 5；2–500 个类别、有效值至少 5、唯一比例不超过 70%）。",
        "图表候选仅来自已选择字段，不能理解为覆盖所有字段或全部组合；每个专题均预留图表位置，最多 60 图。",
        "缺失、常量与疑似标识符有明确排除原因；每个相关系数至少 5 对完整值只是产品防护阈值，不是可靠性或显著性保证。",
        "偏度/超额峰度在按最大绝对值缩放后计算；不会据此声称正态或对称。IQR 为 0 时不自动判极端值。",
    ]
    sampling_notes = ["画像、分位数、分组与时间聚合使用全部分析行；仅散点显示最多固定种子抽样 1,500 点。",
                      "类别图最多显示 12 组；分组比较按有效支持数选前 8 组且每组至少 5 个有效值，其余组不合并为虚构‘其他’。",
                      "分组比较最多 9 个组合，先让每个已选类别覆盖关注度量（或首个合格度量），再填充次级度量。"]
    missing = df.isna().mean().mul(100).sort_values(ascending=False).head(15)
    charts.add("quality", "各字段缺失率", "分母为全部分析行；显示缺失率最高的最多 15 个字段。", "missingness",
        go.Figure(go.Bar(x=list(missing.index), y=missing.round(3).tolist(), marker_color=COLORS[0],
            hovertemplate="%{x}<br>缺失率 %{y:.2f}%<extra></extra>")).update_layout(
                yaxis_title="缺失率（%）", yaxis_range=[0, min(100, max(1, float(missing.max()) * 1.12))], showlegend=False),
        missing.index)
    row_missing = df.isna().sum(axis=1)
    if row_missing.max() > 0:
        counts = row_missing.value_counts().sort_index()
        charts.add("quality", "每行缺失字段数", "基于全部字段和分析行；用来观察完整记录与多字段缺失的支持数。", "completeness",
            go.Figure(go.Bar(x=counts.index.tolist(), y=counts.tolist(), marker_color=COLORS[1])).update_layout(
                xaxis_title="每行缺失字段数", yaxis_title="记录数", showlegend=False), list(df.columns))
        incomplete_fields = [name for name in df.columns if df[name].isna().any()][:12]
        mask = df[incomplete_fields].isna().to_numpy(dtype=np.int32)
        codes = mask @ (1 << np.arange(len(incomplete_fields), dtype=np.int32))
        unique_codes, pattern_counts = np.unique(codes, return_counts=True)
        order = np.argsort(-pattern_counts, kind="stable")[:10]
        labels = []
        for index in order:
            fields = [name for bit, name in enumerate(incomplete_fields) if unique_codes[index] & (1 << bit)]
            labels.append(short(" + ".join(fields) if fields else "这些字段均完整", 85))
        charts.add("quality", "常见缺失组合", "展示所选缺失字段中支持数最多的 10 种缺失模式；不推断缺失机制。", "missing_pattern",
            go.Figure(go.Bar(x=labels, y=pattern_counts[order].tolist(), marker_color=COLORS[2])).update_layout(
                yaxis_title="记录数", showlegend=False), incomplete_fields,
            [f"只选择源列顺序前 {len(incomplete_fields)} 个存在缺失的字段（上限 12）；组合计数使用全部 {len(df):,} 行。"])
        if len(incomplete_fields) >= 2:
            intersection = mask.T @ mask
            sizes = mask.sum(axis=0)
            union = sizes[:, None] + sizes[None, :] - intersection
            overlap = np.divide(intersection, union, out=np.zeros_like(intersection, dtype=float), where=union > 0)
            charts.add("quality", "缺失共现 · Jaccard", "共同缺失行数 / 至少一个字段缺失的行数；仅为共现描述，不能判断缺失是否随机。", "missing_cooccurrence",
                go.Figure(go.Heatmap(x=incomplete_fields, y=incomplete_fields,
                    z=overlap.round(6).tolist(), zmin=0, zmax=1, colorscale=[[0,"#F1EEE7"],[1,COLORS[0]]],
                    hovertemplate="%{x} × %{y}<br>共同缺失比例 %{z:.3f}<extra></extra>")), incomplete_fields)
    outlier_items = [d for d in distributions if d["outlier_pct"] is not None]
    if outlier_items:
        charts.add("quality", "各度量 IQR 极端值比例", "分母为各字段非缺失记录；边界 Q1−1.5×IQR 与 Q3+1.5×IQR。潜在极端值不等于错误。", "outlier_rate",
            go.Figure(go.Bar(x=[d["column"] for d in outlier_items], y=[d["outlier_pct"] for d in outlier_items],
                customdata=[d["n"] for d in outlier_items], marker_color=COLORS[3],
                hovertemplate="%{x}<br>IQR 提示 %{y:.2f}%<br>有效记录 %{customdata}<extra></extra>")).update_layout(
                    yaxis_title="潜在极端值比例（%）", showlegend=False), [d["column"] for d in outlier_items])

    for item in distributions:
        name = item["column"]
        values = df[name].dropna()
        counts, bins = np.histogram(values, bins=min(32, max(2, int(np.sqrt(len(values))))))
        charts.add("distributions", f"{short(name)} · 数值分布", f"全部 {len(values):,} 个非缺失值的分箱计数；不根据均值/中位数关系推断分布对称或正态。", "histogram",
            go.Figure(go.Bar(x=((bins[:-1] + bins[1:]) / 2).tolist(), y=counts.tolist(), width=np.diff(bins).tolist(),
                marker_color=COLORS[0])).update_layout(xaxis_title=short(name), yaxis_title="记录数", showlegend=False), [name])
        q1, median, q3 = item["p25"], item["p50"], item["p75"]
        inside = values.between(q1 - 1.5 * item["iqr"], q3 + 1.5 * item["iqr"])
        charts.add("distributions", f"{short(name)} · 分位与尾部", f"箱体为 Q1–Q3，中线为中位数，须线为 1.5×IQR 内的实际极值；P05={display(item['p05'])}, P95={display(item['p95'])}。", "box",
            go.Figure(go.Box(x=[short(name)], q1=[q1], median=[median], q3=[q3], lowerfence=[number(values[inside].min())],
                upperfence=[number(values[inside].max())], name=short(name), marker_color=COLORS[2], boxpoints=False)).update_layout(showlegend=False), [name])

    categories, alias_maps = [], {}
    for name in selected_categories:
        counts = df[name].dropna().value_counts(sort=True)
        n = int(counts.sum())
        shares = counts / n
        aliases = {value: f"G{i + 1:02d}" for i, value in enumerate(counts.index)}
        alias_maps[name] = aliases
        top_values = [{"group_id": aliases[label], "label": str(label)[:100], "count": int(count), "pct": round(count/n*100, 3)}
                      for label, count in counts.head(12).items()]
        categories.append({"column": name, "n": n, "unique": len(counts), "top1_pct": round(float(shares.iloc[0]) * 100, 3),
            "top3_pct": round(float(shares.head(3).sum()) * 100, 3), "hhi": round(float((shares ** 2).sum()), 6),
            "entropy": round(float(-(shares * np.log2(shares)).sum()), 6), "top_values": top_values})
        charts.add("categories", f"{short(name)} · 类别支持数", "按全部非缺失值聚合后显示最多 12 个类别；分母为该字段非缺失记录，不把省略类别合成‘其他’。", "bar",
            go.Figure(go.Bar(x=[x["group_id"] + " · " + short(x["label"]) for x in top_values], y=[x["count"] for x in top_values],
                customdata=[x["pct"] for x in top_values], marker_color=COLORS[1],
                hovertemplate="%{x}<br>记录 %{y}<br>占非缺失值 %{customdata:.2f}%<extra></extra>")).update_layout(yaxis_title="记录数", showlegend=False), [name])
    if len(categories) >= 2:
        charts.add("categories", "类别集中度 · HHI", "HHI=各类别份额平方和（0–1），全类别参与；不同唯一值数量会影响该指标，不能简单评价好坏。", "concentration",
            go.Figure(go.Bar(x=[c["column"] for c in categories], y=[c["hhi"] for c in categories],
                customdata=[c["unique"] for c in categories], marker_color=COLORS[4],
                hovertemplate="%{x}<br>HHI %{y:.3f}<br>类别数 %{customdata}<extra></extra>")).update_layout(yaxis_range=[0,1], showlegend=False), [c["column"] for c in categories])

    pearson, pearson_matrix = pair_statistics(df, selected, "pearson")
    spearman, spearman_matrix = pair_statistics(df, selected, "spearman")
    for method, pairs, matrix, kind in [("Pearson", pearson, pearson_matrix, "heatmap"), ("Spearman", spearman, spearman_matrix, "spearman")]:
        if len(matrix.columns) >= 2 and pairs:
            counts = [[int(df[[a,b]].notna().all(axis=1).sum()) for b in matrix.columns] for a in matrix.columns]
            charts.add("relationships", f"{method} · 数值字段相关性", "每对变量分别使用完整样本；至少 5 对只是防护阈值。Spearman 在该对有效样本上排名；相关不代表因果或显著性。", kind,
                go.Figure(go.Heatmap(x=list(matrix.columns), y=list(matrix.columns),
                    z=matrix.where(pd.notna(matrix), None).values.tolist(), customdata=counts, zmin=-1,zmax=1,
                    colorscale=[[0,"#778D99"],[.5,"#F1EEE7"],[1,"#8B5055"]],
                    hovertemplate="%{x} × %{y}<br>r=%{z:.3f}<br>成对有效 n=%{customdata}<extra></extra>")), list(matrix.columns))
    ranked_pairs = sorted(pearson, key=lambda p: (target not in {p["a"],p["b"]}, -abs(p["r"])))
    chosen_pairs, used_fields = [], set()
    for pair in ranked_pairs:
        if not chosen_pairs or len({pair["a"], pair["b"]} - used_fields) > 0:
            chosen_pairs.append(pair)
            used_fields.update((pair["a"], pair["b"]))
        if len(chosen_pairs) >= 4:
            break
    for pair in ranked_pairs:
        if len(chosen_pairs) >= 4:
            break
        if pair not in chosen_pairs:
            chosen_pairs.append(pair)
    for pair in chosen_pairs:
        a, b = pair["a"], pair["b"]
        points = df[[a,b]].dropna()
        notes = []
        if len(points) > 1500:
            points = points.sample(1500, random_state=42)
            notes = [f"图中固定随机种子 42 抽样 1,500 点；Pearson 与有效 n 使用全部 {pair['n']:,} 对完整值。"]
        charts.add("relationships", f"{short(a)} × {short(b)}", f"Pearson r={pair['r']:.3f}，成对有效 n={pair['n']:,}；描述性关系，不作因果推断。", "scatter",
            go.Figure(go.Scattergl(x=points[a].tolist(),y=points[b].tolist(),mode="markers",marker={"color":COLORS[0],"size":5,"opacity":.45})).update_layout(
                xaxis_title=short(a),yaxis_title=short(b),showlegend=False), [a,b], notes)

    # Target and the strongest associated metrics get the first group comparisons.
    metric_order = [target] if target in selected else []
    for pair in ranked_pairs:
        if target in {pair["a"],pair["b"]}:
            other = pair["b"] if pair["a"] == target else pair["a"]
            if other not in metric_order:
                metric_order.append(other)
    metric_order += [name for name in selected if name not in metric_order]
    group_metrics = metric_order[:3]
    groups = []
    for metric in group_metrics:
        for category in selected_categories:
            if len(groups) >= 9:
                break
            grouped = df.groupby(category, observed=True, sort=False)[metric]
            summary = grouped.agg(n="count", mean="mean", median="median", sum="sum")
            summary["q25"] = grouped.quantile(.25)
            summary["q75"] = grouped.quantile(.75)
            total_groups = len(summary)
            summary = summary[summary["n"] >= 5].sort_values("n", ascending=False, kind="stable")
            if len(summary) < 2:
                continue
            omitted = total_groups - min(8,len(summary))
            summary = summary.head(8)
            values = [{"group_id": alias_maps[category][label], "label": str(label)[:100], "n":int(row["n"]),
                **{key:number(row[key]) for key in ("mean","median","q25","q75","sum")}} for label,row in summary.iterrows()]
            study = {"category":category,"metric":metric,"groups":values,"omitted_groups":omitted,
                "selection_note":"每组至少 5 个非缺失指标值，按有效支持数选前 8 组；比较只描述选中组。算术和未验证业务可加性。"}
            groups.append(study)
            labels = [v["group_id"] + " · " + short(v["label"]) for v in values]
            figure = go.Figure(go.Scatter(x=labels,y=[v["median"] for v in values],mode="markers",name="中位数与四分位范围",
                error_y={"type":"data","symmetric":False,"array":[max(0,v["q75"]-v["median"]) for v in values],
                         "arrayminus":[max(0,v["median"]-v["q25"]) for v in values]},customdata=[v["n"] for v in values],
                marker={"color":COLORS[0],"size":8},hovertemplate="%{x}<br>中位数 %{y:,.3g}<br>有效 n=%{customdata}<extra></extra>"))
            figure.add_trace(go.Scatter(x=labels,y=[v["mean"] for v in values],mode="markers",name="均值",marker={"color":COLORS[3],"symbol":"diamond","size":8}))
            charts.add("groups",f"{short(category)} × {short(metric)} · 稳健比较",study["selection_note"],"group_comparison",figure,[category,metric])

    time_studies = []
    if dates:
        date = dates[0]
        available = df[df[date].notna()].copy()
        index = pd.DatetimeIndex(available[date])
        span_days = (index.max().to_pydatetime() - index.min().to_pydatetime()).days
        frequency = "D" if span_days <= 120 else "W" if span_days <= 840 else "MS"
        months = (index.max().year-index.min().year)*12+index.max().month-index.min().month+1
        interval = max(1, math.ceil(months / 120)) if frequency == "MS" else 1
        rule = f"{interval}MS" if frequency == "MS" and interval > 1 else frequency
        indexed = available.set_index(date)
        row_counts = indexed.resample(rule).size()
        empty = int(row_counts.eq(0).sum())
        volume_dates = row_counts.index.strftime("%Y-%m-%d").tolist()
        charts.add("time",f"{short(date)} · 各时间桶记录数",f"按 {rule} 聚合日期有效的全部记录；0 表示该桶没有记录，不把指标缺失值当作 0。共 {empty} 个无记录桶。","time_volume",
            go.Figure(go.Bar(x=volume_dates,y=row_counts.tolist(),marker_color=COLORS[1])).update_layout(yaxis_title="日期有效记录数",showlegend=False),[date],wide=True)
        for metric in metric_order[:4]:
            series = indexed[metric].resample(rule)
            aggregate = series.agg(["count","mean","median"])
            aggregate["sum"] = series.sum(min_count=1)
            points = [{"date":stamp.strftime("%Y-%m-%d"),"n":int(row["count"]),"rows":int(row_counts.loc[stamp]),
                "mean":number(row["mean"]),"median":number(row["median"]),"sum":number(row["sum"])} for stamp,row in aggregate.iterrows()]
            notes = [f"按所选日期字段「{date}」和 {rule} 分桶；字符串日期统一为 UTC，原日期类型保留其时区。",
                     f"日期有效记录 {len(available):,} / 全体 {len(df):,} 行；缺失日期的 {len(df)-len(available):,} 行未参与日期分桶。",
                     "这是当前记录按日期条件进行的指标比较；是否代表事件时间取决于字段业务定义，不能默认解释为指标的历史轨迹或价格涨跌。",
                     "时间桶首尾可能不是完整周期；周频日期为周末桶标签，月频为起始日。",
                     "空桶指标为 null，折线断开；n 为指标非缺失数，rows 为日期有效记录数。sum 仅为算术和，未验证业务可加性。"]
            study = {"date_column":date,"metric":metric,"frequency":frequency,"bucket_interval":interval,"points":points,
                "start":str(index.min()),"end":str(index.max()),"total_buckets":len(row_counts),
                "nonempty_buckets":int(row_counts.gt(0).sum()),"empty_buckets":empty,
                "coverage_pct":round(float(row_counts.gt(0).mean())*100,3),"notes":notes}
            time_studies.append(study)
            figure = go.Figure(go.Scatter(x=[p["date"] for p in points],y=[p["mean"] for p in points],mode="lines",name="均值",connectgaps=False,
                customdata=[p["n"] for p in points],line={"color":COLORS[0]},hovertemplate="%{x}<br>均值 %{y:,.3g}<br>有效 n=%{customdata}<extra></extra>"))
            figure.add_trace(go.Scatter(x=[p["date"] for p in points],y=[p["median"] for p in points],mode="lines",name="中位数",connectgaps=False,line={"color":COLORS[2],"dash":"dot"}))
            charts.add("time",f"{short(metric)} · 按{short(date)}分桶的均值/中位数",f"按 {rule} 比较当前记录的非缺失值均值/中位数，不默认代表历史观测，不是算术和或增长因果；空桶保留断线。","line",figure,[date,metric],notes,wide=True)

    target_summary = "未指定关注字段；已按自动选择规则组织整体探索。"
    target_refs = []
    if target in selected:
        target_summary = f"已围绕数值关注字段「{target}」优先选择分布、成对关系、分组及时间证据；所有结论仅为描述性分析。"
        associations = []
        spearman_map = {frozenset((p["a"],p["b"])):p for p in spearman}
        for pair in pearson:
            if target in {pair["a"],pair["b"]}:
                other = pair["b"] if pair["a"] == target else pair["a"]
                rank_pair = spearman_map.get(frozenset((target,other)))
                associations.append((other,pair,rank_pair))
        if associations:
            figure = go.Figure(go.Bar(x=[a[0] for a in associations],y=[a[1]["r"] for a in associations],name="Pearson",customdata=[a[1]["n"] for a in associations],
                hovertemplate="%{x}<br>Pearson %{y:.3f}<br>成对 n=%{customdata}<extra></extra>"))
            figure.add_trace(go.Bar(x=[a[0] for a in associations],y=[a[2]["r"] if a[2] else None for a in associations],name="Spearman"))
            charts.add("target",f"{short(target)} · 关联证据对照","Pearson 与 Spearman 对照；每对单独处理缺失，不把相关系数当成因果或显著性。","target_association",figure,[target]+[a[0] for a in associations])
            driver = associations[0][0]
            complete = df[[driver,target]].dropna()
            if complete[driver].nunique() >= 4 and len(complete) >= 20:
                bins = pd.qcut(complete[driver],q=4,duplicates="drop")
                aggregate = complete.groupby(bins,observed=True)[target].agg(["count","mean","median"])
                aggregate = aggregate[aggregate["count"] >= 5]
                if len(aggregate) >= 2:
                    figure = go.Figure(go.Bar(x=[str(v) for v in aggregate.index],y=aggregate["mean"].tolist(),name="均值",customdata=aggregate["count"].tolist(),
                        hovertemplate="%{x}<br>关注指标均值 %{y:,.3g}<br>有效 n=%{customdata}<extra></extra>"))
                    figure.add_trace(go.Scatter(x=[str(v) for v in aggregate.index],y=aggregate["median"].tolist(),mode="markers",name="中位数"))
                    charts.add("target",f"{short(driver)}分位组下的{short(target)}","按驱动字段分位数划分最多 4 组，每组至少 5 个完整值；仅描述组内关注指标，不证明预测能力。","target_bins",figure,[driver,target])
        values = df[target].dropna()
        if len(values) >= 5 and values.min() >= 0 and values.sum() > 0:
            ordered = np.sort(values.to_numpy())
            cumulative = np.insert(np.cumsum(ordered)/ordered.sum(),0,0)
            positions = np.linspace(0,len(ordered),min(201,len(ordered)+1),dtype=int)
            charts.add("target",f"{short(target)} · 数值贡献集中度","按该指标值由小到大排序后计算累计份额；仅适用于非负可求和数值。算术份额不自动等于业务收入贡献。","target_concentration",
                go.Figure(go.Scatter(x=(positions/len(ordered)*100).tolist(),y=(cumulative[positions]*100).tolist(),mode="lines",name="累计数值份额")).add_trace(
                    go.Scatter(x=[0,100],y=[0,100],mode="lines",name="均等份额参考",line={"dash":"dot","color":"#94a3b8"})).update_layout(xaxis_title="由小到大累计记录比例（%）",yaxis_title="累计数值份额（%）"),[target],
                ["累计份额使用全部非缺失值精确计算，仅绘制最多 201 个等距记录位置；这不是抽样统计。"])
        target_groups = [g for g in groups if g["metric"] == target]
        if target_groups and values.mean() != 0:
            study = target_groups[0]
            baseline = float(values.mean())
            charts.add("target",f"{short(study['category'])} · 关注指标均值相对差","所选组均值相对全体有效值均值的百分比差，仅是描述性比较；有效 n 见提示，不能称差异显著。","target_group_gap",
                go.Figure(go.Bar(x=[g["group_id"]+" · "+short(g["label"]) for g in study["groups"]],
                    y=[(g["mean"]-baseline)/abs(baseline)*100 for g in study["groups"]],customdata=[g["n"] for g in study["groups"]],
                    marker_color=COLORS[4],hovertemplate="%{x}<br>相对全体均值差 %{y:.2f}%<br>有效 n=%{customdata}<extra></extra>")).update_layout(yaxis_title="相对全体均值差（%）",showlegend=False),[study["category"],target])
    elif target in selected_categories:
        target_summary = f"关注字段「{target}」是类别/布尔目标；已优先提供类别平衡和按该目标分组的数值比较，不对类别编码强行计算数值相关。"
    elif target in dates:
        target_summary = f"关注字段「{target}」是日期目标；已在时间专题提供记录覆盖与适用的数值趋势，不把日期强行编码为预测标签。"
    elif target in kinds:
        target_summary = f"关注字段「{target}」当前类型或有效变异不足以支持专项比较；保留画像，适用范围与排除原因见覆盖说明。"

    selected_charts = charts.selected()
    if target in dates:
        target_refs = [c["id"] for c in selected_charts if target in c["fields"] and c["section"] == "time"]
    elif target in selected_categories:
        target_refs = [c["id"] for c in selected_charts if target in c["fields"] and c["section"] in {"categories","groups"}]
    else:
        target_refs = [c["id"] for c in selected_charts if c["section"] == "target"]
    not_applicable = []
    reasons = {"quality":"当前没有可补充的质量图。","distributions":"没有至少 2 个有效值且存在变异的非标识符数值字段。",
        "categories":"没有满足类别数量、支持数和唯一比例阈值的非标识符类别字段。",
        "relationships":"没有至少两个有变异数值度量及至少 5 对完整样本；不强行构造相关关系。",
        "groups":"没有至少两个组各含 5 个有效数值的类别×度量组合。",
        "time":"没有合格真实日期字段与有变异数值度量组合；未将数字 ID 或年份强行作为时间。",
        "target":target_summary}
    sections = []
    for key,label,description in TOPICS:
        ids = [c["id"] for c in selected_charts if c["section"] == key]
        if key == "target" and target_refs:
            ids = target_refs
        sections.append({"key":key,"label":label,"description":description,"chart_ids":ids})
        if not ids:
            not_applicable.append({"section":key,"reason":reasons[key]})
    coverage = {"analyzed_rows":len(df),"eligible_numeric_fields":eligible,"selected_numeric_fields":selected,
        "selected_categorical_fields":selected_categories,"selected_datetime_fields":dates,"excluded_fields":excluded,
        "chart_count":len(selected_charts),"max_charts":MAX_CHARTS,"candidate_chart_count":len(charts.candidates),
        "omitted_chart_count":len(charts.candidates)-len(selected_charts),"not_applicable":not_applicable,
        "selection_notes":selection_notes,"sampling_notes":sampling_notes}
    eda = {"version":2,"sections":sections,"coverage":coverage,"distributions":distributions,"categories":categories,
        "correlations":{"pearson":pearson,"spearman":spearman},"groups":groups,"time":time_studies,
        "target":{"column":target if target in kinds else None,"kind":kinds.get(target),"summary":target_summary,"chart_ids":target_refs}}
    return selected_charts, eda


def deeper_insights(eda):
    insights = []
    def add(title,body,evidence,level="info"):
        insights.append({"title":title,"body":body,"evidence":evidence,"level":level})
    for item in sorted(eda["distributions"],key=lambda d: abs(d["skew"] or 0),reverse=True)[:3]:
        if item["skew"] is not None:
            add(f"{item['column']}的分布形状与尾部",f"样本偏度为 {item['skew']:.3f}，P05–P95 范围为 {display(item['p05'])}–{display(item['p95'])}。偏度只描述三阶形状，不构成正态性检验，也不能据均值与中位数相等断言对称。",
                f"有效 n={item['n']:,}；Q1={display(item['p25'])}，中位数={display(item['p50'])}，Q3={display(item['p75'])}；超额峰度={display(item['kurtosis'])}。")
    for item in sorted(eda["categories"],key=lambda c:c["top1_pct"],reverse=True)[:2]:
        add(f"{item['column']}的类别集中情况",f"最多的一类占有效记录 {item['top1_pct']:.2f}%，前 3 类合计 {item['top3_pct']:.2f}%。是否需要平衡样本取决于业务目标，不能仅据集中度判断数据好坏。",
            f"非缺失 n={item['n']:,}，类别数={item['unique']}，HHI={item['hhi']:.3f}（0–1），熵={item['entropy']:.3f} bits。")
    pearson_map = {frozenset((p["a"],p["b"])):p for p in eda["correlations"]["pearson"]}
    comparisons = [(p,pearson_map.get(frozenset((p["a"],p["b"])))) for p in eda["correlations"]["spearman"]]
    comparisons = [p for p in comparisons if p[1] is not None]
    comparisons.sort(key=lambda pair:abs(pair[0]["r"]-pair[1]["r"]),reverse=True)
    for rank, linear in comparisons[:2]:
        add(f"{rank['a']}与{rank['b']}的两种关联证据", "Pearson 衡量线性关系，Spearman 衡量排序的单调关系；差异可能来自非线性、极端值或并列值，不能直接确定原因或宣称显著性。",
            f"Pearson={linear['r']:.3f}，Spearman={rank['r']:.3f}，每对有效 n={rank['n']:,}。")
    for study in eda["groups"][:3]:
        high = max(study["groups"],key=lambda g:g["mean"])
        low = min(study["groups"],key=lambda g:g["mean"])
        add(f"{study['category']}分组下的{study['metric']}",f"在按支持数选出的组中，均值范围为 {display(low['mean'])}–{display(high['mean'])}；最高组为 {high['group_id']}「{high['label']}」，最低组为 {low['group_id']}「{low['label']}」。这里只描述所选组，不代表差异显著或分组造成结果。",
            f"最高组 n={high['n']}、中位数={display(high['median'])}；最低组 n={low['n']}、中位数={display(low['median'])}；每组至少 5 个有效值。")
    if eda["time"]:
        study = eda["time"][0]
        add("日期覆盖与样本量需一起阅读",f"记录日期范围 {study['start']} 至 {study['end']}，共 {study['total_buckets']} 个聚合桶，其中 {study['empty_buckets']} 个没有日期有效记录。按记录日期分桶不默认代表指标的历史观测；均值曲线与有效 n 应同时核对，不能把空期当成指标归零。",
            f"频率={study['frequency']}、间隔={study['bucket_interval']}；时间桶有记录覆盖率={study['coverage_pct']:.2f}%。")
    return insights


def model_evidence(eda):
    """Bounded aggregate-only evidence. Never expose raw category values."""
    focus = eda["target"]["column"]
    focus_studies = [study for study in eda["groups"] if study["metric"] == focus]
    ordered_studies = focus_studies + [study for study in eda["groups"] if study not in focus_studies]
    return {"coverage":{"selected_numeric_fields":eda["coverage"]["selected_numeric_fields"],
            "not_applicable":eda["coverage"]["not_applicable"]},
        "distributions":eda["distributions"][:8],
        "categories":[{key:item[key] for key in ("column","n","unique","top1_pct","top3_pct","hhi","entropy")} for item in eda["categories"]],
        "correlations":{"pearson":eda["correlations"]["pearson"][:8],"spearman":eda["correlations"]["spearman"][:8]},
        "groups":[{"category":study["category"],"metric":study["metric"],"selection_note":study["selection_note"],
            "groups":[{key:g[key] for key in ("group_id","n","mean","median","q25","q75")} for g in study["groups"][:6]]} for study in ordered_studies[:5]],
        "time":[{"date_column":study["date_column"],"metric":study["metric"],"frequency":study["frequency"],
            "bucket_interval":study["bucket_interval"],"total_buckets":study["total_buckets"],"empty_buckets":study["empty_buckets"],
            "notes":study["notes"],
            "selection_note":"只提供最近最多 12 个有指标值的日期桶，非全部日期范围；不能默认视为指标历史轨迹。", "points":[p for p in study["points"] if p["n"] > 0][-12:]}
            for study in eda["time"][:3]],"target":eda["target"]}
