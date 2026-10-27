# API 契约

所有业务接口使用 `/api`，JSON 字段为 snake_case。除健康检查、会话、登录、注册和退出外均需账号会话。账号 Cookie 不作为 URL 参数传递。对浏览器非只读 API 请求检查 Origin；开发代理只在本地允许指定的 Vite 来源。

上传、任务、下载和用量均按当前账号过滤，其他账号的资源 ID 返回 404。管理员只能配置共享模型，不因此获得普通报告接口的跨账号读取权限。已保存密钥永不通过 API 回传。

## 会话与账号

| 方法与路径 | 输入或返回 |
| --- | --- |
| `GET /api/health` | `{status:"ok"}` |
| `GET /api/session` | `{auth_required:true,authenticated,user:{id,username,role}|null,model_enabled,model_name,limits:{max_upload_mb:50,max_rows:100000,max_columns:80}}` |
| `POST /api/login` | JSON `{username:string,password:string}`，成功设置 Cookie 并返回 session |
| `POST /api/register` | 同上，注册普通用户并立即登录；不能指定角色或额度 |
| `POST /api/logout` | 删除会话 Cookie，返回 `{ok:true}` |

登录与注册要求严格字符串，额外字段返回 422。注册账号规范与限流见[账号说明](accounts-and-quotas.md)。`model_enabled` 表示配置能力，不等于当前用户有可用费用；启用模型前还应成功读取用量且未锁定。

## 上传、任务与报告

| 方法与路径 | 输入或返回 |
| --- | --- |
| `POST /api/uploads` | multipart `file`；返回 `{upload_id,filename,files:[{name,size}]}` |
| `POST /api/jobs` | JSON `{upload_id,selected_file,goal?:string,use_llm?:boolean,target_column?:string}`，返回 Job |
| `GET /api/jobs` | `{jobs:[Job]}`，当前账号最新在前，最多 100 项；列表不含完整结果 |
| `GET /api/jobs/{id}` | 当前账号 Job，包含可用结果；执行中可约每 1500 ms 轮询 |
| `POST /api/demo` | 创建明确标注的合成零售任务，不调用模型 |
| `POST /api/jobs/{id}/retry` | 可选 JSON `{use_llm:boolean}`，返回新 Job |
| `DELETE /api/jobs/{id}` | `{ok:true}`；不删除费用记录 |
| `GET /api/jobs/{id}/report.md` | 已完成任务的 Markdown 下载 |
| `GET /api/jobs/{id}/report.html` | 已完成任务的独立 HTML 下载 |

`selected_file` 必须来自上传返回的成员列表。支持 CSV、TSV、XLSX、ZIP，每次一张表，XLSX 为首工作表。`goal` 最长 2000 字符，`target_column` 最长 200 字符。读取范围与字段选择见 [EDA 设计](eda-design.md)。

重试的 `use_llm` 为严格 JSON boolean，额外键、null 字段、字符串或数字返回 422。**无请求体或 `{}` 均继承原任务的模型设置**；要确保免费重新分析，必须显式发送 `{use_llm:false}`。前端升级和失败重试弹窗默认关闭模型并发送显式值。重试是新分析，不能将它当作读取历史报告。原任务仍在运行时拒绝重试或删除。

## 用户用量与管理员密钥

- `GET /api/usage` 返回当前账号 Usage。
- `POST /api/model/authorize` 接收 `{api_key:string,confirm_budget:true}`，仅管理员可调用，经只读验证后更换共享密钥并直接返回其 Usage。不会给任何账号充值或重置费用。

```ts
type Usage = {
 currency:'USD'; user_id:string; role:'admin'|'user'; is_admin:boolean; unlimited:boolean;
 limit_usd:1|null;
 spent_usd:number; reserved_usd:number; uncertain_usd:number;
 remaining_usd:number|null; locked:boolean;
 model:string|null;
 input_per_million_usd:number|null; output_per_million_usd:number|null;
 prompt_tokens:number; completion_tokens:number; request_count:number;
 lifetime_spent_usd:number; last_error:string|null;
};
```

`spent_usd`、tokens、请求数和 `lifetime_spent_usd` 均为当前用户跨全部密钥周期的累计记录。金额按每笔向上取整至微美元后汇总；tokens 只累计可靠提供商值。普通 `limit_usd=1`，`remaining_usd=max(0,1-spent-reserved-uncertain)`；管理员 `unlimited=true`，上限和剩余为 null，不能显示为零。

`locked` 也可能表示缺失配置或账单安全限制，管理员也受异常保护。可用余额为正仍可能不足下一笔最坏预留。请求或晚到结算同时绑定用户与凭据周期，换密钥、删除任务或重启不会重置普通额度。用量读取失败不能替换成伪造零值。

授权错误：400 为无效密钥、配置或未确认；401 未登录；403 普通账号；409 有待完成模型调用；422 结构错误；503 只读验证不可达。密钥错误不会回显输入值。`confirm_budget` 是保留的接口字段名，当前表示确认使用共享密钥，不表示授予新的金额周期。

模型请求按服务端的模型/端点 allowlist、单价上限、ZDR 与最大 3200 输出 tokens 发送，无自动模型或供应商回退。预留、未知账单与计费口径见[模型与计费](model-and-budget.md)。

## Job 与结果

```ts
type Job = {
 id:string; filename:string; created_at:string;
 status:'queued'|'running'|'completed'|'failed'; progress:number;
 goal:string; is_demo:boolean; error:string|null;
 use_llm?:boolean; target_column?:string|null;
 steps:{key:string;label:string;status:'pending'|'running'|'completed'|'failed';detail:string}[];
 result?:Result|null;
};
type Result = {
 title:string; summary:string;
 source:{filename:string;is_demo:boolean;analyzed_rows:number;total_rows:number|null;sampled:boolean;sheet?:string|null;notes:string[]};
 overview:{rows:number;columns:number;numeric_columns:number;categorical_columns:number;missing_cells:number;missing_pct:number;duplicate_rows:number;quality_score:number};
 columns:{name:string;dtype:string;kind:'numeric'|'categorical'|'datetime'|'boolean';missing:number;missing_pct:number;unique:number;mean?:number|null;median?:number|null;min?:number|string|null;max?:number|string|null;std?:number|null;quantiles?:Quantiles|null;skew?:number|null;kurtosis?:number|null;iqr?:number|null;outlier_count?:number|null;outlier_pct?:number|null}[];
 charts:{id:string;title:string;description:string;type:string;figure:{data:any[];layout:any};wide?:boolean;section?:EdaSectionKey;fields?:string[];sample_notes?:string[]}[];
 insights:{title:string;body:string;level:'info'|'warning'|'success';evidence:string}[];
 recommendations:string[];
 preview:{columns:string[];rows:any[][]};
 agent:{mode:'statistical'|'llm';model:string|null;notes:string[];narrative?:string|null;
        review?:{status:string;reviewed_at?:string;note?:string;[key:string]:unknown}};
 duration_seconds:number;
 eda?:EdaV2|null;
};
```

所有统计均对应已分析行。截断时 `source.sampled=true` 且 `total_rows=null`；这是顺序前 N 行的有界读取，不是随机抽样。`quality_score` 是启发式，不是模型准确率。`agent.mode='llm'` 仅表示采用了模型新增文字，不代表事实验证通过；可选 `agent.review` 是该份结果的人工元数据。

`insights` 与 `recommendations` 包含原生统计项及可选模型新增项，不能按整个数组长度判断模型是否超出三条限制。预览与类别原值留在本地结果/报告；模型输入使用有界聚合和别名。

## EDA v2 增量字段

旧报告允许缺少 `eda`、扩展列统计或图表元数据。读取器必须兼容并保守展示，不能为补齐字段自动创建新任务。

```ts
type EdaSectionKey = 'quality'|'distributions'|'categories'|'relationships'|'groups'|'time'|'target';
type Quantiles = {p05:number|null;p25:number|null;p50:number|null;p75:number|null;p95:number|null};
type Pair = {a:string;b:string;r:number;n:number};
type Distribution = {
 column:string;n:number;mean:number|null;median:number|null;std:number|null;
 min:number|null;max:number|null;p05:number|null;p25:number|null;p50:number|null;
 p75:number|null;p95:number|null;skew:number|null;kurtosis:number|null;
 iqr:number|null;outlier_count:number|null;outlier_pct:number|null;
 zero_count:number;negative_count:number;
};
type Category = {
 column:string;n:number;unique:number;top1_pct:number;top3_pct:number;
 hhi:number;entropy:number;
 top_values:{group_id:string;label:string;count:number;pct:number}[];
};
type GroupStudy = {
 category:string;metric:string;
 groups:{group_id:string;label:string;n:number;mean:number|null;median:number|null;
         q25:number|null;q75:number|null;sum:number|null}[];
 omitted_groups:number;selection_note:string;
};
type TimeStudy = {
 date_column:string;metric:string;frequency:'D'|'W'|'MS';bucket_interval:number;
 points:{date:string;rows:number;n:number;mean:number|null;median:number|null;sum:number|null}[];
 start:string;end:string;total_buckets:number;nonempty_buckets:number;
 empty_buckets:number;coverage_pct:number;notes:string[];
};
type EdaV2 = {
 version:2;
 sections:{key:EdaSectionKey;label:string;description:string;chart_ids:string[]}[];
 coverage:{
  analyzed_rows:number;eligible_numeric_fields:string[];selected_numeric_fields:string[];
  selected_categorical_fields:string[];selected_datetime_fields:string[];
  excluded_fields:{field:string;reason:string}[];
  chart_count:number;max_charts:60;candidate_chart_count:number;omitted_chart_count:number;
  not_applicable:{section:EdaSectionKey;reason:string}[];
  selection_notes:string[];sampling_notes:string[];
 };
 distributions:Distribution[];categories:Category[];
 correlations:{pearson:Pair[];spearman:Pair[]};groups:GroupStudy[];time:TimeStudy[];
 target:{column:string|null;kind:'numeric'|'categorical'|'datetime'|'boolean'|null;
         summary:string;chart_ids:string[]};
};
```

深入探索确定性地选择最多 10 数值、5 类别、1 日期字段，最多 60 张唯一图。专题和目标可引用同一 `chart_id`，图的主专题保存在 `Chart.section`；覆盖统计不是所有可能图形的穷举。

Pearson/Spearman 使用成对完整样本，最少 5 对仅作计算防护，不代表显著。分组按支持数选择，至少 5 有效指标/组，最多 8 组/研究及 9 项研究；目标指标优先覆盖类别，`selection_note` 说明遗漏与范围。组别名在同类别不同指标间稳定。HHI 为份额平方和，熵使用 log2。

时间 `rows` 是有效日期记录数，`n` 是有效指标数；`n=0` 时均值、中位数、算术和均为 null。`coverage_pct` 是有日期记录的桶占比。跨度长时 `frequency='MS'`、`bucket_interval=N` 表示 N 月合桶。notes 给出日期有效分母，不能直接解释为历史事件趋势。

## 模型采纳边界与错误

模型输出经结构验证和已知高风险文字检查后才添加到结果。未采用时保留统计结果，并通过 `agent.notes` 说明原因、可靠费用状态及没有自动重试。检查不覆盖所有数值、排序或业务语义；未触发规则不等于解释正确。最大输出、提示目标和输入隐私见[Agent 设计](agent-design.md)。

常见错误采用 `{detail:string}`，避免回显密码、密钥、数据内容或内部路径：400 输入或数据问题，401 未登录，403 来源/权限不允许，404 不可访问资源，409 状态冲突，413 过大，422 参数结构，429 登录/注册限流或队列已满。报告尚未生成返回 409，不支持的扩展名返回 404。验证方法见 [testing.md](testing.md)。
