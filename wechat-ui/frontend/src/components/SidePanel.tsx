import { useCallback, useState } from 'react'
import { api } from '../api/client'
import type { AppConfig, IntentResult, SummaryResult, TodoResult } from '../types'
import { dateToTs } from '../utils/format'

interface Props {
  username: string
  startTs: number
  endTs: number
  onTimeRangeChange: (start: number, end: number) => void
  config: AppConfig | null
}

/**
 * 右栏：功能面板
 * - 时间选择器：选择日期范围，过滤中栏消息（同时也作为分析的时间范围）
 * - 意图识别按钮：调用 /api/analyze/intent/{username}
 * - 待办提取按钮：调用 /api/analyze/todos/{username}
 * - 会话总结按钮：调用 /api/analyze/summary/{username}
 * 三个分析按钮都基于当前时间范围
 */
export default function SidePanel({
  username,
  startTs,
  endTs,
  onTimeRangeChange,
  config,
}: Props) {
  // 日期输入值（YYYY-MM-DD 字符串）
  const [startDate, setStartDate] = useState<string>('')
  const [endDate, setEndDate] = useState<string>('')

  // 三个分析的状态
  const [intentLoading, setIntentLoading] = useState(false)
  const [intentData, setIntentData] = useState<IntentResult | null>(null)
  const [intentError, setIntentError] = useState('')

  const [todosLoading, setTodosLoading] = useState(false)
  const [todosData, setTodosData] = useState<TodoResult | null>(null)
  const [todosError, setTodosError] = useState('')

  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryData, setSummaryData] = useState<SummaryResult | null>(null)
  const [summaryError, setSummaryError] = useState('')

  /** 当前分析参数。 */
  const analyzeParams = useCallback(
    (limit: number) => ({
      start_ts: startTs || 0,
      end_ts: endTs || 0,
      limit,
    }),
    [startTs, endTs],
  )

  /** 重置所有分析结果。 */
  const resetAnalyze = useCallback(() => {
    setIntentData(null)
    setIntentError('')
    setTodosData(null)
    setTodosError('')
    setSummaryData(null)
    setSummaryError('')
  }, [])

  /** 应用时间范围。 */
  const handleApplyTimeRange = useCallback(() => {
    const s = dateToTs(startDate, false)
    const e = dateToTs(endDate, true)
    onTimeRangeChange(s, e)
    resetAnalyze()
  }, [startDate, endDate, onTimeRangeChange, resetAnalyze])

  /** 清除时间过滤。 */
  const handleClearTimeRange = useCallback(() => {
    setStartDate('')
    setEndDate('')
    onTimeRangeChange(0, 0)
    resetAnalyze()
  }, [onTimeRangeChange, resetAnalyze])

  /** 意图识别。 */
  const handleAnalyzeIntent = useCallback(async () => {
    if (!username) return
    setIntentLoading(true)
    setIntentError('')
    setIntentData(null)
    try {
      const result = await api.analyzeIntent(username, analyzeParams(100))
      setIntentData(result)
    } catch (e) {
      setIntentError(e instanceof Error ? e.message : '分析失败')
    } finally {
      setIntentLoading(false)
    }
  }, [username, analyzeParams])

  /** 待办提取。 */
  const handleAnalyzeTodos = useCallback(async () => {
    if (!username) return
    setTodosLoading(true)
    setTodosError('')
    setTodosData(null)
    try {
      const result = await api.analyzeTodos(username, analyzeParams(100))
      setTodosData(result)
    } catch (e) {
      setTodosError(e instanceof Error ? e.message : '分析失败')
    } finally {
      setTodosLoading(false)
    }
  }, [username, analyzeParams])

  /** 会话总结。 */
  const handleAnalyzeSummary = useCallback(async () => {
    if (!username) return
    setSummaryLoading(true)
    setSummaryError('')
    setSummaryData(null)
    try {
      const result = await api.analyzeSummary(username, analyzeParams(200))
      setSummaryData(result)
    } catch (e) {
      setSummaryError(e instanceof Error ? e.message : '分析失败')
    } finally {
      setSummaryLoading(false)
    }
  }, [username, analyzeParams])

  const noUsername = !username
  const timeRangeActive = startTs > 0 || endTs > 0
  const llmReady = !!config?.active_llm

  return (
    <div className="side-panel">
      <div className="side-panel__body">
        {/* 时间选择器 */}
        <div className="side-panel__section">
          <div className="side-panel__section-title">时间范围</div>
          <div className="side-panel__row">
            <label className="side-panel__label">开始日期</label>
            <input
              type="date"
              className="side-panel__input"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
          </div>
          <div className="side-panel__row">
            <label className="side-panel__label">结束日期</label>
            <input
              type="date"
              className="side-panel__input"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
          <button
            className="side-panel__btn"
            onClick={handleApplyTimeRange}
            disabled={noUsername}
          >
            应用时间过滤
          </button>
          {timeRangeActive && (
            <button
              className="side-panel__btn side-panel__btn--secondary"
              onClick={handleClearTimeRange}
              style={{ marginTop: 6 }}
            >
              清除过滤
            </button>
          )}
          <div className="side-panel__label" style={{ marginTop: 6 }}>
            {timeRangeActive
              ? `已过滤：${startTs ? new Date(startTs * 1000).toLocaleDateString('zh-CN') : '不限'} ~ ${endTs ? new Date(endTs * 1000).toLocaleDateString('zh-CN') : '不限'}`
              : '默认显示全部消息'}
          </div>
        </div>

        {/* 意图识别 */}
        <div className="side-panel__section">
          <div className="side-panel__section-title">意图识别</div>
          <button
            className="side-panel__btn"
            onClick={handleAnalyzeIntent}
            disabled={noUsername || intentLoading}
          >
            {intentLoading ? '分析中…' : '识别会话意图'}
          </button>
          {intentError && <div className="side-panel__error">{intentError}</div>}
          {intentData && (
            <div className="side-panel__result">
              <div>
                <span className="intent-result__label">{intentData.intent}</span>
                <span className="intent-result__confidence">
                  置信度 {(intentData.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div className="intent-result__summary">{intentData.summary}</div>
            </div>
          )}
        </div>

        {/* 待办提取 */}
        <div className="side-panel__section">
          <div className="side-panel__section-title">待办提取</div>
          <button
            className="side-panel__btn"
            onClick={handleAnalyzeTodos}
            disabled={noUsername || todosLoading}
          >
            {todosLoading ? '提取中…' : '提取待办事项'}
          </button>
          {todosError && <div className="side-panel__error">{todosError}</div>}
          {todosData && (
            <div className="side-panel__result">
              {todosData.error && <div className="side-panel__error">{todosData.error}</div>}
              {todosData.todos.length === 0 && !todosData.error && (
                <div className="side-panel__empty">无待办事项</div>
              )}
              {todosData.todos.map((t, i) => (
                <div key={i} className="todo-item">
                  <div className="todo-item__header">
                    <span className="todo-item__title">{t.title}</span>
                    {t.priority && (
                      <span className={`todo-item__priority todo-item__priority--${t.priority}`}>
                        {t.priority}
                      </span>
                    )}
                  </div>
                  {t.detail && <div className="todo-item__detail">{t.detail}</div>}
                  <div className="todo-item__meta">
                    {t.assignee && <span>负责人：{t.assignee}</span>}
                    {t.due && <span>截止：{t.due}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 会话总结 */}
        <div className="side-panel__section">
          <div className="side-panel__section-title">会话总结</div>
          <button
            className="side-panel__btn"
            onClick={handleAnalyzeSummary}
            disabled={noUsername || summaryLoading}
          >
            {summaryLoading ? '生成中…' : '生成会话总结'}
          </button>
          {summaryError && <div className="side-panel__error">{summaryError}</div>}
          {summaryData && (
            <div className="side-panel__result" style={{ whiteSpace: 'pre-wrap' }}>
              {summaryData.summary}
            </div>
          )}
        </div>

        {/* LLM 状态提示 */}
        <div className="side-panel__section">
          <div className="side-panel__section-title">LLM 状态</div>
          <div className="side-panel__label">
            {llmReady
              ? `当前 LLM：${config?.active_llm}`
              : '未激活 LLM，意图/待办/总结将退回规则兜底（仅意图有兜底，待办/总结需配置 LLM）'}
          </div>
        </div>
      </div>
    </div>
  )
}
