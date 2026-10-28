import { ArrowRight, BookOpen, ChevronDown, Lightbulb } from 'lucide-react';
import type { Result } from './types';
import ChartCard from './ChartCard';
import './brief.css';

export default function Brief({result, onExplore}: {result: Result; onExplore: () => void}) {
  const brief = result.brief!;
  return <section className="explanation-brief" aria-label="主要结论与解释">
    <header className="brief-intro">
      <span className="brief-eyebrow"><Lightbulb size={16} aria-hidden="true"/>先看结论</span>
      <h2>{brief.headline}</h2>
      <p>{brief.answer}</p>
      {brief.focus.column && <div className="brief-focus"><span>{brief.focus.origin === 'auto' ? '自动关注' : '本次关注'}：<strong>{brief.focus.label}</strong></span><span>扫描 {brief.coverage.numeric_fields_scanned} 个数值字段 · 比较 {brief.coverage.relationships_evaluated} 组目标关系</span></div>}
    </header>
    <div className="brief-findings">{brief.findings.map((finding,index) => <article key={finding.id} className={`brief-finding brief-${finding.kind}`}>
      <div className="brief-finding-heading"><span className="brief-number">{String(index+1).padStart(2,'0')}</span><h3>{finding.title}</h3></div>
      <p className="brief-takeaway">{finding.takeaway}</p>
      <div className="brief-explanation"><BookOpen size={16} aria-hidden="true"/><p>{finding.explanation}</p></div>
      <details className="brief-evidence"><summary>查看依据与解释边界<span>{finding.n.toLocaleString('zh-CN')} 条有效记录</span><ChevronDown size={14} aria-hidden="true"/></summary>
        <div><p>{finding.evidence}</p><p>{finding.caveat}</p>{finding.chart_ids.slice(0,1).map(id => {const chart=result.charts.find(c=>c.id===id);return chart ? <ChartCard key={id} chart={chart}/> : null;})}</div>
      </details>
    </article>)}</div>
    <section className="brief-next"><h3>接下来可以了解</h3><ol>{brief.next_questions.map(q=><li key={q}>{q}</li>)}</ol></section>
    <details className="brief-scope"><summary>这些结论适用于什么范围？</summary><ul>{brief.caveats.map(c=><li key={c}>{c}</li>)}</ul></details>
    <button type="button" className="button secondary" onClick={onExplore}>按问题查看全部图表<ArrowRight size={15} aria-hidden="true"/></button>
  </section>;
}
