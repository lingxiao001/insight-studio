export type User = { id: string; username: string; role: 'admin' | 'user' };
export type Session = {
  user: User | null;
  auth_required: boolean; authenticated: boolean; model_enabled: boolean; model_name: string | null;
  limits: { max_upload_mb: number; max_rows: number; max_columns: number };
};
export type Upload = { upload_id: string; filename: string; files: { name: string; size: number }[] };
export type Step = { key: string; label: string; status: 'pending' | 'running' | 'completed' | 'failed'; detail: string };
export type Column = {
  name: string; dtype: string; kind: 'numeric' | 'categorical' | 'datetime' | 'boolean'; missing: number; missing_pct: number; unique: number;
  mean?: number | null; median?: number | null; min?: number | string | null; max?: number | string | null; std?: number | null;
  quantiles?: { p05: number | null; p25: number | null; p50: number | null; p75: number | null; p95: number | null } | null;
  skew?: number | null; kurtosis?: number | null; iqr?: number | null; outlier_count?: number | null; outlier_pct?: number | null;
};
export type Chart = { id: string; title: string; description: string; type: string; figure: { data: Record<string, any>[]; layout: Record<string, any> }; wide?: boolean; section?: SectionKey; fields?: string[]; sample_notes?: string[] };
export type Result = {
  title: string; summary: string;
  source: { filename: string; is_demo: boolean; analyzed_rows: number; total_rows: number | null; sampled: boolean; sheet?: string | null; notes: string[] };
  overview: { rows: number; columns: number; numeric_columns: number; categorical_columns: number; missing_cells: number; missing_pct: number; duplicate_rows: number; quality_score: number };
  columns: Column[]; charts: Chart[];
  insights: { title: string; body: string; level: 'info' | 'warning' | 'success'; evidence: string }[];
  recommendations: string[]; preview: { columns: string[]; rows: unknown[][] };
  agent: { mode: 'statistical' | 'llm'; model: string | null; notes: string[]; narrative?: string | null };
  duration_seconds: number; eda?: Eda | null; brief?: ExplanationBrief | null;
};
export type UploadSchema = {
  columns: { name: string; label: string; kind: string; meaning: string; selectable: boolean; suggested: boolean }[];
  suggested_target: string | null; analyzed_rows: number; notes: string[];
  questions: {label: string; target: string | null; goal: string}[];
};
export type ExplanationBrief = {
  version: number; headline: string; answer: string; goal: string;
  focus: {column: string | null; label: string | null; origin: string; lower_is_better: boolean; meaning: string};
  question_answers?: {id: string; question: string; answer: string; status: 'supported' | 'partial' | 'insufficient'; status_label?: string; explanation: string; evidence: string; caveat: string; next_step: string; fields: string[]; n: number; rho: number | null; finding_ids: string[]}[];
  findings: {id: string; kind: string; title: string; takeaway: string; explanation: string; evidence: string; caveat: string; n: number; fields: string[]; chart_ids: string[]; next_step: string}[];
  next_questions: string[]; caveats: string[];
  coverage: {analyzed_rows: number; numeric_fields_scanned: number; relationships_evaluated: number};
};
export type Job = {
  id: string; filename: string; created_at: string; status: 'queued' | 'running' | 'completed' | 'failed'; progress: number;
  goal: string; use_llm?: boolean; target_column?: string | null; is_demo: boolean; error: string | null; steps: Step[]; result?: Result | null;
};
export type Usage = {
  currency: 'USD'; unlimited?: boolean; role?: 'admin' | 'user'; is_admin?: boolean; limit_usd: number | null; spent_usd: number; reserved_usd: number; uncertain_usd: number;
  remaining_usd: number | null; locked: boolean; model: string | null;
  input_per_million_usd: number | null; output_per_million_usd: number | null;
  prompt_tokens: number; completion_tokens: number; request_count: number;
  lifetime_spent_usd: number; last_error: string | null;
};

export type SectionKey = 'quality' | 'distributions' | 'categories' | 'relationships' | 'groups' | 'time' | 'target';
export type EdaSection = { key: SectionKey; label: string; description: string; chart_ids: string[] };
export type Coverage = {
  analyzed_rows: number; eligible_numeric_fields: string[]; selected_numeric_fields: string[]; selected_categorical_fields: string[]; selected_datetime_fields: string[];
  excluded_fields: { field: string; reason: string }[]; chart_count: number; max_charts: number; candidate_chart_count: number; omitted_chart_count: number;
  not_applicable: { section: SectionKey; reason: string }[]; selection_notes: string[]; sampling_notes: string[];
};
export type Distribution = {
  column: string; n: number; mean: number | null; median: number | null; std: number | null; min: number | null; max: number | null;
  p05: number | null; p25: number | null; p50: number | null; p75: number | null; p95: number | null; skew: number | null; kurtosis: number | null;
  iqr: number | null; outlier_count: number | null; outlier_pct: number | null; zero_count: number; negative_count: number;
};
export type CategoryStudy = { column: string; n: number; unique: number; top1_pct: number; top3_pct: number; hhi: number; entropy: number; top_values: { group_id?: string; label: string; count: number; pct: number }[] };
export type CorrelationPair = { a: string; b: string; r: number; n: number };
export type GroupStudy = { category: string; metric: string; groups: { group_id?: string; label: string; n: number; mean: number | null; median: number | null; q25: number | null; q75: number | null; sum: number | null }[]; omitted_groups: number; selection_note: string };
export type TimeStudy = { date_column: string; metric: string; frequency: 'D' | 'W' | 'MS'; bucket_interval?: number; points: { date: string; rows?: number; n: number; mean: number | null; median: number | null; sum: number | null }[]; start: string; end: string; total_buckets: number; nonempty_buckets: number; empty_buckets: number; coverage_pct: number; notes: string[] };
export type Eda = { version: 2; sections: EdaSection[]; coverage: Coverage; distributions: Distribution[]; categories: CategoryStudy[]; correlations: { pearson: CorrelationPair[]; spearman: CorrelationPair[] }; groups: GroupStudy[]; time: TimeStudy[]; target: { column: string | null; kind: string | null; summary: string; chart_ids: string[] } };
