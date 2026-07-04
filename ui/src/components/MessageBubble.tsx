import type { MessageOut } from '../types/api';
import { fileUrl } from '../api/client';
import IntentBadge from './IntentBadge';

interface MessageBubbleProps {
  message: MessageOut;
}

// 时间戳格式化
function fmtTime(ts: number | null): string {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(
    d.getHours()
  )}:${p(d.getMinutes())}`;
}

// 文字/图片/语音三种消息气泡
export default function MessageBubble({ message }: MessageBubbleProps) {
  // direction=send 表示自己发出（靠右绿色），否则靠左
  const isOut = message.direction === 'send' || message.direction === 'out';
  const avatarChar = (message.sender || '?').slice(0, 1).toUpperCase();

  return (
    <div className={`msg-row ${isOut ? 'right' : ''}`}>
      <div className="msg-avatar">{avatarChar}</div>
      <div className="msg-body">
        <div className="msg-sender">{message.sender || (isOut ? '我' : '对方')}</div>
        {renderBubble(message, isOut)}
        <div className="msg-meta">
          <span>{fmtTime(message.created_ts)}</span>
          {message.intent ? <IntentBadge intent={message.intent} confidence={message.confidence} /> : null}
        </div>
      </div>
    </div>
  );
}

// 根据消息类型渲染气泡内容
function renderBubble(message: MessageOut, isOut: boolean) {
  // 自己发出的消息气泡使用微信绿底
  const bubbleCls = `msg-bubble ${isOut ? 'green' : ''}`;

  if (message.msg_type === 'image') {
    // 图片消息：显示缩略图，无缩略图路径时显示占位
    if (message.thumb_path) {
      return (
        <div className="msg-bubble">
          <img
            className="msg-thumb"
            src={fileUrl(message.thumb_path)}
            alt="图片"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = 'none';
            }}
          />
        </div>
      );
    }
    return <div className="msg-bubble">[图片]</div>;
  }

  if (message.msg_type === 'voice') {
    // 语音消息：显示转录文本，未转录时提示
    return (
      <div className="msg-bubble">
        <div className="msg-voice">🎙️ 语音消息</div>
        {message.transcribed ? (
          <div className="msg-voice-transcript">{message.content || '(无转录文本)'}</div>
        ) : (
          <div className="msg-voice-transcript muted-2">未转录</div>
        )}
      </div>
    );
  }

  // 文字及其它类型：默认显示 content
  return <div className={bubbleCls}>{message.content || '(空消息)'}</div>;
}
