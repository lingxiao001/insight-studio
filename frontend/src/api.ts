export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { credentials: 'same-origin', ...options, headers: { ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}), ...options.headers } });
  } catch { throw new ApiError('暂时无法连接服务，请检查网络后重试。', 0); }
  if (!response.ok) {
    let message = `请求失败（${response.status}），请稍后重试。`;
    try {
      const data = await response.json();
      if (typeof data.detail === 'string') message = data.detail;
      else if (typeof data.error === 'string') message = data.error;
      else if (Array.isArray(data.detail)) message = data.detail.map((item: {msg?: string}) => item.msg || '参数不正确').join('；');
    } catch { /* A reverse proxy may return non-JSON errors. */ }
    throw new ApiError(message, response.status);
  }
  return response.json() as Promise<T>;
}
