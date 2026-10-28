import { ArrowRight, BookOpen, ChevronDown, Lightbulb } from 'lucide-react';
import type { Result } from './types';
import ChartCard from './ChartCard';
import './brief.css';

export default function Brief({result, onExplore}: {result: Result; onExplore: () => void}) {
  const brief = result.brief!;
  const answers = brief.question_answers || [];
  const findings = <div className="brief-findings">{brief.findings.map(finding => <article key={finding.id} className={`brief-finding brief-${finding.kind}`}>
    <div className="brief-finding-heading"><h3>{finding.title}</h3></div>
    <p className="brief-takeaway">{finding.takeaway}</p>
    <div className="brief-explanation"><BookOpen size={16} aria-hidden="true"/><div><h4>怎样理解</h4><p>{finding.explanation}</p></div></div>
    <p className="brief-boundary"><strong>解释边界</strong>{finding.caveat}</p>
    {finding.next_step && <div className="brief-action"><strong>下一步怎么验证</strong><p>{finding.next_step}</p></div>}
    <details className="brief-evidence"><summary>核对数字与图表<span>{finding.n.toLocaleString('zh-CN')} 条有效记录</span><ChevronDown size={14} aria-hidden="true"/></summary>
      <div><p>{finding.evidence}</p>{finding.chart_ids.slice(0,1).map(id => {const chart=result.charts.find(c=>c.id===id);return chart ? <ChartCard key={id} chart={chart}/> : null;})}</div>
    </details>
  </article>)}</div>;
  const statusLabels = {supported: '观察到共同变化', partial: '未见清晰单调关系', insufficient: '暂不足以判断'};
  return <section className="explanation-brief" aria-label="主要结论与解释">
    <header className="brief-intro">
      <span className="brief-eyebrow"><Lightbulb size={16} aria-hidden="true"/>先看结论</span>
      <h2>{brief.headline}</h2>
      <p>{brief.answer}</p>
      {brief.goal && <div className="brief-goal"><span>你提出的问题</span><p>{brief.goal}</p></div>}
      {brief.focus.column && <div className="brief-focus"><span>{brief.focus.origin === 'auto' ? '自动关注' : '本次关注'}：<strong>{brief.focus.label}</strong></span><span>基于 {brief.coverage.analyzed_rows.toLocaleString('zh-CN')} 条记录</span>{brief.focus.meaning && <p>{brief.focus.meaning}</p>}</div>}
    </header>
    {answers.length > 0 && <section className="brief-answers" aria-labelledby="brief-answers-title"><header><h3 id="brief-answers-title">把问题逐一说清楚</h3><p>没有清晰关系和证据不足，也会如实保留。以下结果描述这份数据中的共同变化，不等于教学干预的效果。</p></header>
      {answers.map(item => <article key={item.id} className={`brief-question brief-question-${item.status}`}>
        <div className="brief-question-heading"><h4>{item.question}</h4><span className="brief-answer-status">{item.status_label || statusLabels[item.status]}</span></div>
        <p className="brief-question-answer">{item.answer}</p>
        <div className="brief-explanation"><BookOpen size={16} aria-hidden="true"/><div><h5>怎样理解</h5><p>{item.explanation}</p></div></div>
        <p className="brief-boundary"><strong>解释边界</strong>{item.caveat}</p>
        {item.next_step && <div className="brief-action"><strong>下一步怎么验证</strong><p>{item.next_step}</p></div>}
        <details className="brief-evidence"><summary>核对统计依据<span>{item.n.toLocaleString('zh-CN')} 条有效配对</span><ChevronDown size={14} aria-hidden="true"/></summary><div><p>{item.evidence}</p></div></details>
      </article>)}
    </section>}
    {answers.length > 0 ? <details className="brief-supplement"><summary>补充发现与指标口径<span>{brief.findings.length} 项</span></summary>{findings}</details> : findings}
    <section className="brief-next"><h3>接下来可以了解</h3><ol>{brief.next_questions.map(q=><li key={q}>{q}</li>)}</ol></section>
    <details className="brief-scope"><summary>这些结论适用于什么范围？</summary><ul>{brief.caveats.map(c=><li key={c}>{c}</li>)}</ul></details>
    <button type="button" className="button secondary" onClick={onExplore}>进一步核对统计依据<ArrowRight size={15} aria-hidden="true"/></button>
  </section>;
}
