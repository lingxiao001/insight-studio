"""Local, evidence-linked explanations for readers who do not work with statistics.

This layer scans outcome relationships across all eligible fields, independently
of the bounded chart selection. It neither fits a model nor sends category labels
or rows to an external service.
"""
import math
import re

import pandas as pd


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
    key = normalized(name)
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
            if (not is_identifier(name, df[name]) or is_rank(name)
                or (name == target and not IDENTIFIER_NAME.search(name)))
            and df[name].notna().sum() >= 5 and df[name].nunique() > 1]


def choose_focus(df, goal="", requested=None):
    if requested in df.columns:
        return requested, "user"
    if requested:
        return None, "none"  # An invalid explicit selection must not silently change the question.
    candidates = numeric_fields(df)
    intent = str(goal).lower()
    # Prefer a field literally named in the question before domain suggestions.
    matches = [c for c in candidates if mention_position(c, goal, known_aliases=False) is not None]
    if matches:
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
    return "".join(notes)


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
        if categorical and not IDENTIFIER_NAME.search(field):
            status, status_label = "partial", "当前方法不适用"
            answer = f"{label(field)}是类别指标，不适用于与{label(target)}的数值排序关系比较。"
            explanation = "当前逐项回答只计算数值排序关系，本项未做类别间差异比较。请查看已生成的分组依据；未运行这种比较不能说明类别与目标没有关系，也不能判断差异大小。"
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


def schema_description(df, source):
    from .analysis import detect_types, IDENTIFIER_NAME
    kinds = detect_types(df)
    focus, _ = choose_focus(df)
    columns = []
    for c in df:
        selectable = (kinds[c] == "numeric" and not IDENTIFIER_NAME.search(c)
                      and df[c].notna().sum() >= 5 and df[c].nunique() > 1)
        reason = ("" if selectable else "关注指标需为非编号的数值列，至少5个有效值且包含不同取值；当前列不满足。")
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


def build_brief(df, kinds, target, origin, goal, charts, source):
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
            if kinds[category] not in {"categorical", "boolean"} or category == target:
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
            answer = "".join(item["answer"] for item in question_answers[:3]) + meaning(target)
            first_two = question_answers[:2]
            if len(first_two) == 2 and all(item["status"] == "supported" for item in first_two):
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
                "question_answers": [dict({k: item[k] for k in ("fields", "status", "n", "rho", "caveat")},
                                          method="not_applicable" if item.get("status_label") else "spearman")
                                     for item in question_answers], "coverage": brief["coverage"]}
    return brief, evidence
