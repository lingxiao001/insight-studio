"""Deterministic, bounded EDA. No generated code or dataset instructions are executed."""
import json
import math
import re
import time

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder

from .ingest import DatasetError

COLORS = ["#7E5555", "#6E8077", "#9B8B6F", "#71818A", "#9A7F88", "#8C8C6C"]
IDENTIFIER_NAME = re.compile(r"(^id$|[ _-]id$|^id[ _-]|编号|编码|邮编|手机号|身份证|(^|_)(index|uuid|code|zip|phone|sku)($|_))", re.I)


def finite(value):
    if value is None or pd.isna(value):
        return None
    result = float(value)
    if not math.isfinite(result):
        return None
    return 0.0 if result == 0 else result


def scalar(value):
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.number, int, float)):
        return finite(value)
    return str(value)[:200]


def short(value, limit=55):
    return str(value)[:limit]


def pretty(value):
    if value is None:
        return "无可用数据"
    if abs(value) >= 10000:
        return f"{value:,.0f}"
    return f"{value:,.3g}"


def detect_types(df):
    kinds = {}
    for name in df.columns:
        series = df[name]
        if pd.api.types.is_bool_dtype(series):
            kinds[name] = "boolean"
        elif pd.api.types.is_numeric_dtype(series):
            kinds[name] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            kinds[name] = "datetime"
        else:
            # Never infer Unix timestamps, numeric identifiers, ages or years as dates.
            sample = series.dropna().astype(str).head(200)
            has_date_shape = sample.str.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T].*)?$")
            if len(sample) and has_date_shape.mean() >= .95:
                parsed = pd.to_datetime(series, errors="coerce", format="mixed", utc=True)
                if parsed.notna().sum() == series.notna().sum():
                    df[name] = parsed
                    kinds[name] = "datetime"
                    continue
            kinds[name] = "categorical"
    return kinds


def is_identifier(name, series):
    if IDENTIFIER_NAME.search(name):
        return True
    clean = series.dropna()
    if len(clean) >= 20 and pd.api.types.is_numeric_dtype(clean):
        return (clean.nunique() / len(clean) > .95
                and (clean.is_monotonic_increasing or clean.is_monotonic_decreasing)
                and np.equal(clean, np.floor(clean)).all())
    return False


def column_profiles(df, kinds):
    profiles = []
    for name in df.columns:
        series = df[name]
        clean = series.dropna()
        kind = kinds[name]
        profile = {"name": name, "dtype": str(series.dtype), "kind": kind,
                   "missing": int(series.isna().sum()), "missing_pct": round(series.isna().mean() * 100, 3),
                   "unique": int(series.nunique())}
        if kind == "numeric":
            profile.update(mean=finite(clean.mean()), median=finite(clean.median()),
                           min=finite(clean.min()), max=finite(clean.max()), std=finite(clean.std()))
        elif kind == "datetime":
            profile.update(min=scalar(clean.min()), max=scalar(clean.max()))
        profiles.append(profile)
    return profiles


def quality_analysis(df, profiles, numeric):
    missing = int(df.isna().sum().sum())
    missing_pct = missing / df.size * 100
    duplicates = int(df.duplicated().sum())
    constant = sum(item["unique"] <= 1 for item in profiles)
    score = max(0, round(100 - missing_pct * .6 - duplicates / len(df) * 25 - constant / len(df.columns) * 15))
    outliers = {}
    for name in numeric:
        series = df[name].dropna()
        if len(series) < 4:
            continue
        q1, q3 = series.quantile([.25, .75])
        spread = q3 - q1
        if spread > 0:
            count = int(((series < q1 - 1.5 * spread) | (series > q3 + 1.5 * spread)).sum())
            if count:
                outliers[name] = {"count": count, "pct": round(count / len(series) * 100, 2),
                                  "lower": finite(q1 - 1.5 * spread), "upper": finite(q3 + 1.5 * spread)}
    return {"rows": len(df), "columns": len(df.columns),
            "numeric_columns": sum(p["kind"] == "numeric" for p in profiles),
            "categorical_columns": sum(p["kind"] in {"categorical", "boolean"} for p in profiles),
            "missing_cells": missing, "missing_pct": round(missing_pct, 3),
            "duplicate_rows": duplicates, "quality_score": score}, outliers


def correlation_pairs(df, numeric):
    eligible = [name for name in numeric if df[name].notna().sum() >= 5 and df[name].nunique() > 1]
    pairs = []
    corr = df[eligible].corr(min_periods=5) if eligible else pd.DataFrame()
    for i, a in enumerate(eligible):
        for b in eligible[i + 1:]:
            value = finite(corr.loc[a, b])
            if value is not None:
                count = int(df[[a, b]].notna().all(axis=1).sum())
                pairs.append({"a": a, "b": b, "r": value, "n": count})
    return sorted(pairs, key=lambda item: abs(item["r"]), reverse=True), corr


def charts_for(df, kinds, numeric, excluded, target, pairs, corr):
    charts = []

    def add(title, description, kind, figure, wide=False):
        figure.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)",
                             plot_bgcolor="rgba(0,0,0,0)", font={"family": "Arial, sans-serif", "color": "#334155", "size": 12},
                             colorway=COLORS, margin={"l": 55, "r": 20, "t": 25, "b": 65},
                             height=330, showlegend=False, hoverlabel={"namelength": 50})
        figure.update_xaxes(gridcolor="#eef2f6", zeroline=False, automargin=True)
        figure.update_yaxes(gridcolor="#eef2f6", zeroline=False, automargin=True)
        charts.append({"id": f"chart-{len(charts) + 1}", "title": title,
                       "description": description, "type": kind,
                       "figure": json.loads(json.dumps(figure.to_plotly_json(), cls=PlotlyJSONEncoder)), "wide": wide})

    missing = df.isna().mean().mul(100).sort_values(ascending=False).head(15)
    add("各字段缺失率", "基于全部分析行；缺失率为缺失单元格数 / 行数。", "missingness",
        go.Figure(go.Bar(x=[short(x) for x in missing.index], y=missing.round(3).tolist(), marker_color=COLORS[0],
                         hovertemplate="%{x}<br>缺失率 %{y:.2f}%<extra></extra>")).update_layout(
                             yaxis_title="缺失率（%）", yaxis_range=[0, min(100, max(1, float(missing.max()) * 1.12))]))
    metrics = [name for name in numeric if df[name].notna().any()]
    if target in metrics:
        metrics.remove(target)
        metrics.insert(0, target)
    # Sampling only controls figure size; descriptive statistics use all analyzed rows.
    for name in metrics[:2]:
        values = df[name].dropna()
        if len(values):
            counts, bins = np.histogram(values, bins=min(32, max(1, int(np.sqrt(len(values))))))
            centers = ((bins[:-1] + bins[1:]) / 2).tolist()
            add(f"{short(name)} · 数值分布", "在全部分析行上计算分箱计数；柱高表示记录数。", "histogram",
                go.Figure(go.Bar(x=centers, y=counts.tolist(), width=np.diff(bins).tolist(), marker_color=COLORS[len(charts) % len(COLORS)])))
    categories = [name for name in df.columns if kinds[name] in {"categorical", "boolean"}
                  and name not in excluded and 1 < df[name].nunique() <= 500
                  and df[name].nunique() / max(len(df), 1) <= .7]
    for name in categories[:2]:
        counts = df[name].dropna().astype(str).value_counts().head(12)
        add(f"{short(name)} · 类别构成", "展示记录数最多的 12 个类别；不包含缺失值。", "bar",
            go.Figure(go.Bar(x=[short(x) for x in counts.index], y=counts.tolist(), marker_color=COLORS[len(charts) % len(COLORS)])))
    if metrics:
        name = metrics[0]
        values = df[name].dropna()
        # Explicit quantiles/whiskers preserve full-data statistics without sending every row.
        q1, med, q3 = values.quantile([.25, .5, .75])
        iqr = q3 - q1
        inside = values.between(q1 - 1.5 * iqr, q3 + 1.5 * iqr)
        add(f"{short(name)} · 箱线分布", "箱体为第 25–75 百分位，须线为 1.5×IQR 范围内的实际极值。", "box",
            go.Figure(go.Box(q1=[float(q1)], median=[float(med)], q3=[float(q3)],
                             lowerfence=[finite(values[inside].min())], upperfence=[finite(values[inside].max())],
                             x=[short(name)], name=short(name), marker_color=COLORS[2], boxpoints=False)))
    if len(corr.columns) >= 2:
        columns = list(corr.columns[:12])
        add("数值字段相关性", "Pearson 线性相关；按成对非缺失值计算，至少 5 对。已排除疑似标识符；相关不代表因果。", "heatmap",
            go.Figure(go.Heatmap(z=corr.loc[columns, columns].where(pd.notna(corr), None).values.tolist(),
                                x=[short(x) for x in columns], y=[short(x) for x in columns],
                                colorscale=[[0, "#c9b8ef"], [.5, "#f3f5fa"], [1, "#0f9f95"]], zmin=-1, zmax=1,
                                colorbar={"thickness": 10, "len": .8}, hovertemplate="%{x} × %{y}<br>r=%{z:.3f}<extra></extra>")))
    if pairs:
        pair = next((p for p in pairs if target in {p["a"], p["b"]}), pairs[0])
        points = df[[pair["a"], pair["b"]]].dropna()
        sampled = len(points) > 1500
        if sampled:
            points = points.sample(1500, random_state=42)
        add(f"{short(pair['a'])} × {short(pair['b'])}",
            f"相关系数 r={pair['r']:.3f}（{pair['n']:,} 对完整值）。" + ("散点固定种子抽样 1,500 点。" if sampled else "显示全部完整值。"), "scatter",
            go.Figure(go.Scattergl(x=points[pair["a"]].tolist(), y=points[pair["b"]].tolist(), mode="markers",
                                  marker={"color": COLORS[0], "size": 6, "opacity": .5})).update_layout(
                xaxis_title=short(pair["a"]), yaxis_title=short(pair["b"])))
    dates = [name for name in df.columns if kinds[name] == "datetime" and df[name].notna().sum() >= 2]
    if dates and metrics:
        date, metric = dates[0], metrics[0]
        time_values = df[[date, metric]].dropna().set_index(date)[metric]
        span_days = (time_values.index.max().to_pydatetime() - time_values.index.min().to_pydatetime()).days if len(time_values) else 0
        if len(time_values) > 1 and span_days > 0:
            rule = "D" if span_days <= 120 else "W" if span_days <= 1000 else "MS"
            trend = time_values.resample(rule).agg(["mean", "count"])
            trend = trend[trend["count"] > 0]
            add(f"{short(metric)} · 时间趋势", f"按{'日' if rule == 'D' else '周' if rule == 'W' else '月'}计算非缺失值均值；空时间段省略。",
                "line", go.Figure(go.Scatter(x=trend.index.strftime("%Y-%m-%d").tolist(),
                                             y=trend["mean"].round(6).tolist(), mode="lines",
                                             line={"color": COLORS[0], "width": 2}, fill="tozeroy",
                                             fillcolor="rgba(15,159,149,.07)")), True)
    if categories and metrics:
        category, metric = categories[0], metrics[0]
        group = df.groupby(category, observed=True)[metric].agg(["mean", "count"]).sort_values("count", ascending=False).head(10)
        group = group[group["count"] >= 3].sort_values("mean", ascending=False)
        if len(group) > 1:
            add(f"{short(category)}下的{short(metric)}均值", "展示记录数最多的 10 组且每组至少 3 个有效值；组间差异为描述性比较。", "grouped_bar",
                go.Figure(go.Bar(x=[short(x) for x in group.index], y=group["mean"].round(6).tolist(),
                                 customdata=group["count"].tolist(), marker_color=COLORS[1],
                                 hovertemplate="%{x}<br>均值 %{y:,.2f}<br>有效记录 %{customdata}<extra></extra>")))
    # Null matrix cells / floating arithmetic overflow must never produce invalid JSON.
    return json.loads(json.dumps(charts, cls=PlotlyJSONEncoder))


def statistical_insights(df, profiles, overview, outliers, pairs, numeric, excluded, target, goal):
    insights = []
    recommendations = []

    def add(title, body, evidence, level="info"):
        insights.append({"title": title, "body": body, "evidence": evidence, "level": level})

    add("数据质量评分的含义", f"当前启发式质量评分为 {overview['quality_score']}/100。它只衡量缺失、重复和常量列，不代表数据真实性、代表性或模型准确率。",
        "公式：100 − 缺失单元格百分比×0.6 − 重复行比例×25 − 常量列比例×15，下限为 0。")
    missing_profiles = sorted([p for p in profiles if p["missing"]], key=lambda p: p["missing_pct"], reverse=True)
    if missing_profiles:
        highest = missing_profiles[0]
        add("缺失值需要按业务含义处理", f"「{highest['name']}」缺失比例最高，达到 {highest['missing_pct']:.2f}%。避免直接用 0 代替未知值；可先检查缺失是否集中在特定人群或时间段。",
            f"{highest['missing']:,} / {len(df):,} 行缺失；全表缺失率 {overview['missing_pct']:.2f}%。", "warning")
        recommendations.append("核查缺失值来源，并按字段含义选择保留、删除或插补；插补前后分别复核分布。")
    else:
        add("未检测到缺失单元格", "当前分析范围内所有字段均有值，仍需结合业务检查空字符串、占位值和不合法编码。", f"{df.size:,} 个单元格；pandas 缺失值识别规则。", "success")
    if overview["duplicate_rows"]:
        add("存在完全重复的记录", "重复行可能来自重复导入，也可能是合法的相同行为；建议结合业务主键确认后再去重。",
            f"除首次出现外，共 {overview['duplicate_rows']:,} 行完全重复。", "warning")
        recommendations.append("结合业务主键与时间字段验证重复记录，确认后再去重。")
    if outliers:
        name, values = max(outliers.items(), key=lambda item: item[1]["pct"])
        add(f"{name}中存在潜在极端值", "IQR 规则仅用于提示，极端值也可能是真实的重要事件。建议检查单位、录入错误及业务上下限。",
            f"非缺失值中 {values['count']:,} 个（{values['pct']:.2f}%）超出 [{pretty(values['lower'])}, {pretty(values['upper'])}]。", "warning")
        recommendations.append("逐一核查 IQR 提示的极端值；保留原始数据，避免未经验证直接删除。")
    if pairs:
        pair = next((p for p in pairs if target in {p["a"], p["b"]}), pairs[0])
        magnitude = abs(pair["r"])
        if magnitude < .1:
            body = f"「{pair['a']}」与「{pair['b']}」的 Pearson 相关系数接近零，当前样本未见明显线性关联。这不排除非线性关系或分组差异，仍需结合业务假设验证。"
        else:
            strength = "较强" if magnitude >= .7 else "中等" if magnitude >= .4 else "较弱"
            body = f"「{pair['a']}」与「{pair['b']}」呈{strength}{'正' if pair['r'] >= 0 else '负'}线性关联。相关不等于因果；可能受到分组差异、时间变化或极端值影响。"
        add("数值关系值得继续验证", body,
            f"Pearson r={pair['r']:.3f}，基于 {pair['n']:,} 对非缺失值；疑似标识符已排除。")
        if magnitude >= .4:
            recommendations.append("对相关性较高的变量分组复核，并用业务假设和独立数据验证，避免直接推断因果。")
        else:
            recommendations.append("围绕业务假设检查分组差异或非线性关系，并用独立数据验证；当前线性相关不足以支持明确的关系判断。")
    if excluded:
        add("疑似标识符已从数值关系中排除", f"已排除：{'、'.join(excluded[:8])}。字段名或连续唯一整数触发此启发式规则，请按业务含义复核。",
            "这些字段仍保留在数据画像和预览中；不参与相关性、散点或数值分布选择。")
    focus = target if target in numeric else next((name for name in numeric if name.lower() in goal.lower()), None)
    if focus:
        series = df[focus].dropna()
        add(f"围绕{focus}的重点观察", f"该指标均值为 {pretty(finite(series.mean()))}，中位数为 {pretty(finite(series.median()))}。可结合时间或业务分组进一步排查差异；这些统计不包含缺失值。",
            f"有效值 {len(series):,}，范围 {pretty(finite(series.min()))} 至 {pretty(finite(series.max()))}。")
        recommendations.insert(0, f"围绕「{focus}」建立业务口径，比较时间和类别分组，并验证当前分析目标中的假设。")
    if not numeric:
        add("当前数据缺少可比较的数值度量", "已生成字段缺失情况、类别分布和数据画像。没有为编码或纯文本强行构造相关性与时间趋势。",
            f"识别到 {overview['numeric_columns']} 个数值列，剔除标识符后可用度量 {len(numeric)} 个。")
    if not recommendations:
        recommendations.append("确认各字段的业务定义与采集口径，再选择有意义的指标和分组开展后续分析。")
    return insights[:10], recommendations[:6]


def analyze(df, source, goal, target, progress):
    started = time.monotonic()
    progress("profile", "识别字段类型并计算描述性统计。")
    # Squared deviations and histogram bin arithmetic can overflow long before
    # IEEE-754's absolute maximum. Reject explicitly rather than inventing null stats.
    if any(df[name].dropna().abs().gt(1e150).any() for name in df.select_dtypes(include=["number"]).columns):
        raise DatasetError("部分数值的绝对值超过安全分析范围（1e150），请先缩放计量单位后重新上传。")
    kinds = detect_types(df)
    profiles = column_profiles(df, kinds)
    excluded = [name for name in df.columns if is_identifier(name, df[name])]
    if target in excluded and kinds[target] == "numeric":
        if not IDENTIFIER_NAME.search(target):
            # An explicit business metric takes precedence over the weaker
            # monotonic-integer heuristic, while named IDs stay excluded.
            excluded.remove(target)
            source["notes"].append(f"「{target}」虽为单调唯一整数，已按用户明确选择的关注字段保留为数值度量。")
        else:
            source["notes"].append(f"关注字段「{target}」名称疑似标识符，仍只保留在字段画像与预览中，不参与数值关系分析；请核对业务含义。")
    numeric = [name for name in df.columns if kinds[name] == "numeric" and name not in excluded]
    if target and target not in df.columns:
        source["notes"].append("指定的目标字段不存在，本次使用自动字段选择。")
        target = None
    progress("quality", "检查缺失值、完整重复记录和 IQR 极端值。")
    overview, outliers = quality_analysis(df, profiles, numeric)
    progress("charts", "分七个专题计算分布、缺失模式、分组比较、多指标时间趋势与两种相关关系。")
    from .deep_eda import build_eda, deeper_insights, model_evidence
    charts, eda = build_eda(df, kinds, profiles, numeric, excluded, target, goal)
    pairs = eda["correlations"]["pearson"]
    progress("insights", "根据统计证据生成洞察及下一步建议。")
    insights, recommendations = statistical_insights(df, profiles, overview, outliers, pairs, numeric, excluded, target, goal)
    insights = (insights + deeper_insights(eda))[:24]
    summary = (f"本次分析 {len(df):,} 行、{len(df.columns)} 个字段，识别到 {overview['numeric_columns']} 个数值字段，"
               f"缺失率 {overview['missing_pct']:.2f}%，完全重复记录 {overview['duplicate_rows']:,} 行。"
               f"已按七个分析专题生成 {len(charts)} 张统计图；具体字段选择、抽样与不适用原因见覆盖说明。")
    if source["is_demo"]:
        summary = "此报告使用合成零售演示数据。" + summary
    result = {"title": "合成零售数据探索报告" if source["is_demo"] else "数据探索分析报告",
              "summary": summary, "source": source, "overview": overview, "columns": profiles,
              "charts": charts, "eda": eda, "insights": insights, "recommendations": recommendations,
              "preview": {"columns": list(df.columns), "rows": [[scalar(v) for v in row] for row in df.head(12).itertuples(index=False, name=None)]},
              "agent": {"mode": "statistical", "model": None,
                        "notes": ["统计分析由固定 Python 分析步骤执行；未执行模型生成代码。", "所有统计均基于本次分析行；散点图若抽样会单独标明。", "数值相关性不代表因果关系；IQR 结果不等同于错误数据。"]},
              "duration_seconds": round(time.monotonic() - started, 2)}
    # Restrict external model input to bounded aggregate statistics, never preview rows or category values.
    aggregates = {"overview": overview, "columns": profiles[:80], "correlations": pairs[:8],
                  "outliers": dict(list(outliers.items())[:10]), "excluded_identifiers": excluded[:20],
                  "eda_evidence": model_evidence(eda)}
    return result, aggregates
