// API 客户端：基于 fetch 封装，base URL 为空（同源走 Vite proxy）。

import type {
  AppConfig,
  AutoSetupResult,
  ContactListResponse,
  ContactType,
  HealthStatus,
  IntentResult,
  MessageListResponse,
  SearchResult,
  SortType,
  SummaryResult,
  TodoResult,
  TranscribeResult,
} from '../types'

/** base URL：开发环境为空字符串（同源走 Vite proxy 到 8766）。 */
const BASE_URL = ''

/** 通用请求封装，自动 JSON 解析并抛出业务异常。 */
async function request<T>(
  url: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  }
  // 非 FormData 请求自动加 JSON content-type
  if (!(options.body instanceof FormData) && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json'
  }

  const resp = await fetch(`${BASE_URL}${url}`, { ...options, headers })

  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const err = await resp.json()
      if (err && err.detail) detail = String(err.detail)
    } catch {
      // 非 JSON 错误响应
    }
    throw new Error(detail)
  }

  // WAV 等二进制响应由调用方单独处理
  return (await resp.json()) as T
}

/** 构造 query string。 */
function qs(params: Record<string, string | number | boolean | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '' && v !== null) usp.set(k, String(v))
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

// ============================================================================
// 健康检查
// ============================================================================
export const api = {
  /** 健康检查。 */
  health: () => request<HealthStatus>('/api/health'),

  // ------------------------------------------------------------------------
  // 配置
  // ------------------------------------------------------------------------
  getConfig: () => request<AppConfig>('/api/config'),

  saveConfig: (config: Partial<AppConfig>) =>
    request<AppConfig>('/api/config', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  // ------------------------------------------------------------------------
  // 自动检测与自动解密
  // ------------------------------------------------------------------------
  /** 触发自动检测配置（傻瓜式：自动找微信目录、自动解密、自动填 wxid）。 */
  autoSetup: (force = false) =>
    request<AutoSetupResult>(`/api/auto-setup${qs({ force })}`, { method: 'POST' }),

  /** 查询自动检测状态（不修改配置）。 */
  autoSetupStatus: () =>
    request<{ has_decrypted_dir: boolean; decrypted_dir_preview: string }>(
      '/api/auto-setup/status',
    ),

  // ------------------------------------------------------------------------
  // 联系人
  // ------------------------------------------------------------------------
  listContacts: (type: ContactType, sort: SortType = 'recent') =>
    request<ContactListResponse>(`/api/contacts${qs({ type, sort })}`),

  getContact: (username: string) =>
    request<import('../types').Contact>(`/api/contacts/${encodeURIComponent(username)}`),

  // ------------------------------------------------------------------------
  // 消息
  // ------------------------------------------------------------------------
  listMessages: (
    username: string,
    params: { start_ts?: number; end_ts?: number; limit?: number; offset?: number } = {},
  ) =>
    request<MessageListResponse>(
      `/api/messages/${encodeURIComponent(username)}${qs(params)}`,
    ),

  searchMessages: (keyword: string, username = '', limit = 100) =>
    request<SearchResult>(`/api/search${qs({ keyword, username, limit })}`),

  // ------------------------------------------------------------------------
  // 语音
  // ------------------------------------------------------------------------
  /** 获取语音 WAV 数据 URL（可直接作为 <audio> src）。 */
  voiceUrl: (username: string, localId: number) =>
    `${BASE_URL}/api/voice/${encodeURIComponent(username)}/${localId}`,

  transcribe: (username: string, local_id: number) =>
    request<TranscribeResult>('/api/transcribe', {
      method: 'POST',
      body: JSON.stringify({ username, local_id }),
    }),

  // ------------------------------------------------------------------------
  // 分析
  // ------------------------------------------------------------------------
  analyzeIntent: (
    username: string,
    params: { start_ts?: number; end_ts?: number; limit?: number } = {},
  ) =>
    request<IntentResult>(
      `/api/analyze/intent/${encodeURIComponent(username)}${qs(params)}`,
      { method: 'POST' },
    ),

  analyzeTodos: (
    username: string,
    params: { start_ts?: number; end_ts?: number; limit?: number } = {},
  ) =>
    request<TodoResult>(
      `/api/analyze/todos/${encodeURIComponent(username)}${qs(params)}`,
      { method: 'POST' },
    ),

  analyzeSummary: (
    username: string,
    params: { start_ts?: number; end_ts?: number; limit?: number } = {},
  ) =>
    request<SummaryResult>(
      `/api/analyze/summary/${encodeURIComponent(username)}${qs(params)}`,
      { method: 'POST' },
    ),
}
