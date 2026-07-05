// 类型定义：与后端 wechat-ui/backend/main.py 的 API 响应对齐

// ============================================================================
// 联系人 / 会话
// ============================================================================
export type ContactType = 'friends' | 'groups' | 'recent' | 'all'
export type SortType = 'recent' | 'name'

/** 联系人对象（对应后端 _contact_to_dict）。 */
export interface Contact {
  username: string
  nickname: string
  remark: string
  alias: string
  display_name: string
  is_group: boolean
  is_official: boolean
  /** 最后消息时间戳（秒），0 表示无会话记录。 */
  last_msg_ts: number
  last_msg_summary: string
  last_msg_type: number
  unread_count: number
}

export interface ContactListResponse {
  total: number
  contacts: Contact[]
}

// ============================================================================
// 消息
// ============================================================================

/** 消息基础类型常量（与后端 db_reader.py 对齐）。 */
export const MSG_TYPE = {
  TEXT: 1,
  IMAGE: 3,
  VOICE: 34,
  CONTACT_CARD: 42,
  VIDEO: 43,
  EMOJI: 47,
  LOCATION: 48,
  LINK: 49,
  VOIP: 50,
  SYSTEM: 10000,
  RECALL: 10002,
} as const

/** 解析后的消息内容（按类型有不同字段）。 */
export interface ParsedContent {
  // 图片
  md5?: string
  width?: number
  height?: number
  // 语音 / 视频
  length?: number
  // 链接 / 文件 / 小程序
  title?: string
  description?: string
  url?: string
  app_type?: number
  type_name?: string
  // 位置
  poiname?: string
  label?: string
  lat?: number
  lng?: number
  // 表情
  desc?: string
}

/** 单条消息（对应后端 _message_to_dict）。 */
export interface Message {
  local_id: number
  server_id: number
  local_type: number
  base_type: number
  sub_type: number
  type_name: string
  create_time: number
  sender_wxid: string
  is_self: boolean
  content: string
  parsed: ParsedContent
  transcription: string
}

export interface MessageListResponse {
  total: number
  messages: Message[]
}

// ============================================================================
// 配置
// ============================================================================
export interface WhisperConfig {
  binary_path: string
  model_path: string
  /** 语言提示：""=自动, "es"=西班牙语, "en"=英语, "zh"=普通话。 */
  language: string
}

export interface LLMProvider {
  name: string
  api_base: string
  api_key: string
  model: string
  /** 可选的语音转录模型（OpenAI Whisper 兼容）。 */
  whisper_model?: string
}

export interface AppConfig {
  decrypted_dir: string
  wechat_base_dir: string
  self_wxid: string
  whisper: WhisperConfig
  llm_providers: LLMProvider[]
  active_llm: string
}

// ============================================================================
// 分析接口返回
// ============================================================================
export interface IntentResult {
  intent: string
  confidence: number
  summary: string
}

export interface TodoItem {
  title: string
  detail?: string
  due?: string
  assignee?: string
  priority?: 'high' | 'medium' | 'low' | string
}

export interface TodoResult {
  todos: TodoItem[]
  error?: string
}

export interface SummaryResult {
  summary: string
}

// ============================================================================
// 语音转录
// ============================================================================
export interface TranscribeResult {
  text: string
  /** 来源：whisper_cpp | llm | error。 */
  source: string
}

// ============================================================================
// 搜索
// ============================================================================
export interface SearchResult {
  total: number
  messages: Message[]
}

// ============================================================================
// 健康检查
// ============================================================================
export interface HealthStatus {
  ok: boolean
  ts: number
  decrypted_dir: string
  self_wxid: string
  whisper_configured: boolean
  llm_configured: boolean
}
