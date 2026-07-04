// 意图标签到展示文案与样式的映射
const INTENT_MAP: Record<string, { label: string; cls: string }> = {
  order: { label: '下单', cls: 'intent-order' },
  quote: { label: '询价', cls: 'intent-quote' },
  info: { label: '咨询', cls: 'intent-info' },
  complaint: { label: '投诉', cls: 'intent-complaint' },
  greeting: { label: '问候', cls: 'intent-greeting' },
  farewell: { label: '告别', cls: 'intent-farewell' },
  confirm: { label: '确认', cls: 'intent-confirm' },
  cancel: { label: '取消', cls: 'intent-cancel' },
  other: { label: '其他', cls: 'intent-other' },
};

interface IntentBadgeProps {
  intent?: string | null;
  confidence?: number;
}

// 意图彩色徽章
export default function IntentBadge({ intent, confidence }: IntentBadgeProps) {
  if (!intent) return <span className="badge">未识别</span>;
  const conf = INTENT_MAP[intent] || { label: intent, cls: 'intent-other' };
  const pct =
    typeof confidence === 'number' && confidence > 0
      ? `${Math.round(confidence * 100)}%`
      : null;
  return (
    <span className={`intent-badge ${conf.cls}`}>
      {conf.label}
      {pct ? ` · ${pct}` : ''}
    </span>
  );
}
