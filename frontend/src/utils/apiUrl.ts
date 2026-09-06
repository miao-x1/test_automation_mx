/**
 * 浏览器 → Vite/Nginx → FastAPI 的路径约定。
 *
 * 开发代理与生产 Nginx 都会去掉第一段 `/api` 再转发：
 *   /api/requirement/x  →  /requirement/x
 *   /api/api/v1/x       →  /api/v1/x
 *
 * axios instance 的 baseURL 已是 `/api`，因此 axios 的 url 写 `/api/v1/x`
 * 会变成 `/api/api/v1/x`，去前缀后正好命中后端。
 *
 * fetch / EventSource 没有 baseURL，访问后端 `/api/v1` 或 `/api/v2` 时
 * 必须再补一层 `/api`。其它后端路径（/requirement、/upload/task）保持 `/api` + 路径。
 */
export function browserApiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`;
  if (p.startsWith('/api/v1') || p.startsWith('/api/v2')) {
    return `/api${p}`;
  }
  if (p.startsWith('/api/')) {
    return p;
  }
  return `/api${p}`;
}
