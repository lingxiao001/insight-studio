from html import escape
import json
from pathlib import Path

from plotly.offline import get_plotlyjs

REPORT_STYLE = """
:root{color-scheme:light;--paper:#F8F7F3;--sheet:#FFFDF9;--ink:#302F2B;--muted:#746F66;--line:#D8D3C9;--accent:#762B38}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.85 "Helvetica Neue","PingFang SC","Hiragino Sans GB",system-ui,sans-serif}
main{max-width:1180px;margin:auto;padding:56px 28px}h1,h2,h3{font-family:"Songti SC","Noto Serif CJK SC","STSong",serif}h1{font-size:32px;font-weight:500;letter-spacing:.02em;margin:14px 0 18px}h2{font-size:22px;font-weight:500;margin:0 0 16px}h3{font-size:17px;font-weight:500;margin:0}p{color:var(--muted);white-space:pre-wrap;overflow-wrap:anywhere}
a{color:var(--accent);text-underline-offset:4px}button{border:1px solid var(--accent);border-radius:2px;background:var(--accent);color:var(--sheet);padding:10px 16px;font:inherit;cursor:pointer}button:disabled{opacity:.6;cursor:wait}
.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(390px,1fr));gap:24px}.chart,.panel{background:var(--sheet);border:1px solid var(--line);border-radius:3px;padding:28px;margin:32px 0}.chart{min-width:0;margin:0}.badge{color:var(--accent);font-size:12px;font-weight:600;letter-spacing:.15em}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:32px 0}.metric{background:var(--sheet);border:1px solid var(--line);padding:24px;border-radius:3px}.metric small{display:block;color:var(--muted)}.metric strong{display:block;font-size:28px;font-weight:400;color:var(--ink);margin-top:8px;font-variant-numeric:tabular-nums}
.insight{border-bottom:1px solid var(--line);padding:24px 0}.insight:last-child{border:0}.evidence{font-size:13px;background:#F1EEE7;border-left:2px solid #9B8B6F;padding:12px 16px;color:var(--muted)}dl{display:grid;grid-template-columns:110px 1fr;gap:10px}dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}li{margin:9px 0;overflow-wrap:anywhere}
details{margin:14px 0}summary{cursor:pointer;color:var(--ink);padding:12px 0;border-bottom:1px solid var(--line)}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}td,th{text-align:left;padding:12px;border-bottom:1px solid var(--line);white-space:nowrap}th{color:var(--muted);background:#F1EEE7;font-weight:500}footer{color:var(--muted);font-size:12px;margin-top:40px;padding-top:20px;border-top:1px solid var(--line)}
@media(max-width:700px){main{padding:32px 16px}.charts{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,1fr)}.chart,.panel{padding:20px}h1{font-size:26px}}
@media print{body{background:white}main{max-width:none}.panel,.chart{break-inside:avoid}.charts{display:block}.chart{margin:20px 0}button{display:none}}
"""

LAZY_RENDER_JS = r"""
const nodes = Array.from(document.querySelectorAll('script[type="application/json"][data-chart]'));
const loaded = new Map();
function renderChart(node) {
  if (loaded.has(node.id)) return loaded.get(node.id);
  const figure = JSON.parse(node.textContent);
  const target = document.getElementById(node.dataset.chart);
  const promise = Promise.resolve(Plotly.newPlot(target, figure.data, figure.layout,
    {responsive:true,displaylogo:false}));
  loaded.set(node.id,promise);
  return promise;
}
if ('IntersectionObserver' in window) {
  const observer = new IntersectionObserver(entries => entries.forEach(entry => {
    if (entry.isIntersecting) {
      const node = document.getElementById(entry.target.id + '-data');
      renderChart(node).catch(() => {entry.target.textContent='图表加载失败，可查看下方统计表。';});
      observer.unobserve(entry.target);
    }
  }), {rootMargin:'200px'});
  nodes.forEach(node => observer.observe(document.getElementById(node.dataset.chart)));
} else { nodes.forEach(renderChart); }
const printButton = document.getElementById('prepare-print');
if (printButton) printButton.addEventListener('click', async () => {
  printButton.disabled=true;
  printButton.textContent='正在准备全部图表，请等待…';
  await Promise.allSettled(nodes.map(renderChart));
  document.querySelectorAll('details').forEach(element => {element.open=true;});
  printButton.textContent='全部图表已准备，可以打印';
  printButton.disabled=false;
  window.print();
});
"""


def md_text(value):
    # Avoid injected links/images/headings when a dataset has adversarial names.
    text = str(value).replace("\\", "\\\\")
    for char in "`*_{}[]<>()#|!":
        text = text.replace(char, "\\" + char)
    return text.replace("\n", " ").replace("\r", " ")


def report_tables(eda):
    tables = [("分布与尾部统计", ["字段","有效 n","均值","中位数","标准差","P05","Q1","Q3","P95","偏度","超额峰度","IQR 极端值数"],
        [[d[key] for key in ("column","n","mean","median","std","p05","p25","p75","p95","skew","kurtosis","outlier_count")] for d in eda["distributions"]]),
        ("类别集中度",["字段","非缺失 n","类别数","Top1 %","Top3 %","HHI (0–1)","熵 (bits)"],
         [[c[key] for key in ("column","n","unique","top1_pct","top3_pct","hhi","entropy")] for c in eda["categories"]])]
    for study in eda["groups"]:
        tables.append((f"分组证据：{study['category']} × {study['metric']}",
            ["别名","类别原名","有效 n","均值","中位数","Q1","Q3","算术和"],
            [[g[key] for key in ("group_id","label","n","mean","median","q25","q75","sum")] for g in study["groups"]]))
    for study in eda["time"]:
        tables.append((f"时间证据：{study['date_column']} × {study['metric']}（{study['bucket_interval']}×{study['frequency']}）",
            ["时间桶","日期有效记录","指标有效 n","均值","中位数","算术和"],
            [[p[key] for key in ("date","rows","n","mean","median","sum")] for p in study["points"]]))
    return [(title,headers,rows) for title,headers,rows in tables if rows]


def report_value(value):
    if value is None:
        return "—"
    return f"{value:.8g}" if isinstance(value, float) else str(value)


def deep_markdown(eda):
    if not eda:
        return []
    coverage = eda["coverage"]
    lines = ["", "## 深度 EDA 覆盖与选择", "", md_text(eda["target"]["summary"]), "",
        f"- EDA 版本：{eda['version']}；唯一图表 {coverage['chart_count']} / 上限 {coverage['max_charts']}；已选字段内图表候选 {coverage['candidate_chart_count']}，省略 {coverage['omitted_chart_count']}。",
        f"- 数值字段：{md_text('、'.join(coverage['selected_numeric_fields']) or '无')}；合理候选 {len(coverage['eligible_numeric_fields'])} 个。",
        f"- 类别字段：{md_text('、'.join(coverage['selected_categorical_fields']) or '无')}。",
        f"- 日期字段：{md_text('、'.join(coverage['selected_datetime_fields']) or '无')}。"]
    lines += ["- " + md_text(note) for note in coverage["selection_notes"] + coverage["sampling_notes"]]
    lines += ["", "### 不适用与排除原因", ""]
    lines += [f"- {md_text(item['field'])}：{md_text(item['reason'])}" for item in coverage["excluded_fields"]]
    lines += [f"- 专题 {md_text(item['section'])}：{md_text(item['reason'])}" for item in coverage["not_applicable"]]
    lines += ["", "分组 G01 等别名在下方本地表中对应原类别；外部模型只收到别名和聚合统计。空时间桶指标为 —，不补零；n 为指标非缺失记录数。算术和未验证业务可加性。显示数字最多保留 8 位有效数字，统计计算保留原精度。", ""]
    for title,headers,rows in report_tables(eda):
        lines += ["### " + md_text(title), "", "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        lines += ["| " + " | ".join(md_text(report_value(v)) for v in row) + " |" for row in rows]
        lines.append("")
    return lines


def deep_html(eda):
    if not eda:
        return ""
    c = eda["coverage"]
    notes = "".join("<li>" + escape(note) + "</li>" for note in c["selection_notes"] + c["sampling_notes"])
    omissions = "".join(f'<li><strong>{escape(item["field"])}</strong>：{escape(item["reason"])}</li>' for item in c["excluded_fields"])
    omissions += "".join(f'<li>专题 {escape(item["section"])}：{escape(item["reason"])}</li>' for item in c["not_applicable"])
    tables = []
    for title,headers,rows in report_tables(eda):
        heading = "".join("<th>"+escape(h)+"</th>" for h in headers)
        values = "".join("<tr>"+"".join("<td>"+escape(report_value(v))+"</td>" for v in row)+"</tr>" for row in rows)
        tables.append(f'<details class="evidence-table"><summary>{escape(title)} · {len(rows)} 行</summary><div class="table-wrap"><table><thead><tr>{heading}</tr></thead><tbody>{values}</tbody></table></div></details>')
    return (f'<section class="panel"><h2>深度 EDA 覆盖与选择</h2><p>{escape(eda["target"]["summary"])}</p>'
        f'<p>EDA v{eda["version"]} · 唯一图表 {c["chart_count"]} / 上限 {c["max_charts"]} · 已选字段内候选 {c["candidate_chart_count"]} · 省略 {c["omitted_chart_count"]}</p>'
        f'<p>合理数值候选 {len(c["eligible_numeric_fields"])}，已选 {len(c["selected_numeric_fields"])}；已选类别 {len(c["selected_categorical_fields"])}，日期 {len(c["selected_datetime_fields"])}。</p>'
        f'<ul>{notes}</ul><details><summary>不适用与字段排除原因</summary><ul>{omissions or "<li>无额外排除说明。</li>"}</ul></details></section>'
        '<section class="panel"><h2>可复算的聚合证据</h2><p>点击展开完整表格。G01 等别名只在同一类别字段下对应原类别；外部模型不接收类别原名。空期指标为 —，不补零。算术和未验证业务可加性；显示数字最多 8 位有效数字，统计计算保留原精度。</p>'
        + "".join(tables) + "</section>")


def brief_group_table(item):
    groups = item.get("groups", [])
    if not groups:
        return [], []
    proportional = "rate_pct" in groups[0]
    if proportional:
        count_label = "事件数" if item.get("method") == "event_rate" else "所比较原始取值记录数"
        headers = ["别名", "类别或区间", "有效 n", count_label, "比例 %", "展示支持"]
        rows = [[g.get("group_id", f"G{index:02d}"), g["label"], g["n"], g["events"], g["rate_pct"],
                 "达到20条" if g["supported"] else "不足20条"] for index,g in enumerate(groups,1)]
    else:
        headers = ["别名", "类别或区间", "有效 n", "均值", "中位数", "展示支持"]
        rows = [[g.get("group_id", f"G{index:02d}"), g["label"], g["n"], g["mean"], g["median"],
                 "达到20条" if g["supported"] else "不足20条"] for index,g in enumerate(groups,1)]
    return headers, rows


def brief_group_markdown(item):
    headers, rows = brief_group_table(item)
    if not rows:
        return []
    return ["分组依据（支持不足的小组也保留）：", "", "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(md_text(report_value(v)) for v in row) + " |" for row in rows], ""]


def brief_group_html(item):
    headers, rows = brief_group_table(item)
    if not rows:
        return ""
    heading = "".join("<th>" + escape(h) + "</th>" for h in headers)
    body = "".join("<tr>" + "".join("<td>" + escape(report_value(v)) + "</td>" for v in row) + "</tr>" for row in rows)
    return ('<p>分组依据（支持不足的小组也保留）：</p><div class="table-wrap"><table><thead><tr>'
            + heading + "</tr></thead><tbody>" + body + "</tbody></table></div>")


def brief_markdown(brief):
    if not brief:
        return []
    lines = ["## 先看结论", "", md_text(brief["answer"]), ""]
    if brief.get("question_answers"):
        lines += ["### 对问题逐项回答", ""]
        for item in brief["question_answers"]:
            lines += ["#### " + md_text(item["question"]), "", md_text(item["answer"]), "",
                      md_text(item["explanation"]), "", "依据：" + md_text(item["evidence"]), "",
                      "解释边界：" + md_text(item["caveat"]), "", "下一步：" + md_text(item["next_step"]), ""]
            lines += brief_group_markdown(item)
    for item in brief["findings"]:
        lines += ["### " + md_text(item["title"]), "", md_text(item["takeaway"]), "",
                  md_text(item["explanation"]), "", "依据：" + md_text(item["evidence"]), "",
                  "解释边界：" + md_text(item["caveat"]), "", "下一步：" + md_text(item.get("next_step", "核对字段口径。")), ""]
        lines += brief_group_markdown(item)
    lines += ["### 接下来可以了解", ""] + ["- " + md_text(q) for q in brief["next_questions"]]
    lines += ["", "### 本次解释的范围", ""] + ["- " + md_text(c) for c in brief["caveats"]] + [""]
    return lines


def brief_html(brief):
    if not brief:
        return ""
    statuses = {"supported": "观察到共同变化", "partial": "未见清晰单调关系", "insufficient": "暂不足以判断"}
    answers = "".join(f'<article class="insight"><small>{escape(i.get("status_label") or statuses.get(i["status"], "问题回答"))}</small>'
                      f'<h3>{escape(i["question"])}</h3><p>{escape(i["answer"])}</p><p>{escape(i["explanation"])}</p>'
                      f'<details><summary>查看依据与解释边界 · {i["n"]} 条有效记录</summary><p>{escape(i["evidence"])}</p>'
                      f'<p>{escape(i["caveat"])}</p>{brief_group_html(i)}</details><p>下一步：{escape(i["next_step"])}</p></article>'
                      for i in brief.get("question_answers", []))
    cards = "".join(f'<article class="insight"><h3>{escape(i["title"])}</h3><p>{escape(i["takeaway"])}</p>'
                    f'<p>{escape(i["explanation"])}</p><details><summary>查看依据与解释边界 · {i["n"]} 条有效记录</summary>'
                    f'<p>{escape(i["evidence"])}</p><p>{escape(i["caveat"])}</p>{brief_group_html(i)}</details>'
                    f'<p>下一步：{escape(i.get("next_step", "核对字段口径。"))}</p></article>' for i in brief["findings"])
    questions = "".join(f'<li>{escape(q)}</li>' for q in brief["next_questions"])
    caveats = "".join(f'<li>{escape(c)}</li>' for c in brief["caveats"])
    answer_heading = "<h3>对问题逐项回答</h3>" if answers else ""
    return f'<section class="panel"><h2>先看结论</h2><p>{escape(brief["answer"])}</p>{answer_heading}{answers}{cards}<h3>接下来可以了解</h3><ul>{questions}</ul><details><summary>本次解释的范围</summary><ul>{caveats}</ul></details></section>'


def render_markdown(result, goal):
    source, overview = result["source"], result["overview"]
    projection = source.get("quality_scope") == "selected_fields"
    lines = [f"# {md_text(result['title'])}", "", md_text(result["summary"]), "", *brief_markdown(result.get("brief")), "## 来源与范围", "",
             f"- 来源：{md_text(source['filename'])}",
             f"- 演示数据：{'是；合成生成，不代表真实业务' if source['is_demo'] else '否'}",
             f"- 分析行数：{overview['rows']:,}；字段数：{overview['columns']}；截取：{'是' if source['sampled'] else '否'}",
             f"- 分析目标：{md_text(goal or '自动探索数据质量、分布与潜在关系。')}",
             f"- Agent 模式：{result['agent']['mode']}"]
    if source.get("sheet"):
        lines.append(f"- 工作表：{md_text(source['sheet'])}")
    lines.extend(f"- {md_text(note)}" for note in source["notes"])
    lines += ["", "## 核心指标", "", "| 指标 | 数值 |", "| --- | --- |",
              f"| 缺失单元格 | {overview['missing_cells']:,} |",
              f"| 缺失率 | {overview['missing_pct']:.2f}% |"]
    if projection:
        lines += ["", "本例只保留选定分析字段。同值记录不等于同一业务记录，不据此对原始数据作质量评级或去重。"]
    else:
        lines += [f"| 完全重复行 | {overview['duplicate_rows']:,} |",
                  f"| 启发式质量评分 | {overview['quality_score']} / 100 |"]
    lines += ["", "## 数据洞察", ""]
    for insight in result["insights"]:
        lines += [f"### {md_text(insight['title'])}", "", md_text(insight["body"]), "",
                  f"统计依据：{md_text(insight['evidence'])}", ""]
    if result["agent"].get("narrative"):
        lines += ["## Agent 分析", "", md_text(result["agent"]["narrative"]), ""]
    lines += ["## 建议与下一步", ""] + [f"{i + 1}. {md_text(item)}" for i, item in enumerate(result["recommendations"])]
    lines += deep_markdown(result.get("eda"))
    lines += ["", "## 图表目录", ""]
    chart_map = {chart["id"]:chart for chart in result["charts"]}
    sections = (result.get("eda") or {}).get("sections", [{"label":"图表探索","description":"","chart_ids":list(chart_map)}])
    for section in sections:
        lines += ["### " + md_text(section["label"]), "", md_text(section["description"]), ""]
        for chart_id in section["chart_ids"]:
            chart = chart_map[chart_id]
            lines += [f"- {md_text(chart['title'])}：{md_text(chart['description'])}"]
            lines += ["  - " + md_text(note) for note in chart.get("sample_notes", [])]
        if not section["chart_ids"]:
            lines += ["本专题无适用图表，原因见覆盖说明。"]
    lines += ["", "完整交互图表见同任务下载的 HTML 报告；HTML 已内嵌 Plotly，无需联网。", "", "## 字段画像", "",
              "| 字段 | 类型 | 非缺失唯一值 | 缺失率 | 均值 | 中位数 |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for column in result["columns"]:
        lines.append(f"| {md_text(column['name'])} | {column['kind']} | {column['unique']:,} | {column['missing_pct']:.2f}% | {report_value(column.get('mean'))} | {report_value(column.get('median'))} |")
    lines += ["", "## 方法与局限", "",
              "- 缺失值、均值、分位数、IQR 和 Pearson 相关均基于本次分析行；没有自动清洗或删除原始记录。",
              "- 重复行数不包含首次出现的记录；数值相关性至少需要 5 对完整值，已排除疑似标识符。",
              "- 质量分为启发式指标：100 − 缺失单元格百分比×0.6 − 重复行比例×25 − 常量列比例×15，下限 0。",
              "- IQR 使用 Q1−1.5×IQR 与 Q3+1.5×IQR；潜在极端值不等于错误值；相关不代表因果。",
              "- 日期只识别真实日期型或明确的年/月/日文本；不会将数值 ID 或年份强行转换为时间。"]
    if projection:
        lines = [line for line in lines if not line.startswith(("- 重复行数不包含", "- 质量分为启发式指标"))]
    lines.extend("- " + md_text(note) for note in result["agent"]["notes"])
    return "\n".join(lines) + "\n"


def render_html(result, markdown, goal=""):
    title = escape(result["title"])
    source, overview = result["source"], result["overview"]
    projection = source.get("quality_scope") == "selected_fields"
    metric_values = [
        ("分析行数", f"{overview['rows']:,}"), ("字段数量", str(overview["columns"])),
        ("缺失率", f"{overview['missing_pct']:.2f}%")]
    metric_values.append(("聚合图表", str(len(result["charts"]))) if projection else
                         ("质量评分 · 启发式", f"{overview['quality_score']} / 100"))
    metrics = "".join(f'<div class="metric"><small>{label}</small><strong>{value}</strong></div>' for label, value in metric_values)
    source_notes = "".join(f"<li>{escape(note)}</li>" for note in source["notes"])
    source_html = (f'<section class="panel"><h2>来源与分析范围</h2><dl><dt>数据文件</dt><dd>{escape(source["filename"])}</dd>'
                   f'<dt>数据性质</dt><dd>{"公开数据的聚合分析示例" if source.get("public_example") else "合成演示数据，不代表真实业务" if source["is_demo"] else "用户上传的数据集"}</dd>'
                   f'<dt>分析范围</dt><dd>{overview["rows"]:,} 行；{"已截取前 100,000 行，完整行数未知" if source["sampled"] else "完整读取"}</dd>'
                   f'<dt>分析目标</dt><dd>{escape(goal or "探索数据质量、分布与潜在关系。")}</dd>'
                   f'<dt>Agent 模式</dt><dd>{escape(result["agent"]["mode"])}'
                   f'{" · " + escape(result["agent"].get("model") or "") if result["agent"]["mode"] == "llm" else " · 可复算统计规则"}</dd></dl><ul>{source_notes}</ul></section>')
    source_html += deep_html(result.get("eda"))
    insights_html = "".join(f'<article class="insight"><h3>{escape(item["title"])}</h3><p>{escape(item["body"])}</p><div class="evidence">统计依据：{escape(item["evidence"])}</div></article>' for item in result["insights"])
    narrative_html = f'<section class="panel"><h2>Agent 目标分析</h2><p>{escape(result["agent"]["narrative"])}</p></section>' if result["agent"].get("narrative") else ""
    recommendations_html = "".join(f"<li>{escape(item)}</li>" for item in result["recommendations"])
    column_rows = "".join(f'<tr><td>{escape(c["name"])}</td><td>{escape(c["kind"])}</td><td>{c["unique"]:,}</td><td>{c["missing_pct"]:.2f}%</td><td>{report_value(c.get("mean"))}</td><td>{report_value(c.get("median"))}</td></tr>' for c in result["columns"])
    methods = ["所有统计均基于本次分析行；散点若抽样会在图注中标明。未自动清洗或删除原始记录。",
               "重复行数不包含首次出现；Pearson 相关至少需要 5 对完整值，疑似标识符已排除。相关不代表因果。",
               "质量评分 = 100 − 缺失单元格百分比×0.6 − 重复行比例×25 − 常量列比例×15，下限为 0。它不代表数据真实性或模型准确率。",
               "IQR 极端值边界为 Q1−1.5×IQR 与 Q3+1.5×IQR；提示不等同于错误数据。",
               "日期仅使用真实日期型或全部有效的明确年/月/日文本；带时区文本会统一到 UTC。"] + result["agent"]["notes"]
    if projection:
        methods = [note for note in methods if not note.startswith(("重复行数不包含", "质量评分 ="))]
        methods.append("本例只保留选定分析字段。同值记录不等于同一业务记录，不据此对原始数据作质量评级或去重。")
    methods_html = "".join(f"<li>{escape(item)}</li>" for item in methods)
    charts = []
    chart_cards = {}
    scripts = []
    for i, chart in enumerate(result["charts"]):
        element = f"chart-{i}"
        notes = "".join("<li>" + escape(note) + "</li>" for note in chart.get("sample_notes", []))
        chart_cards[chart["id"]] = f'<section class="chart"><h3>{escape(chart["title"])}</h3><p>{escape(chart["description"])}</p><ul>{notes}</ul><div class="chart-canvas" style="min-height:340px" id="{element}"></div></section>'
        # Never place untrusted dataset strings directly inside executable script context.
        encoded = json.dumps(chart["figure"], ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        scripts.append(f'<script type="application/json" data-chart="{element}" id="{element}-data">{encoded}</script>')
    sections = (result.get("eda") or {}).get("sections", [{"key":"all","label":"图表探索","description":"","chart_ids":list(chart_cards)}])
    chart_map = {chart["id"]:chart for chart in result["charts"]}
    navigation = " · ".join(f'<a href="#topic-{escape(section["key"],quote=True)}">{escape(section["label"])}</a>' for section in sections)
    charts.append('<div style="grid-column:1/-1"><p>' + navigation + '</p><p>图表按滚动位置加载，可离线使用。打印前请使用按钮并等待全部图表准备完成。</p><button id="prepare-print" type="button">准备全部图表并打印</button></div>')
    for section in sections:
        primary = [cid for cid in section["chart_ids"] if chart_map[cid].get("section", "all") == section["key"]]
        references = [cid for cid in section["chart_ids"] if cid not in primary]
        links = "".join(f'<li>{escape(chart_map[cid]["title"])}（已在对应主专题呈现，避免重复图）</li>' for cid in references)
        cards = "".join(chart_cards[cid] for cid in primary)
        if not cards and not references:
            cards = '<p>当前数据不适用于本专题，详细原因见覆盖说明。</p>'
        charts.append(f'<section style="grid-column:1/-1" id="topic-{escape(section["key"],quote=True)}"><h2>{escape(section["label"])}</h2><p>{escape(section["description"])}</p><ul>{links}</ul><div class="charts">{cards}</div></section>')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>{REPORT_STYLE}</style></head><body><main><div class="badge">INSIGHT STUDIO · 离线可用分析报告</div><h1>{title}</h1><p>{escape(result['summary'])}</p>{brief_html(result.get('brief'))}<div class="metrics">{metrics}</div>{source_html}<section class="panel"><h2>数据洞察</h2>{insights_html}</section>{narrative_html}<section class="panel"><h2>建议与下一步</h2><ol>{recommendations_html}</ol></section><h2>图表探索</h2><div class="charts">{''.join(charts)}</div><section class="panel"><h2>字段画像</h2><div class="table-wrap"><table><thead><tr><th>字段</th><th>类型</th><th>非缺失唯一值</th><th>缺失率</th><th>均值</th><th>中位数</th></tr></thead><tbody>{column_rows}</tbody></table></div></section><section class="panel"><h2>方法与局限</h2><ul>{methods_html}</ul></section><footer>Insight Studio · 数据探索报告 · 图表库与数据已内嵌，可离线查看</footer></main>
<script>{get_plotlyjs()}</script>{''.join(scripts)}
<script>{LAZY_RENDER_JS}</script></body></html>'''


def save_reports(directory: Path, result, goal):
    directory.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(result, goal)
    documents = {"result.json": json.dumps(result, ensure_ascii=False, allow_nan=False),
                 "report.md": markdown, "report.html": render_html(result, markdown, goal)}
    for name, content in documents.items():
        temporary = directory / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(directory / name)
