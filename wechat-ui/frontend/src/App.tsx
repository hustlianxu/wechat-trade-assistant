import { useCallback, useEffect, useState } from 'react'
import { api } from './api/client'
import type { AppConfig, Contact, HealthStatus, Message } from './types'
import ContactList from './components/ContactList'
import ChatView from './components/ChatView'
import SidePanel from './components/SidePanel'
import Settings from './components/Settings'

/**
 * 主应用：三栏布局
 * 左栏 ContactList：联系人/群聊/最近 + 搜索
 * 中栏 ChatView：当前会话消息
 * 右栏 SidePanel：时间过滤、意图/待办/总结
 */
export default function App() {
  // 当前选中会话
  const [selectedUsername, setSelectedUsername] = useState<string>('')
  const [selectedContact, setSelectedContact] = useState<Contact | null>(null)

  // 时间范围（秒级时间戳，0 表示不限）
  const [startTs, setStartTs] = useState<number>(0)
  const [endTs, setEndTs] = useState<number>(0)

  // 健康检查 / 配置
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false)

  // 搜索：当用户从搜索结果点击进入会话时，由 ContactList 触发
  const [messages, setMessages] = useState<Message[]>([])

  /** 拉取健康状态。 */
  const refreshHealth = useCallback(async () => {
    try {
      const h = await api.health()
      setHealth(h)
    } catch (e) {
      setHealth(null)
    }
  }, [])

  /** 拉取配置。 */
  const refreshConfig = useCallback(async () => {
    try {
      const c = await api.getConfig()
      setConfig(c)
    } catch (e) {
      setConfig(null)
    }
  }, [])

  useEffect(() => {
    refreshHealth()
    refreshConfig()
  }, [refreshHealth, refreshConfig])

  /** 选中会话。 */
  const handleSelectContact = useCallback((contact: Contact) => {
    setSelectedUsername(contact.username)
    setSelectedContact(contact)
    setMessages([])
  }, [])

  /** 选中搜索结果中的某条消息（跳转到对应会话）。 */
  const handleSelectMessage = useCallback((msg: Message, username: string) => {
    // 构造临时 Contact
    const contact: Contact = {
      username,
      nickname: '',
      remark: '',
      alias: '',
      display_name: username,
      is_group: username.endsWith('@chatroom'),
      is_official: username.startsWith('gh_'),
      last_msg_ts: msg.create_time,
      last_msg_summary: '',
      last_msg_type: 0,
      unread_count: 0,
    }
    setSelectedUsername(username)
    setSelectedContact(contact)
    setMessages([])
  }, [])

  /** 时间范围变更。 */
  const handleTimeRangeChange = useCallback((start: number, end: number) => {
    setStartTs(start)
    setEndTs(end)
  }, [])

  /** 配置保存后回调。 */
  const handleConfigSaved = useCallback((c: AppConfig) => {
    setConfig(c)
    refreshHealth()
  }, [refreshHealth])

  // 健康状态指示器
  const healthOk = health?.ok ?? false
  const healthHint = healthOk
    ? `已连接 · ${health?.decrypted_dir ? '已配置目录' : '未配置目录'}${health?.llm_configured ? ' · LLM 已就绪' : ''}`
    : '后端未连接，请确认 8766 端口已启动'

  return (
    <div className="app">
      {/* 左栏：联系人列表 */}
      <aside className="app__left">
        <div className="status-bar">
          <span className={`status-bar__dot ${healthOk ? 'status-bar__dot--ok' : 'status-bar__dot--error'}`} />
          <span>{healthHint}</span>
          <span className="status-bar__spacer" />
          <span className="status-bar__action" onClick={() => setSettingsOpen(true)}>
            设置
          </span>
        </div>
        <ContactList
          selectedUsername={selectedUsername}
          onSelectContact={handleSelectContact}
          onSelectMessage={handleSelectMessage}
        />
      </aside>

      {/* 中栏：聊天视图 */}
      <main className="app__center">
        <ChatView
          contact={selectedContact}
          username={selectedUsername}
          startTs={startTs}
          endTs={endTs}
          messages={messages}
          onMessagesLoaded={setMessages}
          onOpenSettings={() => setSettingsOpen(true)}
        />
      </main>

      {/* 右栏：功能面板 */}
      <aside className="app__right">
        <SidePanel
          username={selectedUsername}
          startTs={startTs}
          endTs={endTs}
          onTimeRangeChange={handleTimeRangeChange}
          config={config}
        />
      </aside>

      {/* 设置弹窗 */}
      {settingsOpen && (
        <Settings
          config={config}
          onClose={() => setSettingsOpen(false)}
          onSaved={handleConfigSaved}
        />
      )}
    </div>
  )
}
