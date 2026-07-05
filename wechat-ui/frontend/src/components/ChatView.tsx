import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Contact, Message } from '../types'
import { formatTime, shouldShowTimeDivider } from '../utils/format'
import MessageBubble from './MessageBubble'

interface Props {
  contact: Contact | null
  username: string
  /** 时间过滤（来自右栏 SidePanel）。 */
  startTs: number
  endTs: number
  /** 受控消息列表（由 App 持有，便于与右栏共享）。 */
  messages: Message[]
  onMessagesLoaded: (messages: Message[]) => void
  onOpenSettings: () => void
}

/**
 * 中栏：聊天记录显示
 * - 顶部显示当前会话名称
 * - 消息按时间正序显示
 * - 自己发的消息在右侧绿色气泡，对方在左侧白色气泡
 * - 时间戳超过 5 分钟间隔显示时间分隔线
 * - 群聊显示发送者昵称
 */
export default function ChatView({
  contact,
  username,
  startTs,
  endTs,
  messages,
  onMessagesLoaded,
  onOpenSettings,
}: Props) {
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  const bodyRef = useRef<HTMLDivElement>(null)

  /** 拉取消息。 */
  useEffect(() => {
    if (!username) {
      onMessagesLoaded([])
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    api
      .listMessages(username, {
        start_ts: startTs || 0,
        end_ts: endTs || 0,
        limit: 500,
        offset: 0,
      })
      .then((resp) => {
        if (cancelled) return
        onMessagesLoaded(resp.messages || [])
      })
      .catch((e) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : '加载失败')
        onMessagesLoaded([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [username, startTs, endTs, onMessagesLoaded])

  /** 滚动到底部。 */
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight
    }
  }, [messages.length])

  const title = contact?.display_name || username || ''
  const subtitle = contact?.is_group ? '群聊' : contact?.is_official ? '公众号' : ''

  // 空状态：未选择会话
  if (!username) {
    return (
      <div className="chat-view">
        <div className="chat-view__header">
          <span className="chat-view__title">微信会话分析助手</span>
          <div className="chat-view__header-actions">
            <button className="chat-view__header-btn" onClick={onOpenSettings}>
              设置
            </button>
          </div>
        </div>
        <div className="chat-view__body">
          <div className="chat-view__empty">
            <div className="chat-view__empty-icon">💬</div>
            <div className="chat-view__empty-text">从左侧选择会话开始查看</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-view">
      {/* 顶部会话名称 */}
      <div className="chat-view__header">
        <div>
          <span className="chat-view__title">{title}</span>
          {subtitle && <span className="chat-view__subtitle">{subtitle}</span>}
        </div>
        <div className="chat-view__header-actions">
          <span className="chat-view__subtitle">
            {startTs || endTs ? '时间已过滤' : '全部消息'}
          </span>
          <button className="chat-view__header-btn" onClick={onOpenSettings}>
            设置
          </button>
        </div>
      </div>

      {/* 消息列表 */}
      <div className="chat-view__body" ref={bodyRef}>
        {loading && <div className="side-panel__loading">加载中…</div>}
        {error && <div className="side-panel__error">{error}</div>}
        {!loading && !error && messages.length === 0 && (
          <div className="chat-view__empty">
            <div className="chat-view__empty-icon">📭</div>
            <div className="chat-view__empty-text">该时间范围内没有消息</div>
          </div>
        )}
        {!loading &&
          !error &&
          messages.map((msg, idx) => {
            const prev = idx > 0 ? messages[idx - 1] : null
            const showDivider = !prev || shouldShowTimeDivider(prev.create_time, msg.create_time)
            return (
              <div key={`${msg.local_id}-${idx}`}>
                {showDivider && msg.create_time > 0 && (
                  <div className="msg-time-divider">
                    <span>{formatTime(msg.create_time)}</span>
                  </div>
                )}
                <MessageBubble
                  message={msg}
                  username={username}
                  isGroup={!!contact?.is_group}
                />
              </div>
            )
          })}
      </div>
    </div>
  )
}
