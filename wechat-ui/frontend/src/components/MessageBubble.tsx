import type { Message } from '../types'
import { MSG_TYPE } from '../types'
import { avatarChar, formatTime } from '../utils/format'
import VoiceMessage from './VoiceMessage'

interface Props {
  message: Message
  username: string
  /** 是否为群聊（用于决定是否显示发送者昵称）。 */
  isGroup: boolean
}

/**
 * 消息气泡：根据 base_type 渲染不同内容
 * - 自己消息右对齐绿色背景，对方左对齐白色背景
 * - 群聊显示发送者名称
 * - 时间显示
 * - 引用 VoiceMessage 处理语音
 */
export default function MessageBubble({ message, username, isGroup }: Props) {
  const { is_self, base_type, content, parsed, create_time, sender_wxid, transcription } = message

  // 系统消息：居中灰色
  if (base_type === MSG_TYPE.SYSTEM || base_type === MSG_TYPE.RECALL) {
    return (
      <div className="msg-row msg-row--system">
        <div className="msg-system">{content || message.type_name}</div>
      </div>
    )
  }

  const avatarName = is_self ? '我' : (sender_wxid || username)

  return (
    <div className={`msg-row ${is_self ? 'msg-row--self' : ''}`}>
      <div className={`msg-avatar ${is_self ? 'msg-avatar--self' : 'msg-avatar--other'}`}>
        {avatarChar(avatarName)}
      </div>
      <div className="msg-content">
        {/* 群聊显示发送者昵称（自己的消息也显示"我"） */}
        {(isGroup || is_self) && (
          <div className="msg-sender">{is_self ? '我' : sender_wxid || '对方'}</div>
        )}
        <div className={`msg-bubble ${is_self ? 'msg-bubble--self' : 'msg-bubble--other'}`}>
          <MessageBody
            baseType={base_type}
            content={content}
            parsed={parsed}
            username={username}
            localId={message.local_id}
            lengthMs={parsed?.length}
            transcription={transcription}
          />
        </div>
        <div className="msg-sender">{create_time ? formatTime(create_time) : ''}</div>
      </div>
    </div>
  )
}

/** 根据消息类型渲染气泡内部内容。 */
function MessageBody({
  baseType,
  content,
  parsed,
  username,
  localId,
  lengthMs,
  transcription,
}: {
  baseType: number
  content: string
  parsed: Message['parsed']
  username: string
  localId: number
  lengthMs?: number
  transcription: string
}) {
  switch (baseType) {
    case MSG_TYPE.TEXT:
      return <>{content}</>

    case MSG_TYPE.IMAGE:
      return (
        <div className="msg-media">
          <div className="msg-media__icon">🖼</div>
          <div className="msg-media__label">图片</div>
          {(parsed?.width || parsed?.height) && (
            <div className="msg-media__label" style={{ background: 'transparent' }}>
              {parsed.width}×{parsed.height}
            </div>
          )}
        </div>
      )

    case MSG_TYPE.VOICE:
      return (
        <VoiceMessage
          username={username}
          localId={localId}
          lengthMs={lengthMs}
          initialTranscription={transcription}
        />
      )

    case MSG_TYPE.VIDEO:
      return (
        <div className="msg-media">
          <div className="msg-media__icon">▶</div>
          <div className="msg-media__label">视频</div>
          {parsed?.length ? (
            <div className="msg-media__label" style={{ background: 'transparent' }}>
              {Math.ceil(parsed.length)}秒
            </div>
          ) : null}
        </div>
      )

    case MSG_TYPE.EMOJI:
      return (
        <div className="msg-media" style={{ width: 100, minHeight: 100 }}>
          <div className="msg-media__icon" style={{ fontSize: 40 }}>😊</div>
          <div className="msg-media__label">表情</div>
        </div>
      )

    case MSG_TYPE.LINK:
    case 49: // 链接 / 文件 / 小程序
      return (
        <a
          className="msg-link-card"
          href={parsed?.url || '#'}
          target="_blank"
          rel="noopener noreferrer"
        >
          {parsed?.title && <div className="msg-link-card__title">{parsed.title}</div>}
          {parsed?.description && <div className="msg-link-card__desc">{parsed.description}</div>}
          {parsed?.url && <div className="msg-link-card__url">{parsed.url}</div>}
          {!parsed?.title && !parsed?.description && <div className="msg-link-card__title">{content.slice(0, 50)}</div>}
        </a>
      )

    case MSG_TYPE.LOCATION:
      return (
        <div className="msg-location">
          <span className="msg-location__icon">📍</span>
          <span className="msg-location__name">
            {parsed?.poiname || parsed?.label || '位置'}
          </span>
        </div>
      )

    case MSG_TYPE.CONTACT_CARD:
      return (
        <div className="msg-card">
          <div className="msg-card__avatar">👤</div>
          <div className="msg-card__name">{content.slice(0, 30) || '名片'}</div>
        </div>
      )

    case MSG_TYPE.VOIP:
      return <>{content || '通话'}</>

    default:
      // 兜底：若 content 是 XML，显示类型名；否则直接显示
      if (content && content.trim().startsWith('<')) {
        return <>{message_type_label(baseType)}</>
      }
      return <>{content || message_type_label(baseType)}</>
  }
}

/** 兜底类型标签。 */
function message_type_label(baseType: number): string {
  const map: Record<number, string> = {
    1: '文本',
    3: '图片',
    34: '语音',
    42: '名片',
    43: '视频',
    47: '表情',
    48: '位置',
    49: '链接/文件',
    50: '通话',
    10000: '系统',
    10002: '撤回',
  }
  return `[${map[baseType] || `类型${baseType}`}]`
}
