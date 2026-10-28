import { useEffect, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, BookOpen, CircleAlert, ExternalLink, LoaderCircle, Search } from 'lucide-react';
import { api } from './api';
import Brief from './Brief';
import ChartCard from './ChartCard';
import type { Result } from './types';
import './examples.css';

type ExampleSummary = {
  slug: string; title: string; description: string; topic: string;
  domain?: string; finding?: string; records?: number; fields?: number;
};
type Example = ExampleSummary & {result: Result; provenance: {
  citation: string; url: string; doi?: string; license: string; license_url?: string;
  population: string; preprocessing: string; publication: string;
  kaggle_url?: string; dataset_version?: string | number; accessed_at?: string;
}};

export default function PublicExamples({slug}: {slug: string | null}) {
  const [items, setItems] = useState<ExampleSummary[]>([]);
  const [example, setExample] = useState<Example | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [domain, setDomain] = useState('全部');
  const [query, setQuery] = useState('');
  const [chartsOpen, setChartsOpen] = useState(false);
  const charts = useRef<HTMLElement>(null);
  const availableDomains = [...new Set(items.map(item => item.domain || '其他'))];
  const preferredDomains = ['商业', '金融', '医疗', '娱乐', '教育'];
  const domains = ['全部', ...preferredDomains.filter(value => availableDomains.includes(value)),
    ...availableDomains.filter(value => !preferredDomains.includes(value))];
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = items.filter(item => (domain === '全部' || (item.domain || '其他') === domain)
    && (!normalizedQuery || [item.title, item.description, item.topic, item.domain, item.finding]
      .filter(Boolean).join(' ').toLocaleLowerCase().includes(normalizedQuery)));
  function explore() {
    setChartsOpen(true);
    requestAnimationFrame(() => {charts.current?.focus({preventScroll:true}); charts.current?.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});});
  }
  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(''); setExample(null); setChartsOpen(false);
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
        <div className="example-heading"><span className="brief-eyebrow"><BookOpen size={16} aria-hidden="true"/>公开分析示例 · {example.domain ? `${example.domain} / ` : ''}{example.topic}</span><h1>{example.title}</h1><p>{example.description}</p><div className="example-facts"><span>{example.result.overview.rows.toLocaleString('zh-CN')} 条记录</span><span>{example.result.overview.columns.toLocaleString('zh-CN')} 个字段</span><span>免费只读 · 不消耗额度</span><span>{example.result.agent.mode === 'llm' ? '统计与模型解释' : '统计分析 · 无模型调用'}</span></div><div className="example-downloads"><a className="button secondary" href={`/api/examples/${example.slug}/report.md`} download><ArrowDownToLine size={15} aria-hidden="true"/>下载 Markdown 报告</a><a className="button secondary" href={`/api/examples/${example.slug}/report.html`} download><ArrowDownToLine size={15} aria-hidden="true"/>下载离线报告</a></div></div>
        {example.result.brief && <Brief result={example.result} onExplore={explore}/>}
        <section ref={charts} className="example-charts" tabIndex={-1}><details open={chartsOpen} onToggle={event=>setChartsOpen(event.currentTarget.open)}><summary>用图表核对发现<span>{example.result.charts.length} 张图表</span></summary><p>图表只呈现聚合数值。把鼠标移到图形上，可以查看对应区间或分组。</p><div className="charts-grid">{chartsOpen && example.result.charts.map(chart=><ChartCard key={chart.id} chart={chart}/>)}</div></details></section>
        <section className="card example-provenance"><h2>这份分析来自哪里？</h2><p>{example.provenance.citation}</p><div className="example-source-links"><a href={example.provenance.url} target="_blank" rel="noreferrer">查看数据来源<ExternalLink size={13} aria-hidden="true"/></a>{example.provenance.kaggle_url && example.provenance.kaggle_url !== example.provenance.url && <a href={example.provenance.kaggle_url} target="_blank" rel="noreferrer">Kaggle 数据页<ExternalLink size={13} aria-hidden="true"/></a>}</div><dl className="example-source-facts">{example.provenance.dataset_version && <div><dt>数据版本</dt><dd>{example.provenance.dataset_version}</dd></div>}{example.provenance.accessed_at && <div><dt>获取日期</dt><dd>{example.provenance.accessed_at}</dd></div>}<div><dt>数据许可</dt><dd>{example.provenance.license_url ? <a href={example.provenance.license_url} target="_blank" rel="noreferrer">{example.provenance.license}<ExternalLink size={13} aria-hidden="true"/></a> : example.provenance.license}</dd></div>{example.provenance.doi && <div><dt>DOI</dt><dd>{example.provenance.doi}</dd></div>}</dl><p>{example.provenance.population}</p><p>{example.provenance.preprocessing}</p><p>{example.provenance.publication}</p></section>
      </> : <><div className="example-heading"><span className="brief-eyebrow"><BookOpen size={16} aria-hidden="true"/>公开分析示例</span><h1>从一个好问题，读懂一份数据</h1><p>从日常消费到健康与娱乐，先看结论，再查依据。每份分析都说明数字能回答什么，以及还不能确定什么。</p><div className="example-facts"><span>免登录阅读</span><span>免费只读 · 不消耗额度</span><span>可以下载报告</span></div></div><section className="example-selection" aria-label="查找分析示例"><div className="example-domains" role="group" aria-label="按领域筛选">{domains.map(value=><button className={domain === value ? 'active' : ''} key={value} aria-pressed={domain === value} onClick={()=>setDomain(value)}>{value}</button>)}</div><label className="example-search"><Search size={16} aria-hidden="true"/><span className="visually-hidden">搜索示例问题、领域或发现</span><input type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="搜索你关心的问题"/></label></section><p className="example-result-count" role="status">{normalizedQuery || domain !== '全部' ? `找到 ${filtered.length} 份分析` : `${items.length} 份公开分析`}</p><div className="example-catalog">{filtered.map(item=><a className="card example-card" key={item.slug} href={`?example=${item.slug}`}><span className="brief-eyebrow">{item.domain || '其他'} / {item.topic}</span><h2>{item.title}</h2><p>{item.finding || item.description}</p><div className="example-card-scale">{typeof item.records === 'number' && <span>{item.records.toLocaleString('zh-CN')} 条记录</span>}{typeof item.fields === 'number' && <span>{item.fields} 个字段</span>}</div><span className="text-button">阅读分析<ArrowRight size={15} aria-hidden="true"/></span></a>)}</div>{filtered.length === 0 && <div className="example-empty"><h2>没有找到匹配的示例</h2><p>换一个关键词，或查看所有领域。</p><button className="button secondary" onClick={()=>{setDomain('全部'); setQuery('');}}>查看全部示例</button></div>}<p className="example-catalog-note">公开示例展示聚合统计，不提供逐行个人记录。数据来源、适用范围和许可分别列在每份报告末尾；样本中的关联不直接代表因果关系。</p></>}
    </main><footer className="example-footer">Insight Studio · <a href="https://github.com/lingxiao001/insight-studio">开源代码</a> · <a href="https://github.com/lingxiao001/insight-studio/blob/main/LICENSE">AGPL-3.0</a></footer>
  </div>;
}
