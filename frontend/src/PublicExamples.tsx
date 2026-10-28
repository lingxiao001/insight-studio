import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, BookOpen, CircleAlert, ExternalLink, LoaderCircle } from 'lucide-react';
import { api } from './api';
import Brief from './Brief';
import ChartCard from './ChartCard';
import type { Result } from './types';
import './examples.css';

type ExampleSummary = {slug: string; title: string; description: string; topic: string};
type Example = ExampleSummary & {result: Result; provenance: {
  citation: string; url: string; doi: string; license: string; license_url: string;
  population: string; preprocessing: string; publication: string;
}};

export default function PublicExamples({slug}: {slug: string | null}) {
  const [items, setItems] = useState<ExampleSummary[]>([]);
  const [example, setExample] = useState<Example | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [chartsOpen, setChartsOpen] = useState(false);
  const charts = useRef<HTMLElement>(null);
  function explore() {
    setChartsOpen(true);
    requestAnimationFrame(() => {charts.current?.focus({preventScroll:true}); charts.current?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});});
  }
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError('');
    const request = slug ? api<Example>(`/examples/${encodeURIComponent(slug)}`).then(value => {if (!cancelled) setExample(value);})
      : api<{examples: ExampleSummary[]}>('/examples').then(value => {if (!cancelled) setItems(value.examples);});
    void request.catch(problem => {if (!cancelled) setError((problem as Error).message);})
      .finally(() => {if (!cancelled) setLoading(false);});
    return () => {cancelled = true;};
  }, [slug, attempt]);
  return <div className="public-examples"><a className="skip-link" href="#example-content">跳到分析内容</a>
    <header className="example-header"><a className="brand" href="/"><span className="brand-rule" aria-hidden="true"/><div><strong>Insight Studio</strong><small>数据研究室</small></div></a><a className="button secondary" href="/">进入研究室<ArrowRight size={15} aria-hidden="true"/></a></header>
    <main id="example-content" className="example-content">
      <a className="back-link" href={slug ? '?view=examples' : '/'}><ArrowLeft size={14} aria-hidden="true"/>{slug ? '全部公开示例' : '返回研究室'}</a>
      {loading ? <div className="loading-state" role="status"><LoaderCircle size={24} className="spin" aria-hidden="true"/><p>正在读取公开示例…</p></div> : error ? <div className="card example-error" role="alert"><CircleAlert size={24} aria-hidden="true"/><h1>暂时无法打开示例</h1><p>{error}</p><button className="button secondary" onClick={()=>setAttempt(value=>value+1)}>重新读取</button></div> : example ? <>
        <div className="example-heading"><span className="brief-eyebrow"><BookOpen size={16} aria-hidden="true"/>公开分析示例 · {example.topic}</span><h1>{example.title}</h1><p>{example.description}</p><div className="example-facts"><span>{example.result.overview.rows.toLocaleString('zh-CN')} 条记录</span><span>{example.result.overview.columns.toLocaleString('zh-CN')} 个字段</span><span>免登录阅读</span><span>{example.result.agent.mode === 'llm' ? '统计与模型解释' : '统计分析 · 无模型调用'}</span></div><div className="example-downloads"><a className="button secondary" href={`/api/examples/${example.slug}/report.md`} download><ArrowDownToLine size={15} aria-hidden="true"/>下载 Markdown 报告</a><a className="button secondary" href={`/api/examples/${example.slug}/report.html`} download><ArrowDownToLine size={15} aria-hidden="true"/>下载离线报告</a></div></div>
        {example.result.brief && <Brief result={example.result} onExplore={explore}/>}
        <section ref={charts} className="example-charts" tabIndex={-1}><details open={chartsOpen} onToggle={event=>setChartsOpen(event.currentTarget.open)}><summary>用图表核对发现<span>{example.result.charts.length} 张图表</span></summary><p>图表只呈现聚合数值。把鼠标移到图形上，可以查看对应区间或分组。</p><div className="charts-grid">{chartsOpen && example.result.charts.map(chart=><ChartCard key={chart.id} chart={chart}/>)}</div></details></section>
        <section className="card example-provenance"><h2>这份分析来自哪里？</h2><p>{example.provenance.citation} · <a href={example.provenance.url} target="_blank" rel="noreferrer">查看原始数据来源<ExternalLink size={13} aria-hidden="true"/></a></p><p>{example.provenance.population}</p><p>{example.provenance.preprocessing}</p><p>{example.provenance.publication}</p><p>数据许可：<a href={example.provenance.license_url} target="_blank" rel="noreferrer">{example.provenance.license}</a>。DOI：{example.provenance.doi}。</p></section>
      </> : <><div className="example-heading"><span className="brief-eyebrow"><BookOpen size={16} aria-hidden="true"/>公开分析示例</span><h1>先读一份有依据的结论</h1><p>同一份毕业生数据，从两个问题出发。展开依据，看看数字支持怎样的解释。</p><div className="example-facts"><span>免登录</span><span>无需上传</span><span>可以下载报告</span></div></div><div className="example-catalog">{items.map(item=><a className="card example-card" key={item.slug} href={`?example=${item.slug}`}><span className="brief-eyebrow">{item.topic}</span><h2>{item.title}</h2><p>{item.description}</p><span className="text-button">阅读分析<ArrowRight size={15} aria-hidden="true"/></span></a>)}</div><p className="example-catalog-note">来源：Mendeley Data · Graduation V1 · CC BY 4.0。253名毕业生的课程和量表记录，自评不能替代实际就业结果。</p></>}
    </main><footer className="example-footer">Insight Studio · <a href="https://github.com/lingxiao001/insight-studio">开源代码</a> · <a href="https://github.com/lingxiao001/insight-studio/blob/main/LICENSE">AGPL-3.0</a></footer>
  </div>;
}
