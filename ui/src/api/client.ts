import type {
  OkResponse,
  DashboardData,
  ContactOut,
  ContactListResponse,
  MessageOut,
  MessageListResponse,
  SearchMessagesRequest,
  IntentLabelResponse,
  TodoOut,
  TodoListResponse,
  TodoCreateRequest,
  TodoUpdateRequest,
  TodoSummaryResponse,
  AssistantQueryRequest,
  AssistantMessageOut,
  AssistantHistoryResponse,
  SettingsResponse,
  LLMConfigRequest,
  RealtimeListenRequest,
  ManualKeyRequest,
  ManualKeysJsonRequest,
  ResignRequest,
  DecryptStatusResponse,
  DecryptTriggerRequest,
  DecryptTriggerResponse,
} from '../types/api';

// 后端 API 基地址：优先使用 preload 注入的地址，回退到默认本地地址
const BASE: string = (window.api?.apiUrl as string) || 'http://127.0.0.1:8765';

// 统一 fetch 封装：自动设置 JSON 头、解析响应、抛出错误
async function request<T>(urlPath: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${urlPath}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = '';
    try {
      detail = await res.text();
    } catch {
      /* 忽略读取错误 */
    }
    throw new Error(`HTTP ${res.status} ${res.statusText} ${detail}`);
  }
  // 部分接口可能返回空体，需做兼容
  const text = await res.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

// 拼接查询字符串，自动过滤空值
function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  });
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const api = {
  // ===== 健康检查 =====
  health: () => request<{ ok: boolean; ts: number }>('/api/health'),

  // ===== 仪表盘 =====
  getDashboard: () => request<DashboardData>('/api/dashboard'),

  // ===== 客户 =====
  listContacts: (p?: string | { intent?: string; q?: string; limit?: number; offset?: number }) => {
    // 兼容旧式调用：api.listContacts('intent_name')
    const params = typeof p === 'string' ? { intent: p || undefined } : p;
    return request<ContactListResponse>(`/api/contacts${qs(params as Record<string, any>)}`);
  },
  getContact: (id: number) => request<ContactOut>(`/api/contacts/${id}`),
  getContactMessages: (
    id: number,
    p?: { start_ts?: number; end_ts?: number; msg_type?: string; limit?: number }
  ) => request<MessageListResponse>(`/api/contacts/${id}/messages${qs(p)}`),

  // ===== 消息搜索 =====
  searchMessages: (body: SearchMessagesRequest) =>
    request<MessageListResponse>('/api/messages/search', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // ===== 意图识别 =====
  classifyIntent: (text: string) =>
    request<IntentLabelResponse>('/api/intent/classify', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
  classifyIntentBatch: (texts: string[]) =>
    request<{ results: IntentLabelResponse[] }>('/api/intent/classify/batch', {
      method: 'POST',
      body: JSON.stringify({ texts }),
    }),
  reclassifyContact: (id: number, limit?: number) =>
    request<{ updated: number }>(`/api/contacts/${id}/reclassify${qs({ limit })}`, {
      method: 'POST',
    }),

  // ===== 待办 =====
  listTodos: (p?: { status?: string; contact_id?: number; order_by?: string }) =>
    request<TodoListResponse>(`/api/todos${qs(p as Record<string, any>)}`),
  createTodo: (body: TodoCreateRequest) =>
    request<TodoOut>('/api/todos', { method: 'POST', body: JSON.stringify(body) }),
  updateTodo: (id: number, body: TodoUpdateRequest) =>
    request<OkResponse>(`/api/todos/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteTodo: (id: number) =>
    request<OkResponse>(`/api/todos/${id}`, { method: 'DELETE' }),
  getTodoSummary: () => request<TodoSummaryResponse>('/api/todos/summary'),
  autoExtractTodos: (contact_id?: number, limit?: number) =>
    request<{ extracted: number; todos: TodoOut[] }>(
      `/api/todos/auto-extract${qs({ contact_id, limit })}`,
      { method: 'POST' }
    ),

  // ===== 智能助手 =====
  queryAssistant: (body: AssistantQueryRequest) =>
    request<AssistantMessageOut>('/api/assistant/query', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getAssistantHistory: (limit?: number) =>
    request<AssistantHistoryResponse>(`/api/assistant/history${qs({ limit })}`),

  // ===== 语音转写 STT =====
  transcribePending: (limit?: number) =>
    request<{ total: number; success: number; results: any[] }>(
      `/api/stt/transcribe-pending${qs({ limit })}`,
      { method: 'POST' }
    ),
  getSttStatus: () =>
    request<{
      available: boolean;
      whisper_bin: string;
      model_path: string;
      language: string;
    }>('/api/stt/status'),

  // ===== 设置 =====
  getSettings: () => request<SettingsResponse>('/api/settings'),
  setLLM: (body: LLMConfigRequest) =>
    request<OkResponse>('/api/settings/llm', { method: 'POST', body: JSON.stringify(body) }),
  clearLLM: () => request<OkResponse>('/api/settings/llm', { method: 'DELETE' }),
  setRealtime: (body: RealtimeListenRequest) =>
    request<OkResponse>('/api/settings/realtime', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  setManualKey: (body: ManualKeyRequest) =>
    request<OkResponse>('/api/settings/manual-key', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  setManualKeysJson: (body: ManualKeysJsonRequest) =>
    request<OkResponse>('/api/settings/manual-keys-json', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getManualKeysJson: () =>
    request<{ keys_json: string; has_keys: boolean }>('/api/settings/manual-keys-json'),

  // ===== 数据目录（手动指定） =====
  setDataDir: (data_dir: string) =>
    request<OkResponse>('/api/settings/data-dir', {
      method: 'POST',
      body: JSON.stringify({ data_dir }),
    }),
  getDataDir: () =>
    request<{ data_dir: string; has_dir: boolean }>('/api/settings/data-dir'),

  // ===== 解密 =====
  getDecryptStatus: () => request<DecryptStatusResponse>('/api/decrypt/status'),
  triggerDecrypt: (body: DecryptTriggerRequest) =>
    request<DecryptTriggerResponse>('/api/decrypt/trigger', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  resign: (body: ResignRequest) =>
    request<OkResponse>('/api/decrypt/resign', { method: 'POST', body: JSON.stringify(body) }),
};

// 文件资源基址（用于图片缩略图等静态资源）
export const fileUrl = (p: string): string => `${BASE}/files/${encodeURIComponent(p)}`;
