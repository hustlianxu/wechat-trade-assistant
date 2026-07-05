import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Contact, ContactType, Message, SortType } from '../types'
import { avatarChar, formatShortTime, highlightKeyword, truncate } from '../utils/format'

interface Props {
  selectedUsername: string
  onSelectContact: (contact: Contact) => void
  /** 从搜索结果点击消息时触发（跳转到对应会话）。 */
  onSelectMessage: (msg: Message, username: string) => void
}

type Tab = 'friends' | 'groups' | 'recent'

const TAB_LABELS: Record<Tab, string> = {
  friends: '好友',
  groups: '群聊',
  recent: '最近',
}

/**
 * 左栏：联系人列表
 * - 顶部 3 个 tab：好友 / 群聊 / 最近
 * - 好友 tab 按显示名字母顺序；群聊 / 最近 按最近消息时间倒序（由后端 sort 控制）
 * - 顶部搜索框，支持跨会话关键词搜索
 */
export default function ContactList({ selectedUsername, onSelectContact, onSelectMessage }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('recent')
  const [contacts, setContacts] = useState<Contact[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string>('')

  // 搜索
  const [keyword, setKeyword] = useState<string>('')
  const [searching, setSearching] = useState<boolean>(false)
  const [searchResults, setSearchResults] = useState<Message[]>([])
  const [showSearch, setShowSearch] = useState<boolean>(false)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  /** 拉取联系人。 */
  const loadContacts = useCallback(async (tab: Tab) => {
    setLoading(true)
    setError('')
    try {
      const type: ContactType = tab
      // 好友按名字母序，群聊和最近按时间倒序
      const sort: SortType = tab === 'friends' ? 'name' : 'recent'
      const resp = await api.listContacts(type, sort)
      setContacts(resp.contacts || [])
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
      setContacts([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadContacts(activeTab)
  }, [activeTab, loadContacts])

  /** 触发搜索（防抖 300ms）。 */
  const handleKeywordChange = useCallback((value: string) => {
    setKeyword(value)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!value.trim()) {
      setSearchResults([])
      setShowSearch(false)
      return
    }
    searchTimer.current = setTimeout(async () => {
      setSearching(true)
      setShowSearch(true)
      try {
        const resp = await api.searchMessages(value.trim(), '', 50)
        setSearchResults(resp.messages || [])
      } catch (e) {
        setSearchResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
  }, [])

  /** 点击搜索结果中的某条消息。 */
  const handleSelectSearchMessage = useCallback(
    (msg: Message) => {
      // 消息 content 中群聊前缀 "wxid_xxx:\n..." 已被后端剥离
      // 这里需要从消息上下文中拿到 username。后端 search 接口未返回 username 字段，
      // 但 content 在群聊里可能含前缀；此处用 server_id/local_id 无法反推。
      // 兜底：使用 content 第一段前缀（如有 wxid: 格式）作为 username。
      const m = msg.content.match(/^([A-Za-z0-9_\-@.]+):\n?/)
      const username = m ? m[1] : ''
      if (username) {
        onSelectMessage(msg, username)
      }
      setShowSearch(false)
    },
    [onSelectMessage],
  )

  const handleCloseSearch = useCallback(() => {
    setShowSearch(false)
    setKeyword('')
    setSearchResults([])
  }, [])

  return (
    <div className="contact-list">
      {/* 搜索框 */}
      <div className="contact-list__search">
        <input
          className="contact-list__search-input"
          placeholder="搜索消息内容"
          value={keyword}
          onChange={(e) => handleKeywordChange(e.target.value)}
          onFocus={() => keyword && setShowSearch(true)}
        />
        {keyword && (
          <button className="btn btn--small btn--default" onClick={handleCloseSearch}>
            ✕
          </button>
        )}
      </div>

      {/* 搜索结果浮层 */}
      {showSearch && (
        <div className="search-results">
          {searching && <div className="side-panel__loading">搜索中…</div>}
          {!searching && searchResults.length === 0 && (
            <div className="side-panel__empty">未找到匹配消息</div>
          )}
          {!searching &&
            searchResults.map((msg, idx) => (
              <div
                key={`${msg.local_id}-${idx}`}
                className="search-result-item"
                onClick={() => handleSelectSearchMessage(msg)}
              >
                <div className="search-result-item__meta">
                  {msg.type_name} ·{' '}
                  {msg.create_time
                    ? new Date(msg.create_time * 1000).toLocaleString('zh-CN')
                    : ''}
                </div>
                <div className="search-result-item__snippet">
                  {highlightKeyword(truncate(msg.content, 60), keyword).map((part, i) =>
                    part.hit ? (
                      <span key={i} className="search-result-item__highlight">
                        {part.text}
                      </span>
                    ) : (
                      <span key={i}>{part.text}</span>
                    ),
                  )}
                </div>
              </div>
            ))}
        </div>
      )}

      {/* Tab 切换 */}
      <div className="contact-list__tabs">
        {(Object.keys(TAB_LABELS) as Tab[]).map((tab) => (
          <button
            key={tab}
            className={`contact-list__tab ${activeTab === tab ? 'contact-list__tab--active' : ''}`}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* 联系人列表 */}
      <div className="contact-list__items">
        {loading && <div className="side-panel__loading">加载中…</div>}
        {error && <div className="side-panel__error">{error}</div>}
        {!loading && !error && contacts.length === 0 && (
          <div className="contact-list__empty">暂无联系人</div>
        )}
        {!loading &&
          !error &&
          contacts.map((c) => {
            const avatarClass = c.is_group
              ? 'contact-item__avatar--group'
              : c.is_official
                ? 'contact-item__avatar--official'
                : ''
            return (
              <div
                key={c.username}
                className={`contact-item ${selectedUsername === c.username ? 'contact-item--active' : ''}`}
                onClick={() => onSelectContact(c)}
              >
                <div className={`contact-item__avatar ${avatarClass}`}>
                  {avatarChar(c.display_name)}
                </div>
                <div className="contact-item__body">
                  <div className="contact-item__row">
                    <span className="contact-item__name">{c.display_name}</span>
                    <span className="contact-item__time">
                      {c.last_msg_ts ? formatShortTime(c.last_msg_ts) : ''}
                    </span>
                  </div>
                  <div className="contact-item__row">
                    <span className="contact-item__summary">
                      {c.last_msg_summary || (c.alias ? `@${c.alias}` : c.username)}
                    </span>
                    {c.unread_count > 0 && (
                      <span className="contact-item__unread">
                        {c.unread_count > 99 ? '99+' : c.unread_count}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
      </div>
    </div>
  )
}
