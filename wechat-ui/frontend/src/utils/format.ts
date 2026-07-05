// 工具函数：时间格式化、字母头像等共享逻辑

/** 把秒级时间戳格式化为 YYYY-MM-DD HH:mm。 */
export function formatTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 联系人列表时间显示：今天只显示 HH:mm，昨天显示「昨天 HH:mm」，更早显示 MM-DD。 */
export function formatShortTime(ts: number): string {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (sameDay) {
    return `${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  // 昨天
  const y = new Date(now)
  y.setDate(now.getDate() - 1)
  const isYesterday =
    d.getFullYear() === y.getFullYear() &&
    d.getMonth() === y.getMonth() &&
    d.getDate() === y.getDate()
  if (isYesterday) {
    return `昨天 ${pad(d.getHours())}:${pad(d.getMinutes())}`
  }
  // 同年
  if (d.getFullYear() === now.getFullYear()) {
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  }
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 把日期字符串（YYYY-MM-DD）转为秒级时间戳；空串返回 0。 */
export function dateToTs(dateStr: string, endOfDay = false): number {
  if (!dateStr) return 0
  const [y, m, d] = dateStr.split('-').map(Number)
  if (!y || !m || !d) return 0
  const date = new Date(y, m - 1, d, endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0)
  return Math.floor(date.getTime() / 1000)
}

/** 取显示名首字符（用于头像占位符）。 */
export function avatarChar(name: string): string {
  if (!name) return '?'
  const trimmed = name.trim()
  if (!trimmed) return '?'
  return Array.from(trimmed)[0]?.toUpperCase() || '?'
}

/** 消息摘要，截断到指定长度。 */
export function truncate(text: string, max = 30): string {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '…' : text
}

/** 判断两条消息是否需要时间分隔线（间隔超过 5 分钟）。 */
export function shouldShowTimeDivider(prevTs: number, curTs: number): boolean {
  if (!prevTs) return true
  return curTs - prevTs > 5 * 60
}

/** 在文本中高亮关键词（返回带 span 的 React 片段所需字符串数组）。 */
export function highlightKeyword(text: string, keyword: string): Array<{ text: string; hit: boolean }> {
  if (!keyword || !text) return [{ text, hit: false }]
  const lower = text.toLowerCase()
  const kw = keyword.toLowerCase()
  const parts: Array<{ text: string; hit: boolean }> = []
  let idx = 0
  while (idx < text.length) {
    const pos = lower.indexOf(kw, idx)
    if (pos === -1) {
      parts.push({ text: text.slice(idx), hit: false })
      break
    }
    if (pos > idx) {
      parts.push({ text: text.slice(idx, pos), hit: false })
    }
    parts.push({ text: text.slice(pos, pos + kw.length), hit: true })
    idx = pos + kw.length
  }
  return parts
}
