import { useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import { BarChart3, Database, LoaderCircle, LockKeyhole, ShieldCheck, Workflow } from 'lucide-react';
import { api } from './api';
import type { Session } from './types';

export default function AuthScreen({ brand, illustration, onLogin }: { brand: ReactNode; illustration: ReactNode; onLogin: (session: Session) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState(''); const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const operation = useRef(false);
  const register = mode === 'register';
  function switchMode(next: 'login' | 'register') { if (operation.current) return; setMode(next); setPassword(''); setError(''); }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (operation.current || !username.trim() || !password) return;
    operation.current = true; setBusy(true); setError('');
    try { const next = await api<Session>(`/${mode}`, { method: 'POST', body: JSON.stringify({ username: username.trim(), password }) }); setPassword(''); onLogin(next); }
    catch (problem) { setError((problem as Error).message); }
    finally { operation.current = false; setBusy(false); }
  }
  return <div className="login-page"><div className="login-card">{brand}
    <div className="login-heading"><span className="login-space"><LockKeyhole aria-hidden="true" size={13}/>独立账号 · 私有分析档案</span><h1>{register ? '创建数据账号' : '登录数据研究室'}</h1><p>{register ? '建立自己的资料与分析空间，新账号获得 $1 USD 模型使用额度。' : '读取自己的资料，检查证据，留下一份清楚的分析记录。'}</p></div>
    <div className="auth-mode" role="group" aria-label="选择登录或注册"><button type="button" aria-pressed={!register} disabled={busy} onClick={() => switchMode('login')}>登录</button><button type="button" aria-pressed={register} disabled={busy} onClick={() => switchMode('register')}>创建账号</button></div>
    <form onSubmit={submit} aria-busy={busy}><fieldset className="auth-fields" disabled={busy}><legend className="visually-hidden">{register ? '创建账号' : '账号登录'}</legend>
      <label className="field-label" htmlFor="auth-username">用户名</label><input id="auth-username" name="username" type="text" autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false} value={username} onChange={event => setUsername(event.target.value)} required minLength={register ? 3 : undefined} maxLength={32} placeholder={register ? '3–32 个字符，中英文、数字或 _ . -' : '输入你的用户名'} aria-invalid={!!error} aria-describedby={error ? 'auth-error' : undefined}/>
      <label className="field-label auth-password-label" htmlFor="auth-password">密码</label><input id="auth-password" name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} value={password} onChange={event => setPassword(event.target.value)} required minLength={register ? 10 : undefined} maxLength={128} placeholder={register ? '至少 10 个字符' : '输入账号密码'} aria-invalid={!!error} aria-describedby={error ? 'auth-error' : register ? 'auth-password-help' : undefined}/>
      {register && <p className="auth-field-note" id="auth-password-help">请使用至少 10 个字符的密码，避免与其他网站重复。</p>}{error && <p id="auth-error" className="error-text" role="alert">{error}</p>}
      <button className="button primary full" disabled={busy || !username.trim() || !password}>{busy ? <LoaderCircle aria-hidden="true" size={17} className="spin"/> : <LockKeyhole aria-hidden="true" size={17}/>} {busy ? register ? '正在创建账号…' : '正在登录…' : register ? '创建账号并登录' : '进入研究室'}</button>
    </fieldset></form><p className="login-note"><ShieldCheck aria-hidden="true" size={14}/>分析档案与模型用量按账号独立记录。</p><a className="public-example-entry" href="?view=examples"><BarChart3 size={16} aria-hidden="true"/>先看公开分析示例 · 免登录</a>
  </div><div className="login-art"><div className="login-art-content"><h2>一份资料，<br/>多重观察。</h2>{illustration}<div className="login-capabilities"><span><Database aria-hidden="true" size={17}/>统计探索</span><span><Workflow aria-hidden="true" size={17}/>Agent 推理</span><span><BarChart3 aria-hidden="true" size={17}/>交互图表</span></div><p>从日常的表格里，整理出可以核对的发现。</p></div></div></div>;
}
