"""Local, evidence-linked explanations for readers who do not work with statistics.

This layer scans outcome relationships across all eligible fields, independently
of the bounded chart selection. It neither fits a model nor sends category labels
or rows to an external service.
"""
import math
import re
from contextvars import ContextVar

import pandas as pd


_CONTEXT = ContextVar("explanation_context", default={})

DOMAIN_LABELS = {
    "business": {"sales": "销售额", "quantity": "销量", "profit": "利润", "discount": "折扣", "category": "商品类别", "segment": "客户群体", "ship_mode": "配送方式", "total": "交易金额", "rating": "顾客评分", "product_line": "商品线", "unit_price": "单价"},
    "finance": {"age": "年龄", "limit_bal": "信用额度", "education": "教育程度编码", "marriage": "婚姻状态编码", "default_payment_next_month": "下月违约记录", "default_payment_next_month_": "下月违约记录", "default": "违约记录", "balance": "余额"},
    "health": {"age": "年龄", "time": "随访时长", "serum_creatinine": "血清肌酐", "ejection_fraction": "射血分数", "serum_sodium": "血清钠", "death_event": "随访期死亡记录", "diabetes": "糖尿病记录编码", "anaemia": "贫血记录编码", "high_blood_pressure": "高血压记录编码", "smoking": "吸烟记录编码", "platelets": "血小板计数", "sex": "性别编码"},
    "entertainment": {"type": "作品类型", "duration": "片长或季数原值", "release_year": "作品发行年", "rating": "分级标签", "listed_in": "题材标签", "country": "国家或地区标签", "vote_average": "观众评分", "vote_count": "评分人数", "budget": "制作预算", "revenue": "票房收入", "popularity": "平台热度指标"},
}


def field_definition(name):
    definitions = _CONTEXT.get().get("field_definitions", {})
    result = definitions.get(str(name), {}) if isinstance(definitions, dict) else {}
    return result if isinstance(result, dict) else {}


def category_label(name, value):
    values = field_definition(name).get("value_labels", {})
    if isinstance(values, dict):
        text = values.get(str(value))
        if text is None and isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and float(value).is_integer():
            text = values.get(str(int(value)))
        if isinstance(text, str) and text.strip():
            return text.strip()[:80]
    return str(value)[:80]


def excluded_reason(name):
    fields = _CONTEXT.get().get("exclude_fields", {})
    if isinstance(fields, dict) and name in fields:
        return str(fields[name])[:1000] or "来源说明将此字段排除出解释比较。"
    if isinstance(fields, list) and name in fields:
        return "来源说明将此字段排除出解释比较，可能在结果发生后记录，不能作为事前依据。"
    return None


LABELS = {
    "gpa_rank": "GPA排名", "gpa": "GPA", "gender": "性别", "student_id": "学生编号",
    "employment_ability_scale": "就业能力自评", "active_knowledge_acquisition_scale": "主动学习能力自评",
    "innovation_and_entrepreneurship_scale": "创新创业能力自评", "internship": "实习成绩",
    "graduation_project": "毕业设计成绩", "cet4": "英语四级指标", "cet6": "英语六级指标",
    "career_guidance_mean": "就业指导课程均分", "situation_policy_mean": "形势与政策课程均分",
    "advanced_mathematics_a1": "高等数学A1", "advanced_mathematics_a2": "高等数学A2",
    "linear_algebra": "线性代数", "probability_theory_and_mathematical_statistics": "概率论与数理统计",
    "complex_function": "复变函数", "university_physics_b1": "大学物理B1",
    "university_physics_laboratory": "大学物理实验", "discrete_mathematics": "离散数学",
    "principles_of_computer_organization": "计算机组成原理", "digital_circuits": "数字电路",
    "operating_systems": "操作系统", "computer_networks": "计算机网络",
    "microcontroller_principles_and_interfaces": "单片机原理与接口", "compiler_principles": "编译原理",
    "database_principles": "数据库原理", "embedded_systems": "嵌入式系统",
    "data_structures": "数据结构", "algorithm_analysis_and_design": "算法分析与设计",
    "software_engineering": "软件工程", "artificial_intelligence": "人工智能",
    "c_programming": "C语言程序设计", "java_programming": "Java程序设计",
    "web_front_end_ui": "Web前端设计", "college_english_i": "大学英语I", "college_english_ii": "大学英语II",
    "physical_education_scale": "体育能力自评", "moral_character_scale": "品德自评",
    "aesthetic_and_labor_education_scale": "美育与劳动教育自评",
    "fundamentals_of_circuit_theory": "电路原理", "basic_circuit_theory_laboratory": "电路原理实验",
    "literature_search": "文献检索", "scientific_paper_writing_and_research_innovation": "科研写作与创新",
    "foundation_of_innovation_and_entrepreneurship": "创新创业基础",
    "kas_entrepreneurship_practice_for_college_students": "大学生创业实践",
    "mental_health_education_for_college_students": "大学生心理健康教育",
    "military_skills_and_theory_for_college_students": "军事技能与理论",
    "introduction_to_the_basic_principles_of_marxism": "马克思主义基本原理",
    "outline_of_modern_chinese_history": "中国近现代史纲要",
    "introduction_to_mao_zedong_thought_and_the_theoretical_system_of_socialism_with_chinese_part_1": "毛泽东思想和中国特色社会主义理论体系概论（一）",
    "introduction_to_mao_zedong_thought_and_the_theoretical_system_of_socialism_with_chinese_characteristics_part_2": "毛泽东思想和中国特色社会主义理论体系概论（二）",
    "introduction_to_xi_jinping_s_thought_on_socialism_with_chinese_characteristics_for_a_new_era": "习近平新时代中国特色社会主义思想概论",
    "ideological_and_moral_cultivation_and_legal_basis": "思想道德修养与法律基础",
}


def normalized(name):
    return re.sub(r"[^\w]+", "_", str(name).lower()).strip("_")


def label(name):
    explicit = field_definition(name).get("label")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:120]
    key = normalized(name)
    contextual = DOMAIN_LABELS.get(_CONTEXT.get().get("domain"), {})
    if key in contextual:
        return contextual[key]
    if key in LABELS:
        return LABELS[key]
    for suffix, text in (("_lab", "实验"), ("_course_design", "课程设计")):
        if key.endswith(suffix) and key[:-len(suffix)] in LABELS:
            return LABELS[key[:-len(suffix)]] + text
    if key.startswith("physical_education_"):
        return "体育" + key.rsplit("_",1)[1].upper()
    match = re.fullmatch(r"scientific_paper_reading_and_research_innovation_(\d+)", key)
    if match:
        return "科研阅读与创新" + match[1]
    return str(name).replace("_", " ")


def is_rank(name):
    return normalized(name) in {"gpa_rank", "gpa_ranking", "绩点排名", "gpa排名", "成绩排名"}


def meaning(name):
    if excluded_reason(name):
        return "此字段已排除出解释比较：" + excluded_reason(name)
    explicit = field_definition(name).get("meaning")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:1000]
    key = normalized(name)
    if is_rank(name):
        return "这是名次，数值越小排名越靠前；不是GPA分数。课程成绩本身可能参与排名计算。"
    if key in {"employment_ability_scale", "就业能力自评", "就业能力量表"}:
        return "这是就业能力自评量表，不是实际就业率、薪资或是否拿到录用通知。"
    if key in {"cet4", "cet6", "cet_4", "cet_6"}:
        return "这是0/1编码指标；未提供编码说明时，不自动解释为考试通过或未通过。"
    if key == "internship":
        return "这是实习成绩，不是实习时长、实习次数或是否有实习经历。"
    if key.endswith("_scale"):
        return "这是量表分值；需核对题目、计分方式和采集来源，不能直接当作客观能力或行为结果。"
    return "按上传表中的原始口径比较；数值大小的业务含义需结合字段定义。"


def numeric_fields(df, target=None):
    # Explicitly named IDs and monotonic row counters never become evidence.
    from .analysis import is_identifier, IDENTIFIER_NAME
    return [name for name in df.select_dtypes(include=["number"]).columns
            if name not in _CONTEXT.get().get("categorical_fields", []) and not excluded_reason(name)
            and (not is_identifier(name, df[name]) or is_rank(name)
                or (name == target and not IDENTIFIER_NAME.search(name)))
            and df[name].notna().sum() >= 5 and df[name].nunique() > 1]


def _choose_focus(df, goal="", requested=None):
    if requested in df.columns:
        return requested, "user"
    if requested:
        return None, "none"  # An invalid explicit selection must not silently change the question.
    from .analysis import IDENTIFIER_NAME
    candidates = numeric_fields(df)
    named_categories = [c for c in df if not excluded_reason(c) and not IDENTIFIER_NAME.search(c) and df[c].notna().sum() >= 5
                        and 2 <= df[c].nunique() <= 12 and c not in candidates]
    intent = str(goal).lower()
    # Prefer a field literally named in the question before domain suggestions.
    matches = [c for c in candidates + named_categories if mention_position(c, goal, known_aliases=False) is not None]
    if matches:
        event = _CONTEXT.get().get("event", {})
        event_column = event.get("column") if isinstance(event, dict) else None
        if event_column in matches and event_definition(df, event_column):
            return event_column, "auto"
        return max(matches, key=lambda c: len(str(c))), "auto"
    employment = [c for c in candidates if normalized(c) in {"employment_ability_scale", "就业能力自评", "就业能力量表"}]
    if employment and any(word in intent for word in ("就业", "employ", "实习", "职业")):
        return employment[0], "auto"
    ranks = [c for c in candidates if is_rank(c)]
    if ranks:
        return ranks[0], "auto"
    for preferred in ("销售额", "revenue", "利润", "profit", "收入", "income", "gpa", "score", "成绩"):
        found = next((c for c in candidates if normalized(c) == preferred), None)
        if found:
            return found, "auto"
    return None, "none"


def choose_focus(df, goal="", requested=None, context=None):
    if context is None:
        return _choose_focus(df, goal, requested)
    token = _CONTEXT.set(context if isinstance(context, dict) else {})
    try:
        return _choose_focus(df, goal, requested)
    finally:
        _CONTEXT.reset(token)


def target_pairs(df, target, candidates):
    if target not in candidates:
        return []
    pairs = []
    for other in candidates:
        if other == target:
            continue
        values = df[[other, target]].dropna()
        if len(values) < 5 or values[other].nunique() < 2 or values[target].nunique() < 2:
            continue
        # Rank within the complete pair, not globally before missing-value removal.
        rho = float(values[other].rank().corr(values[target].rank()))
        if math.isfinite(rho):
            pairs.append({"field": other, "target": target, "rho": rho, "n": len(values)})
    return sorted(pairs, key=lambda p: (-abs(p["rho"]), str(p["field"])))


def mention_position(field, goal, known_aliases=True):
    """Match column names/known aliases without finding `a` inside `data`."""
    text = str(goal).lower()
    aliases = {"internship": ("实习",), "active_knowledge_acquisition_scale": ("主动学习",),
               "innovation_and_entrepreneurship_scale": ("创新", "创业"), "career_guidance_mean": ("就业指导",),
               "employment_ability_scale": ("就业能力",), "cet4": ("四级",), "cet6": ("六级",)}
    terms = (str(field).lower(), label(field).lower(), *(aliases.get(normalized(field), ()) if known_aliases else ()))
    positions = []
    for term in terms:
        # Chinese phrases have no word separators. ASCII field names do.
        pattern = re.escape(term)
        if re.fullmatch(r"[a-z0-9_\s-]+", term):
            pattern = r"(?<![a-z0-9_])" + pattern + r"(?![a-z0-9_])"
        match = re.search(pattern, text)
        if match:
            positions.append(match.start())
    return min(positions) if positions else None


def question_relevance(field, goal):
    text = str(goal).lower()
    explicit = mention_position(field, goal) is not None
    course = "课程" in text and not normalized(field).endswith("_scale") and not is_rank(field)
    return int(explicit), int(course)


def relationship_title(field, target, rho):
    """Translate rank signs in either position without calling a rank a score."""
    if is_rank(field):
        if is_rank(target):
            direction = "靠前" if rho > 0 else "靠后"
            return f"{label(field)}更靠前的记录，{label(target)}通常更{direction}"
        direction = "较高" if rho < 0 else "较低"
        return f"{label(field)}更靠前的记录，{label(target)}通常{direction}"
    if is_rank(target):
        direction = "靠前" if rho < 0 else "靠后"
        return f"{label(field)}较高的记录，{label(target)}通常更{direction}"
    direction = "同向变化" if rho > 0 else "反向变化"
    return f"{label(field)}与{label(target)}在样本中{direction}"


def relationship_boundary(field, target):
    notes = ["这是样本内的探索性描述，未做显著性检验、混杂控制或独立预测验证；不能据此认定因果。"]
    if is_rank(field) or is_rank(target):
        notes.append("名次越小越靠前；课程成绩或量表可能与排名共享评分来源，不能解释为独立影响。")
    if normalized(field).endswith("_scale") and normalized(target).endswith("_scale"):
        notes.append("两个量表可能共享作答者、题目或计分方法，当前表不能区分共同测量来源与真实能力关系。")
    if normalized(field) == "employment_ability_scale" or normalized(target) == "employment_ability_scale":
        notes.append("就业能力自评不能替代实际就业率、录用或薪资。")
    if normalized(field) == "internship" or normalized(target) == "internship":
        notes.append("实习列记录的是成绩，不能解释为增加实习时长的效果。")
    notes.append(domain_boundary())
    return "".join(notes)


def domain_boundary():
    return {
        "business": "样本收入或订单结构不能直接推出促销效果、利润或未来销量。",
        "finance": "历史样本比例不等于未来损失概率；不构成投资建议，也不能据此审批或拒绝个人信贷。",
        "health": "这是已收集人群的记录比较，不是个体诊断、治疗建议或面向一般人群的患病／死亡概率。随访时间和入组方式可能改变比例。",
        "entertainment": "平台作品目录、发行年份或分级标签不能替代观看量、观众偏好或未来票房。",
    }.get(_CONTEXT.get().get("domain"), "")


def category_field(df, field, kinds=None):
    """Numeric codes require explicit metadata, except two-value indicators.

    Two-value indicators are compared as raw groups; their values acquire no
    business meaning until the source provides that meaning.
    """
    explicit = _CONTEXT.get().get("categorical_fields", [])
    return (field in explicit or pd.api.types.is_bool_dtype(df[field])
            or not pd.api.types.is_numeric_dtype(df[field]) or df[field].nunique() == 2)


def event_definition(df, target):
    raw = _CONTEXT.get().get("event")
    if not isinstance(raw, dict) or raw.get("column") != target or "value" not in raw:
        return None
    values = df[target].dropna()
    if values.nunique() != 2 or not values.eq(raw["value"]).any():
        return None
    text = raw.get("label")
    if not isinstance(text, str) or not text.strip():
        return None
    return {"value": raw["value"], "label": text.strip()[:120],
            "meaning": str(raw.get("meaning", ""))[:1000]}


def group_summary(df, field, target, event=None, categorical_target=False):
    """Complete-case descriptive groups; never a significance test or model."""
    from .analysis import is_identifier
    values = df[[field, target]].dropna()
    base = {"field": field, "target": target, "n": len(values), "missing": len(df)-len(values),
            "groups": [], "omitted_groups": 0, "omitted_rows": 0, "binned": False}
    if excluded_reason(field):
        return {**base, "reason": "此项未参与解释比较：" + excluded_reason(field), "excluded": True}
    if is_identifier(field, df[field]) and not is_rank(field):
        return {**base, "reason": "字段疑似编号，不能作为分组解释依据。"}
    if values.empty or values[field].nunique() < 2:
        return {**base, "reason": "成对有效记录不足或分组字段缺少不同取值。"}
    if category_field(df, field):
        if values[field].nunique() > 12:
            return {**base, "reason": "类别超过12组的展示上限；请提出范围更明确的问题。"}
        keys = values[field]
    elif pd.api.types.is_numeric_dtype(values[field]):
        # qcut retains exact unrounded boundaries internally. Displayed labels
        # are not used to recalculate membership or include an extra row.
        keys, edges = pd.qcut(values[field], q=4, duplicates="drop", retbins=True)
        if len(edges) < 3:
            return {**base, "reason": "数值分布过于集中，无法形成至少两个分位区间。"}
        base.update(binned=True, bin_edges=[float(v) for v in edges])
    else:
        return {**base, "reason": "字段类型不适合当前分组比较。"}
    raw_category = df[target].dropna().value_counts().index[0] if categorical_target and not event else None
    for key, grouped in values.groupby(keys, observed=True, sort=base["binned"]):
        group = grouped[target]
        if base["binned"]:
            position = keys.cat.categories.get_loc(key)
            lower, upper = edges[position], edges[position+1]
            display_label = (f"{lower:.12g} 至{upper:.12g}（含两端）" if position == 0
                             else f"大于{lower:.12g} 至{upper:.12g}（含上界）")
        else:
            display_label = category_label(field,key)
        row = {"label": display_label, "group_id": f"B{len(base['groups'])+1:02d}",
               "n": len(group), "supported": len(group) >= 20}
        if event or categorical_target:
            count = int(group.eq(event["value"] if event else raw_category).sum())
            row.update(events=count, rate_pct=count/len(group)*100)
        else:
            row.update(mean=float(group.mean()), median=float(group.median()))
        base["groups"].append(row)
        if not row["supported"]:
            base["omitted_groups"] += 1
            base["omitted_rows"] += row["n"]
    if categorical_target and not event:
        base["raw_category"] = str(raw_category)[:80]
    return base


def group_answer(comparison, target, event=None, categorical_target=False):
    field, n = comparison["field"], comparison["n"]
    supported = [g for g in comparison["groups"] if g["supported"]]
    method = "event_rate" if event else "category_share" if categorical_target else "group_summary"
    if comparison.get("excluded"):
        method = "excluded"
    evidence = f"成对有效 n={n}；排除缺失任意一项的{comparison['missing']}条记录。"
    evidence += f"每个可比较组至少20条；支持不足的{comparison['omitted_groups']}组共{comparison['omitted_rows']}条仍保留计数。"
    if comparison.get("binned"):
        evidence += "按成对有效记录的四分位切分，重复分界合并；首段含最小值，其余区间左开右闭。"
        evidence += "实际分界=" + ", ".join(repr(v) for v in comparison["bin_edges"]) + "；区间标签的数字按最多12位有效数字显示。"
    caveat = "分组比较是样本描述；未做显著性检验、混杂控制或独立预测验证，不能认定因果。" + domain_boundary()
    if len(supported) < 2:
        answer = f"暂不足以比较不同{label(field)}组的{label(target)}。"
        explanation = comparison.get("reason", "至少需要两个各有20条成对有效记录的组；门槛只控制展示，不保证结果可靠。")
        if comparison.get("excluded"):
            answer = f"{label(field)}已按来源排除，不作为{label(target)}的事前解释或预测依据。"
        status = "insufficient"
        difference = None
    else:
        metric = "rate_pct" if event or categorical_target else "mean"
        ordered = sorted(supported, key=lambda g:(g[metric], g["label"]))
        low, high = ordered[0], ordered[-1]
        difference = float(high[metric]-low[metric])
        if event or categorical_target:
            outcome = event["label"] if event else f"原始类别「{comparison['raw_category']}」"
            answer = (f"本样本可比较的组中，「{high['label']}」的{outcome}比例为{high['rate_pct']:.1f}%"
                      f"（{high['events']}/{high['n']}），「{low['label']}」为{low['rate_pct']:.1f}%"
                      f"（{low['events']}/{low['n']}），绝对相差{difference:.1f}个百分点。")
            explanation = (f"这里每100条已观察记录中大约有多少条{outcome}，分母是各组同时有值的记录，"
                           "不是相对风险，也不是改变组别后的效果。")
            if not event:
                explanation += "未提供事件编码说明，因此只比较原始类别构成，不把1自动解释为发生、通过、违约或死亡。"
            evidence += "各组计数=" + "；".join(f"「{g['label']}」{g['events']}/{g['n']}" for g in comparison["groups"]) + "。"
        else:
            answer = (f"本样本可比较的组中，「{high['label']}」的{label(target)}均值为{high['mean']:.3g}，"
                      f"「{low['label']}」为{low['mean']:.3g}，相差{difference:.3g}。")
            explanation = (f"两组中位数分别为{high['median']:.3g}和{low['median']:.3g}；"
                           "均值容易受少数大值影响，应同时看中位数及各组规模，不能将组间差异归因于类别本身。")
            evidence += "各组有效记录=" + "；".join(f"「{g['label']}」n={g['n']}" for g in comparison["groups"]) + "。"
            if is_rank(target):
                caveat += "目标是名次，数值越小排名越靠前；均值较大不能称为表现更好。"
        explanation += meaning(field)
        status = "supported"  # Only the group support rule; not confidence.
    item = {"id": "", "question": f"{label(field)}与{label(target)}有什么关系？", "answer": answer,
            "status": status, "explanation": explanation, "evidence": evidence, "caveat": caveat,
            "next_step": f"核对「{label(field)}」各组的采集范围、记录时间与其他构成，再用独立记录复核。",
            "fields": [field,target], "n": n, "rho": None, "finding_ids": [], "method": method,
            "groups": comparison["groups"]}
    item["status_label"] = ("已按来源排除" if method == "excluded" else
                            "样本分组比较" if status == "supported" else "分组支持不足")
    if event or categorical_target:
        item["difference_pp"] = difference
    return item


def group_headline(item, target, event=None, raw_category=None):
    field = item["fields"][0]
    if item["status"] != "supported":
        return f"关于{label(field)}的分组记录暂不足以比较"
    if item.get("method") in {"event_rate", "category_share"}:
        outcome = event["label"] if event else f"原始类别「{raw_category}」" if raw_category is not None else label(target)
        return f"按{label(field)}分组，{outcome}比例相差{item['difference_pp']:.1f}个百分点"
    supported = [group for group in item["groups"] if group["supported"]]
    means = [group["mean"] for group in supported]
    different = not math.isclose(max(means), min(means), rel_tol=1e-9, abs_tol=1e-12)
    return f"按{label(field)}分组，{label(target)}均值" + ("有所不同" if different else "相近")


def answer_named_relationships(df, target, candidates, pairs, goal, findings):
    """Answer requested comparisons even when they do not pass display filters.

    Status is a descriptive display rule, never confidence or significance.
    No row values or category labels are added to the model evidence here.
    """
    from .analysis import IDENTIFIER_NAME
    named = [field for field in df if field != target and mention_position(field, goal) is not None]
    named.sort(key=lambda field: (mention_position(field, goal), str(field)))
    by_field = {pair["field"]: pair for pair in pairs}
    answers = []
    for field in named[:12]:
        if excluded_reason(field):
            item = group_answer(group_summary(df, field, target), target)
            item["id"] = f"question-{len(answers)+1}"
            answers.append(item)
            continue
        complete = df[[field, target]].dropna()
        n = len(complete)
        pair = by_field.get(field)
        rho = pair["rho"] if pair else None
        evidence = f"成对有效 n={n}/{len(df)}；缺失任意一项的记录不参与此项比较。"
        if rho is not None:
            evidence += f"Spearman ρ={rho:.4f}。"
        caveat = relationship_boundary(field, target)
        status_label = None
        categorical = (not pd.api.types.is_numeric_dtype(df[field]) or pd.api.types.is_bool_dtype(df[field]))
        if (categorical or field in _CONTEXT.get().get("categorical_fields", [])) and not IDENTIFIER_NAME.search(field):
            item = group_answer(group_summary(df, field, target), target)
            item["id"] = f"question-{len(answers)+1}"
            item["finding_ids"] = [finding["id"] for finding in findings
                                   if set([field,target]).issubset(finding["fields"])]
            answers.append(item)
            continue
        elif pair and n >= 20 and abs(rho) >= .2:
            status = "supported"
            answer = relationship_title(field, target, rho) + "。"
            strength = "较强" if abs(rho) >= .7 else "中等" if abs(rho) >= .4 else "较弱"
            explanation = (f"在这份样本中，共同变化程度为{strength}（排序相关{rho:.2f}）。"
                           "这有助于提出复核问题，不能判断改变其中一项会带来什么效果，也不表示统计显著或结论可靠。")
            if abs(rho) >= .95 and (normalized(field).endswith("_scale") or normalized(target).endswith("_scale")):
                explanation = ("两列排序高度重合，应先核对是否独立采集、是否共享题目或评分规则，再讨论能力关系。"
                               "这既不能证明量表有效，也不能据此认定数据造假。")
        elif pair and n >= 20:
            status = "partial"
            answer = f"当前样本未显示{label(field)}与{label(target)}之间清晰的单调关系。"
            explanation = "排序关联的绝对值低于0.20的展示口径。这不等于二者无关；分组差异、非线性关系、测量误差或缺失记录仍可能影响判断。"
        else:
            status = "insufficient"
            answer = f"暂不足以判断{label(field)}与{label(target)}的关系。"
            if n < 20:
                explanation = f"仅有{n}条成对有效记录，未达到20条的解释展示口径；样本量门槛本身不保证结论可靠。"
            elif field not in candidates:
                explanation = "此字段未成为可比较的数值指标：可能是文本／类别、常量或疑似编号。需要先核对字段类型和口径，不能强行计算排序关系。"
            else:
                explanation = "成对记录中的至少一列缺少足够变化，无法形成可解释的排序关系。"
        next_step = (f"先核对「{label(field)}」和「{label(target)}」的定义、采集时间及评分来源；"
                     + ("补充成对记录后再比较。" if status == "insufficient" else "用独立记录复核这项观察。"))
        if status_label:
            next_step = f"在分组统计中核对「{label(field)}」各类别的记录数和「{label(target)}」分布，再决定是否需要组间比较。"
        answers.append({"id": f"question-{len(answers)+1}",
                        "question": f"{label(field)}与{label(target)}有什么关系？",
                        "answer": answer, "status": status, "explanation": explanation,
                        "evidence": evidence, "caveat": caveat, "next_step": next_step,
                        "fields": [field, target], "n": n, "rho": rho,
                        "method": "spearman",
                        "finding_ids": [finding["id"] for finding in findings
                                        if set([field, target]).issubset(finding["fields"])]})
        if status_label:
            answers[-1]["status_label"] = status_label
    return answers, len(named)


def question_pairs(pairs, goal):
    """Respect the actual question before filling remaining slots by strength."""
    def relevant(pair):
        return (*question_relevance(pair["field"], goal), abs(pair["rho"]))
    return sorted(pairs, key=relevant, reverse=True)


def select_numeric_fields(df, eligible, target, goal, limit=10):
    if target not in eligible:
        return eligible[:limit]
    # Retain outcome-related fields even if they occur after the first ten columns.
    ranked = question_pairs(target_pairs(df, target, eligible), goal)
    ordered = [target] + [p["field"] for p in ranked]
    return list(dict.fromkeys(ordered + eligible))[:limit]


def _schema_description(df, source):
    from .analysis import detect_types, IDENTIFIER_NAME
    kinds = detect_types(df)
    categories = _CONTEXT.get().get("categorical_fields", [])
    if isinstance(categories, list):
        kinds.update({field: "categorical" for field in categories if field in df.columns})
    focus, _ = choose_focus(df)
    columns = []
    for c in df:
        selectable = (not excluded_reason(c) and not IDENTIFIER_NAME.search(c) and df[c].notna().sum() >= 5 and df[c].nunique() > 1
                      and (kinds[c] == "numeric" or (kinds[c] in {"categorical", "boolean"} and df[c].nunique() <= 12)))
        reason = ("" if selectable else excluded_reason(c) or "关注指标需为非编号的数值列或不超过12类的类别列，至少5个有效值且包含不同取值；当前列不满足。")
        columns.append({"name": c, "label": label(c), "kind": kinds[c], "meaning": meaning(c),
                        "suggested": c == focus, "selectable": bool(selectable), "selection_note": reason})
    suggestions = []
    selectable_fields = {c["name"] for c in columns if c["selectable"]}
    rank = next((c for c in df if c in selectable_fields and is_rank(c)), None)
    employment = next((c for c in df if c in selectable_fields and normalized(c) == "employment_ability_scale"), None)
    if rank:
        suggestions.append({"label": "理解学业表现", "target": rank,
                            "goal": "哪些课程成绩与GPA排名更相关？这些关系能说明什么，不能说明什么？"})
    if employment:
        suggestions.append({"label": "理解就业能力自评", "target": employment,
                            "goal": "就业能力自评与实习成绩、主动学习及课程成绩有什么关系？请解释实际含义。"})
    if not suggestions:
        suggestions.append({"label": "先看主要发现", "target": focus,
                            "goal": "请用日常语言说明这份数据最值得关注的发现、支持数字和下一步可以了解的问题。"})
    return {"columns": columns, "suggested_target": focus, "questions": suggestions,
            "analyzed_rows": len(df), "notes": source.get("notes", [])}


def _build_numeric_brief(df, kinds, target, origin, goal, charts, source):
    candidates = numeric_fields(df, target)
    selected_focus = target if target in df.columns else None
    if target not in candidates:
        target = None
    pairs = target_pairs(df, target, candidates)
    findings = []

    def add(kind, title, takeaway, explanation, evidence, fields, caveat, n, next_step):
        ids = [c["id"] for c in charts if set(fields).issubset(set(c.get("fields", [])))
               and (len(fields) < 2 or c["type"] in {"scatter", "grouped_box", "grouped_bar", "target_binned"})][:2]
        findings.append({"id": f"finding-{len(findings)+1}", "kind": kind, "title": title,
                         "takeaway": takeaway, "explanation": explanation, "evidence": evidence,
                         "fields": fields, "chart_ids": ids, "caveat": caveat, "n": int(n), "next_step": next_step})

    focus = {"column": selected_focus, "label": label(selected_focus) if selected_focus else None, "origin": origin,
             "lower_is_better": is_rank(selected_focus) if selected_focus else False,
             "meaning": meaning(selected_focus) if selected_focus else "", "analyzable": target is not None}
    caveats = ["结论只描述本次读取的记录；共同变化不等于一个因素造成另一个结果。"]
    question_answers, questions_detected = [], 0
    if target:
        values = df[target].dropna()
        q1, median, q3 = [float(v) for v in values.quantile([.25, .5, .75])]
        if is_rank(target):
            takeaway = f"本表共有{len(values):,}条有效排名记录，名次越小越靠前。"
            explanation = "后面的课程关系会按‘排名靠前／靠后’解释。课程成绩可能是排名的组成部分，这些关系可帮助了解成绩结构，不能证明提升某门课就会改善排名。"
        else:
            takeaway = f"{label(target)}的中位数为{median:.3g}，中间一半记录在{q1:.3g}至{q3:.3g}之间。"
            explanation = meaning(target)
        add("overview", f"先看懂{label(target)}", takeaway, explanation,
            f"有效记录 n={len(values)}；中位数={median:.6g}；Q1={q1:.6g}；Q3={q3:.6g}。",
            [target], "分位区间描述样本分布，不是合格线或理想标准。", len(values), "先核对这个指标的定义，再阅读关联发现。")
        # Describe an actual cross-section, rather than implying that a single
        # correlation explains every record. Quantiles are computed within pairs.
        if not is_rank(target):
            for pair in question_pairs(pairs, goal):
                field = pair["field"]
                if not question_relevance(field, goal)[0] or is_rank(field):
                    continue
                complete = df[[field,target]].dropna()
                if len(complete) < 40 or complete[field].nunique() < 4 or complete[target].nunique() < 4:
                    continue
                high_cut = float(complete[field].quantile(.75))
                low_cut = float(complete[target].quantile(.25))
                high = complete[field].ge(high_cut)
                joint = high & complete[target].le(low_cut)
                denominator, count = int(high.sum()), int(joint.sum())
                if denominator >= 10 and count >= 5:
                    add("contrast", f"{label(field)}较高，也可能伴随较低的{label(target)}",
                        f"{label(field)}不低于{high_cut:.3g}的{denominator}条记录中，有{count}条的{label(target)}不高于{low_cut:.3g}，占{count/denominator*100:.1f}%。",
                        "两项记录反映的方面并不完全相同。可以先了解这部分记录背后的经历与评价口径，避免用其中一项代替另一项。",
                        f"成对有效 n={len(complete)}；分界分别采用该配对子样本的Q3和Q1，包含边界值；交叉计数={count}/{denominator}。",
                        [field,target], "‘较高／较低’仅指本样本的分位划分，不是合格标准，也不代表个人能力诊断。", len(complete),
                        f"了解这{count}条「{label(field)}较高、{label(target)}较低」记录背后的经历和评价口径。")
                    break
        aligned = [p for p in pairs if p["n"] >= 20 and abs(p["rho"]) >= .95
                   and (normalized(p["field"]).endswith("_scale") or normalized(target).endswith("_scale"))]
        if aligned:
            p = aligned[0]
            add("measurement", "部分量表与目标排序高度对应，评分来源值得先核对",
                f"「{label(p['field'])}」与「{label(target)}」的排序关联绝对值达到{abs(p['rho']):.2f}，两列在本表中提供的信息高度重合。",
                "可能是独立测量的结果，也可能与评分或数据整理方式有关；仅凭这张表无法区分。先核对原始问卷和评分规则，再解释真实能力差异。",
                f"Spearman ρ={p['rho']:.4f}；成对有效 n={p['n']}。", [p["field"],target],
                "高度同步不能证明量表有效，也不能据此认定数据造假。", p["n"], "核对量表是否独立采集，以及是否使用了排名或课程成绩打分。")
        supported = question_pairs([p for p in pairs if p["n"] >= 20 and abs(p["rho"]) >= .2], goal)
        for pair in supported[:3]:
            other, rho = pair["field"], pair["rho"]
            title = relationship_title(other, target, rho)
            strength = "较强" if abs(rho) >= .7 else "中等" if abs(rho) >= .4 else "较弱"
            add("relationship", title, f"在{pair['n']:,}条同时有值的记录中，两项排序呈{strength}的共同变化。",
                ("可先结合这项记录理解成绩差异；课程或量表与排名可能共享计算来源。" if is_rank(target)
                 else "这表示两项记录在样本中往往一起变化，可作为访谈或复核的切入点。") +
                ("就业能力自评反映主观评价，不能替代实际就业结果。" if "就业能力自评" == label(target) else ""),
                f"Spearman ρ={rho:.4f}；成对有效 n={pair['n']}；扫描{len(pairs)}组目标关系，先按问题相关性、再参考关联程度筛选。",
                [other, target], relationship_boundary(other, target), pair["n"],
                f"结合「{label(other)}」的记录口径，访谈不同表现的学生。" if is_rank(target) else f"核对「{label(other)}」的测量方式，并在独立样本中复核这组关系。")
        if not supported:
            add("insufficient", "暂未发现足够清晰的目标关联", "当前数值关系没有同时满足至少20对记录和排序关联绝对值0.20的展示门槛。",
                "这不代表没有关系；样本不足、缺失或非单调关系都可能影响结果。继续补充记录或提出更具体的问题更有帮助。",
                f"扫描{len(candidates)}个数值候选，计算{len(pairs)}组目标关系；未进行显著性检验。",
                [target], "展示门槛是解释筛选规则，不是统计显著性判断。", len(values), "补充记录或检查有业务含义的分组。")
        # One supported categorical contrast, with explicit local labels and scope.
        contrasts = []
        for category in df:
            if excluded_reason(category) or kinds[category] not in {"categorical", "boolean"} or category == target:
                continue
            unique = df[category].nunique()
            if not 2 <= unique <= 8:
                continue
            groups = [(str(k)[:80], v[target].dropna()) for k, v in df.groupby(category, observed=True)]
            kept = [(k, v) for k, v in groups if len(v) >= 20]
            if len(kept) < 2:
                continue
            high, low = max(kept, key=lambda g:g[1].mean()), min(kept, key=lambda g:g[1].mean())
            gap = float(high[1].mean() - low[1].mean())
            scale = float(values.std())
            if math.isfinite(scale) and scale > 0 and gap / scale >= .2:
                contrasts.append((gap / scale, category, high, low, len(groups)-len(kept)))
        if contrasts:
            _, category, high, low, omitted = max(contrasts, key=lambda c:c[0])
            add("group", f"{label(category)}的所选组之间，{label(target)}均值有所不同",
                f"「{high[0]}」组均值{high[1].mean():.3g}，「{low[0]}」组均值{low[1].mean():.3g}，相差{high[1].mean()-low[1].mean():.3g}。",
                "这是按样本标签分组后的描述，可能与课程、经历或其他组成差异有关；不能归因于组别本身。",
                f"两组有效 n={len(high[1])}/{len(low[1])}；每个保留组至少20条记录；另省略{omitted}个小组。",
                [category, target], "未控制混杂因素、未做显著性检验；不据此对个人作决策。", len(high[1])+len(low[1]), "先检查各组的课程和经历构成是否相近。")
        headline = next((f["title"] for f in findings if f["kind"] == "relationship"), findings[0]["title"])
        answer = headline + "。" + ("这里比较的是就业能力自评，不能解释为真实就业结果。" if label(target) == "就业能力自评" else meaning(target))
        requested_pairs = [p for p in supported if question_relevance(p["field"], goal)[0]]
        if len(requested_pairs) >= 2:
            high, low = max(requested_pairs, key=lambda p:abs(p["rho"])), min(requested_pairs, key=lambda p:abs(p["rho"]))
            if abs(high["rho"]) - abs(low["rho"]) >= .15:
                headline = f"相比{label(low['field'])}，{label(high['field'])}与{label(target)}的同步变化更明显"
                answer = (f"在当前样本中，两组排序关联的绝对值分别为{abs(high['rho']):.2f}和{abs(low['rho']):.2f}。"
                          "这有助于区分不同记录提供的信息，不能当作干预效果或预测能力的比较。" + meaning(target))
        caveats.append(meaning(target))
        question_answers, questions_detected = answer_named_relationships(df, target, candidates, pairs, goal, findings[:5])
        if question_answers:
            # The question's weak or unavailable relationships must not be
            # displaced by a stronger, unrelated relationship elsewhere.
            first = question_answers[0]
            headline = first["answer"].rstrip("。")
            if first.get("method") == "group_summary" and first["status"] == "supported":
                headline = group_headline(first, target)
            answer = "".join(item["answer"] for item in question_answers[:3]) + meaning(target)
            first_two = question_answers[:2]
            if len(first_two) == 2 and all(item["status"] == "supported" and item.get("method") == "spearman" for item in first_two):
                high, low = max(first_two, key=lambda item: abs(item["rho"])), min(first_two, key=lambda item: abs(item["rho"]))
                if abs(high["rho"]) - abs(low["rho"]) >= .15:
                    headline = f"相比{label(low['fields'][0])}，{label(high['fields'][0])}与{label(target)}的同步变化更明显"
            if len(question_answers) > 3:
                answer += f"其余{len(question_answers)-3}项问题见逐项回答。"
        elif aligned:
            headline = "先核对量表与目标的评分来源，再解读其他关系"
            measurement = next(f for f in findings if f["kind"] == "measurement")
            relationship = next((f for f in findings if f["kind"] == "relationship"), None)
            answer = measurement["takeaway"] + (relationship["title"] + "。" if relationship else "") + meaning(target)
    elif selected_focus:
        values = df[selected_focus].dropna()
        headline = f"暂不足以解释{label(selected_focus)}的关系"
        answer = f"你选择的「{label(selected_focus)}」有{len(values)}个有效值、{values.nunique()}种取值，当前不能形成可核对的数值关系。"
        explanation = "关注指标需是非编号的数值列，至少5个有效值且包含不同取值；不会改用其他指标替你回答。"
        evidence_text = f"全表 n={len(df)}；目标非缺失 n={len(values)}；不同取值={values.nunique()}。"
        add("insufficient", headline, answer, explanation, evidence_text, [selected_focus],
            meaning(selected_focus), len(values), "核对指标类型并补充有变化的有效记录，或重新选择关注指标。")
        question_answers = [{"id": "question-1", "question": f"目前能解释{label(selected_focus)}吗？",
                             "answer": answer, "status": "insufficient", "explanation": explanation,
                             "evidence": evidence_text, "caveat": meaning(selected_focus),
                             "next_step": findings[0]["next_step"], "fields": [selected_focus],
                             "n": len(values), "rho": None, "finding_ids": [findings[0]["id"]]}]
        questions_detected = 1
        caveats.append(meaning(selected_focus))
    else:
        # A categorical or text-only table still gets usable, non-invented findings.
        for field in df:
            if kinds[field] not in {"categorical", "boolean"} or not 1 < df[field].nunique() <= 12:
                continue
            counts = df[field].value_counts()
            n = int(counts.sum())
            top = str(counts.index[0])[:80]
            add("composition", f"{label(field)}中「{top}」占比最高",
                f"占该字段有效记录的{counts.iloc[0]/n*100:.1f}%（{int(counts.iloc[0])}/{n}）。",
                "先了解样本主要由哪些类别组成，再决定是否需要分别比较。", f"分母为{label(field)}非缺失记录 n={n}；类别数={len(counts)}。",
                [field], "样本构成不代表总体占比。", n, "确认当前样本是否覆盖你关心的其他群体。")
            if len(findings) >= 3:
                break
        headline = findings[0]["title"] if findings else "请先选择你想解释的指标"
        answer = "已整理本表的可观察事实。选择关注指标后，可以进一步回答哪些记录与它一起变化。"
        if not findings:
            add("insufficient", headline, "现有字段尚不足以形成有意义的结果比较。", "可以先查看字段含义与记录范围，再补充有变化的指标或类别。",
                f"本次读取{len(df)}行、{len(df.columns)}列。", [], "不会从编号、常量或纯文本中编造业务结论。", len(df), "补充你想了解的指标，并检查字段口径。")
    if source.get("sampled"):
        caveats.append(f"这里只读取文件前{len(df):,}行，不能代表完整文件或随机样本。")
    elif source.get("is_demo"):
        caveats.append("这是一份合成演示数据，不能代表真实业务。")
    if questions_detected > len(question_answers):
        caveats.append(f"识别到{questions_detected}项点名比较，本次仅逐项回答前{len(question_answers)}项，"
                       f"其余{questions_detected-len(question_answers)}项尚未回答；请拆分问题继续分析。")
    next_questions = list(dict.fromkeys([item["next_step"] for item in question_answers]
                                      + [f["next_step"] for f in findings if f["kind"] != "overview"]))[:3]
    brief = {"version": 1, "headline": headline, "answer": answer, "goal": goal, "focus": focus,
             "findings": findings[:5], "question_answers": question_answers,
             "next_questions": next_questions, "caveats": caveats,
             "coverage": {"analyzed_rows": len(df), "numeric_fields_scanned": len(candidates), "relationships_evaluated": len(pairs),
                          "questions_detected": questions_detected, "questions_answered": len(question_answers),
                          "questions_omitted": max(0, questions_detected-len(question_answers))}}
    # Only field names and numeric aggregates are eligible for model input.
    evidence = {"focus": focus, "target_relationships": question_pairs(pairs, goal)[:8],
                "question_answers": [model_question(item)
                                     for item in question_answers], "coverage": brief["coverage"]}
    return brief, evidence


def model_question(item):
    """Category values remain local; send bounded numeric aggregates + aliases."""
    result = {key: item[key] for key in ("fields", "status", "n", "rho", "caveat", "method") if key in item}
    if "groups" in item:
        result["groups"] = [{"group": group.get("group_id", f"B{index:02d}"), **{k:v for k,v in group.items() if k != "label"}}
                            for index, group in enumerate(item["groups"][:12], 1)]
    if "difference_pp" in item:
        result["difference_pp"] = item["difference_pp"]
    return result


def _build_category_brief(df, kinds, target, origin, goal, charts, source):
    from .analysis import is_identifier
    event = event_definition(df, target)
    clean = df[target].dropna()
    counts = clean.value_counts()
    target_label = label(target)
    caution = "所有比例的分母是已观察的有效记录；不是因果结论、未来预测或统计显著性。" + domain_boundary()
    if event:
        count = int(clean.eq(event["value"]).sum())
        takeaway = f"{len(clean):,}条有效记录中，{event['label']}有{count:,}条，占{count/len(clean)*100:.1f}%。"
        explanation = event["meaning"] or meaning(target)
        overview_evidence = f"事件明确定义为{target}={event['value']}；分子={count}；目标有效分母={len(clean)}；目标缺失={len(df)-len(clean)}。"
    else:
        takeaway = (f"{target_label}有{len(counts)}种原始取值；「{str(counts.index[0])[:80]}」有"
                    f"{int(counts.iloc[0]):,}/{len(clean):,}条，占{counts.iloc[0]/len(clean)*100:.1f}%。")
        explanation = "未提供明确事件编码，只描述表中原始类别；不会把1自动解释为发生、通过、违约或死亡。" + meaning(target)
        overview_evidence = f"目标有效分母={len(clean)}；目标缺失={len(df)-len(clean)}；不同取值={len(counts)}。"
        if _CONTEXT.get().get("event"):
            explanation += "来源中的事件说明未通过实际列值核对，本次未启用该事件含义。"
    findings = [{"id": "finding-1", "kind": "overview", "title": f"先看懂{target_label}", "takeaway": takeaway,
                 "explanation": explanation, "evidence": overview_evidence, "fields": [target],
                 "chart_ids": [c["id"] for c in charts if target in c.get("fields", [])][:2],
                 "caveat": caution, "n": len(clean), "next_step": "先核对目标取值的定义、记录范围和采集时间。"}]
    eligible = [field for field in df if field != target and kinds[field] != "datetime"
                and not excluded_reason(field) and not is_identifier(field, df[field]) and df[field].nunique() > 1]
    comparisons = {field: group_summary(df, field, target, event, categorical_target=True) for field in eligible}
    answers = {field: group_answer(comparison, target, event, categorical_target=True)
               for field, comparison in comparisons.items()}
    named = [field for field in df if field != target and mention_position(field, goal) is not None]
    named.sort(key=lambda field: (mention_position(field, goal), str(field)))
    for field in named[:12]:
        if field not in answers:
            answers[field] = group_answer(group_summary(df, field, target, event, categorical_target=True),
                                          target, event, categorical_target=True)
    ordering = sorted(eligible, key=lambda field: (field in named, answers[field]["status"] == "supported",
                                                  answers[field].get("difference_pp") or 0), reverse=True)
    for field in ordering[:4]:
        item = answers[field]
        findings.append({"id": f"finding-{len(findings)+1}", "kind": "group" if item["status"] == "supported" else "insufficient",
                         "title": f"按{label(field)}比较{event['label'] if event else target_label}", "takeaway": item["answer"],
                         "explanation": item["explanation"], "evidence": item["evidence"], "fields": [field,target],
                         "chart_ids": [c["id"] for c in charts if set([field,target]).issubset(c.get("fields", []))][:2],
                         "caveat": item["caveat"], "n": item["n"], "next_step": item["next_step"],
                         "groups": item["groups"], "method": item["method"]})
    question_answers = []
    for field in named[:12]:
        item = answers[field]
        item["id"] = f"question-{len(question_answers)+1}"
        item["finding_ids"] = [f["id"] for f in findings if set([field,target]).issubset(f["fields"])]
        question_answers.append(item)
    first = next((item for item in question_answers if item["status"] == "supported"), None)
    first = first or next((answers[field] for field in ordering if answers[field]["status"] == "supported"), None)
    first = first or (question_answers[0] if question_answers else answers[ordering[0]] if ordering else None)
    first_category = comparisons.get(first["fields"][0], {}).get("raw_category") if first else None
    headline = group_headline(first, target, event, first_category) if first else findings[0]["title"]
    answer = "".join(item["answer"] for item in question_answers[:3]) if question_answers else first["answer"] if first else takeaway
    if len(question_answers) > 3:
        answer += f"其余{len(question_answers)-3}项问题见逐项回答。"
    caveats = [caution, meaning(target)]
    if source.get("sampled"):
        caveats.append(f"这里只读取文件前{len(df):,}行，不能代表完整文件或随机样本。")
    if len(named) > 12:
        caveats.append(f"识别到{len(named)}项点名比较，本次仅回答前12项，其余{len(named)-12}项尚未回答。")
    if source.get("is_demo"):
        caveats.append("这是一份合成演示数据，不能代表真实业务。")
    focus = {"column": target, "label": target_label, "origin": origin, "lower_is_better": False,
             "meaning": explanation, "analyzable": True, "kind": "event" if event else "categorical"}
    brief = {"version": 1, "headline": headline, "answer": answer, "goal": goal, "focus": focus,
             "findings": findings, "question_answers": question_answers, "caveats": caveats,
             "next_questions": list(dict.fromkeys(item["next_step"] for item in (question_answers or list(answers.values()))))[:3],
             "coverage": {"analyzed_rows": len(df), "numeric_fields_scanned": len(numeric_fields(df)),
                          "relationships_evaluated": len(comparisons), "questions_detected": len(named),
                          "questions_answered": len(question_answers), "questions_omitted": max(0,len(named)-len(question_answers)),
                          "group_comparisons_evaluated": len(comparisons)}}
    evidence_items = question_answers or [answers[field] for field in ordering[:8]]
    evidence = {"focus": {k:v for k,v in focus.items() if k != "meaning"}, "target_relationships": [],
                "question_answers": [model_question(item) for item in evidence_items], "coverage": brief["coverage"]}
    if event:
        encoding = event["value"] if isinstance(event["value"], (int, float, bool)) else "来源已明确编码；原值仅留在本地报告"
        evidence["event"] = {"column": target, "value": encoding, "label": event["label"],
                             "count": int(clean.eq(event["value"]).sum()), "n": len(clean)}
    return brief, evidence


def schema_description(df, source):
    context = source.get("analysis_context", {})
    token = _CONTEXT.set(context if isinstance(context, dict) else {})
    try:
        return _schema_description(df, source)
    finally:
        _CONTEXT.reset(token)


def build_brief(df, kinds, target, origin, goal, charts, source):
    context = source.get("analysis_context", {})
    token = _CONTEXT.set(context if isinstance(context, dict) else {})
    try:
        if (target in df and not excluded_reason(target) and df[target].notna().sum() >= 5 and 2 <= df[target].nunique() <= 12
                and (category_field(df, target) or event_definition(df, target))):
            brief, evidence = _build_category_brief(df, kinds, target, origin, goal, charts, source)
        else:
            brief, evidence = _build_numeric_brief(df, kinds, target, origin, goal, charts, source)
        exclusions = [(field, excluded_reason(field)) for field in df if excluded_reason(field)]
        if exclusions:
            brief["caveats"].append("以下字段只保留基础画像，不进入重点解释或模型证据：" +
                                    "；".join(f"{label(field)}：{reason}" for field,reason in exclusions))
        return brief, evidence
    finally:
        _CONTEXT.reset(token)


def filter_excluded_model_evidence(aggregates, context):
    """Remove excluded-field aggregates while retaining local EDA unchanged."""
    fields = context.get("exclude_fields", {}) if isinstance(context, dict) else {}
    excluded = set(fields) if isinstance(fields, (dict, list)) else set()
    if not excluded:
        return aggregates
    references = {"name", "field", "column", "metric", "category", "date_column", "a", "b", "target"}
    missing = object()

    def scrub(value):
        if isinstance(value, dict):
            if any(isinstance(value.get(key), str) and value[key] in excluded for key in references):
                return missing
            if isinstance(value.get("fields"), list) and set(value["fields"]) & excluded:
                return missing
            result = {}
            for key, item in value.items():
                if key in excluded:
                    continue
                cleaned = scrub(item)
                if cleaned is not missing:
                    result[key] = cleaned
            return result
        if isinstance(value, list):
            result = []
            for item in value:
                if isinstance(item, str) and item in excluded:
                    continue
                cleaned = scrub(item)
                if cleaned is not missing:
                    result.append(cleaned)
            return result
        return value

    # The brief already excludes these relationships and may include a safe
    # method=excluded answer explaining why the user's question was withheld.
    result = scrub({k:v for k,v in aggregates.items() if k != "explanation_evidence"})
    result["explanation_evidence"] = aggregates["explanation_evidence"]
    result["excluded_explanatory_fields"] = [{"field": field, "reason": str(fields[field])[:1000] if isinstance(fields, dict)
                                              else "来源明确排除；不作为事前解释或预测依据。"} for field in sorted(excluded)]
    return result
