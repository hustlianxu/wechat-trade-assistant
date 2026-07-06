// 与后端 schemas 一一对应的 TypeScript 类型定义

export interface OkResponse {
  ok: boolean;
  message: string;
}

export interface DashboardData {
  today_todo_count: number;
  pending_todo_count: number;
  unread_intent_contacts: number;
  recent_contacts: Array<Record<string, any>>;
  recent_todos: Array<Record<string, any>>;
}

export interface ContactOut {
  id: number;
  wxid: string;
  nickname: string;
  remark: string;
  alias: string;
  region: string;
  last_intent: string;
  last_intent_ts: number | null;
  last_msg_ts: number | null;
  note: string;
}
export interface ContactListResponse {
  contacts: ContactOut[];
  total: number;
}

export interface MessageOut {
  id: number;
  contact_id: number;
  msg_id: string | null;
  msg_type: string;
  direction: string;
  sender: string;
  content: string;
  thumb_path: string;
  transcribed: boolean;
  intent: string;
  confidence: number;
  created_ts: number;
}
export interface MessageListResponse {
  messages: MessageOut[];
  total: number;
}
export interface SearchMessagesRequest {
  contact_id?: number;
  contact_keyword?: string;
  keyword?: string;
  start_ts?: number;
  end_ts?: number;
  msg_type?: string;
  limit: number;
}

export interface IntentLabelResponse {
  intent: string;
  confidence: number;
}

export interface TodoOut {
  id: number;
  contact_id: number | null;
  message_id: number | null;
  title: string;
  detail: string;
  due_ts: number | null;
  status: string;
  source: string;
  priority: string;
  created_ts: number | null;
  updated_ts: number | null;
  completed_ts: number | null;
}
export interface TodoListResponse {
  todos: TodoOut[];
  total: number;
}
export interface TodoCreateRequest {
  title: string;
  contact_id?: number;
  detail: string;
  due_ts?: number;
  priority: string;
}
export interface TodoUpdateRequest {
  title?: string;
  detail?: string;
  due_ts?: number;
  status?: string;
  priority?: string;
  contact_id?: number;
}
export interface TodoSummaryResponse {
  by_status: Record<string, number>;
  by_contact: Array<Record<string, any>>;
}

export interface AssistantQueryRequest {
  text: string;
  use_cloud: boolean;
}
export interface AssistantMessageOut {
  id: number | null;
  role: string;
  content: string;
  parsed_query: string;
  matched_msg_ids: string;
  latency_ms: number;
  engine: string;
  created_ts: number | null;
  /** 云端 LLM 调用失败时的诊断信息（仅当曾尝试云端但降级到本地时非空） */
  llm_error?: string;
  messages: MessageOut[];
  contacts: ContactOut[];
  todos: TodoOut[];
}
export interface LLMTestResult {
  ok: boolean;
  provider?: string;
  model?: string;
  api_base?: string;
  response?: string;
  error?: string;
  config_hint?: string;
}
export interface AssistantHistoryResponse {
  turns: AssistantMessageOut[];
}

export interface SettingsResponse {
  wechat_version: string;
  wechat_generation: string;
  wechat_data_dirs: string[];
  needs_resign: boolean;
  is_resigned: boolean;
  realtime_listen: boolean;
  llm_api_base: string;
  llm_model: string;
  llm_api_key_set: boolean;
  whisper_available: boolean;
  intent_model_available: boolean;
  sqlcipher_available: boolean;
  db_path: string;
  data_dir: string;
}
export interface LLMConfigRequest {
  api_base: string;
  api_key: string;
  model: string;
  timeout: number;
}
export interface RealtimeListenRequest {
  enabled: boolean;
}
export interface ManualKeyRequest {
  key_hex: string;
}
export interface ManualKeysJsonRequest {
  keys_json: string;
}
export interface ResignRequest {
  password?: string | null;
}

export interface DecryptStatusResponse {
  wechat_detected: boolean;
  wechat_version: string;
  wechat_generation: string;
  needs_resign: boolean;
  needs_admin: boolean;
  data_dirs: string[];
  last_decrypt_run: Record<string, any> | null;
}
export interface DecryptDbResult {
  db_path: string;
  ok: boolean;
  message: string;
  msg_count: number;
  contact_count: number;
}
export interface DecryptTriggerRequest {
  source: string;
  manual_key?: string | null;
  manual_keys_json?: string | null;
  wxid?: string | null;
  data_dir?: string | null;
}
export interface DecryptTriggerResponse {
  ok: boolean;
  message: string;
  msg_count: number;
  contact_count: number;
  db_results: DecryptDbResult[];
}
/** 增量同步结果：仅拉取本地库中已存在消息之后的新消息。 */
export interface IncrementalDecryptResponse {
  ok: boolean;
  message: string;
  new_msg_count: number;
  data_dir: string;
  db_path: string;
}

// 渲染进程通过 preload 暴露的全局 API 类型
export interface WindowApi {
  apiUrl: string;
  backendError: string;
  openExternal: (url: string) => void;
}

declare global {
  interface Window {
    api?: WindowApi;
  }
}
