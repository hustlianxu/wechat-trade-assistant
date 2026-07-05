import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AppConfig, AutoSetupResult, LLMProvider, WhisperConfig } from '../types'

interface Props {
  /** 当前配置（可能为 null，此时弹窗会拉取）。 */
  config: AppConfig | null
  onClose: () => void
  onSaved: (config: AppConfig) => void
}

/** whisper.cpp 语言选项。 */
const LANGUAGE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: '自动检测' },
  { value: 'es', label: '西班牙语' },
  { value: 'en', label: '英语' },
  { value: 'zh', label: '普通话' },
]

/** 默认配置（用于新增 provider 模板）。 */
function defaultConfig(): AppConfig {
  return {
    decrypted_dir: '',
    wechat_base_dir: '',
    self_wxid: '',
    whisper: { binary_path: '', model_path: '', language: '' },
    llm_providers: [],
    active_llm: '',
  }
}

/** 默认空 provider 模板。 */
function emptyProvider(): LLMProvider {
  return { name: '', api_base: '', api_key: '', model: '', whisper_model: '' }
}

/**
 * 设置弹窗
 * - 解密目录路径
 * - 本账号 wxid
 * - whisper.cpp 配置（binary_path / model_path / language 下拉）
 * - 多 LLM 配置（增删改 + 单选激活）
 * - 保存调用 POST /api/config
 */
export default function Settings({ config, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<AppConfig>(config ?? defaultConfig())
  const [loading, setLoading] = useState<boolean>(!config)
  const [saving, setSaving] = useState<boolean>(false)
  const [error, setError] = useState<string>('')
  const [savedHint, setSavedHint] = useState<string>('')
  const [autoRunning, setAutoRunning] = useState<boolean>(false)
  const [autoResult, setAutoResult] = useState<AutoSetupResult | null>(null)

  // 首次打开若没有传入配置，则拉取
  useEffect(() => {
    if (config) {
      setDraft(config)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    api
      .getConfig()
      .then((c) => {
        if (!cancelled) setDraft(c)
        // 若配置不完整（decrypted_dir 为空或路径无效），自动触发一次检测
        if (!cancelled && (!c.decrypted_dir || c.self_wxid === '')) {
          triggerAutoSetup(false)
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : '加载失败')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [config])

  /** 触发自动检测。 */
  const triggerAutoSetup = async (force: boolean) => {
    setAutoRunning(true)
    setError('')
    setAutoResult(null)
    try {
      const result = await api.autoSetup(force)
      setAutoResult(result)
      // 把检测到的字段合并到 draft（不覆盖用户已填的 LLM 配置）
      setDraft((d) => ({
        ...d,
        decrypted_dir: result.decrypted_dir || d.decrypted_dir,
        wechat_base_dir: result.wechat_base_dir || d.wechat_base_dir,
        self_wxid: result.self_wxid || d.self_wxid,
        whisper: result.whisper?.binary_path ? result.whisper : d.whisper,
      }))
      if (result.needs_manual_action) {
        setError(result.needs_manual_action)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '自动检测失败')
    } finally {
      setAutoRunning(false)
    }
  }

  /** 更新顶层字段。 */
  const updateField = <K extends keyof AppConfig>(key: K, value: AppConfig[K]) => {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  /** 更新 whisper 配置。 */
  const updateWhisper = (patch: Partial<WhisperConfig>) => {
    setDraft((d) => ({ ...d, whisper: { ...d.whisper, ...patch } }))
  }

  /** 新增 provider。 */
  const handleAddProvider = () => {
    setDraft((d) => ({
      ...d,
      llm_providers: [...d.llm_providers, emptyProvider()],
    }))
  }

  /** 删除 provider。 */
  const handleDeleteProvider = (idx: number) => {
    setDraft((d) => {
      const next = d.llm_providers.filter((_, i) => i !== idx)
      const removedName = d.llm_providers[idx]?.name
      return {
        ...d,
        llm_providers: next,
        active_llm: removedName === d.active_llm ? '' : d.active_llm,
      }
    })
  }

  /** 更新某个 provider 字段。 */
  const updateProvider = (idx: number, patch: Partial<LLMProvider>) => {
    setDraft((d) => {
      const next = d.llm_providers.map((p, i) => (i === idx ? { ...p, ...patch } : p))
      // 如果激活项的名字被改了，同步更新 active_llm
      let activeLlm = d.active_llm
      if (idx === d.llm_providers.findIndex((p) => p.name === d.active_llm) && patch.name !== undefined) {
        activeLlm = patch.name
      }
      return { ...d, llm_providers: next, active_llm: activeLlm }
    })
  }

  /** 选中某个 provider 为激活。 */
  const handleSetActive = (name: string) => {
    updateField('active_llm', name)
  }

  /** 保存配置。 */
  const handleSave = async () => {
    setSaving(true)
    setError('')
    setSavedHint('')
    try {
      const saved = await api.saveConfig({
        decrypted_dir: draft.decrypted_dir,
        wechat_base_dir: draft.wechat_base_dir,
        self_wxid: draft.self_wxid,
        whisper: draft.whisper,
        llm_providers: draft.llm_providers,
        active_llm: draft.active_llm,
      })
      setSavedHint('保存成功')
      onSaved(saved)
      setTimeout(() => onClose(), 600)
    } catch (e) {
      setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <div className="modal__title">设置</div>
          <button className="modal__close" onClick={onClose} title="关闭">
            ✕
          </button>
        </div>

        <div className="modal__body">
          {loading && <div className="side-panel__loading">加载中…</div>}
          {error && <div className="side-panel__error">{error}</div>}

          {!loading && (
            <>
              {/* 数据目录配置 */}
              <div className="settings-section">
                <div className="settings-section__title">
                  数据目录
                  <button
                    className="btn btn--primary btn--small"
                    style={{ marginLeft: 'auto' }}
                    onClick={() => triggerAutoSetup(true)}
                    disabled={autoRunning}
                    title="自动检测微信数据目录、自动解密、自动填 wxid"
                  >
                    {autoRunning ? '检测中…' : '🔍 自动检测'}
                  </button>
                </div>

                {/* 自动检测结果 */}
                {autoResult && (
                  <div className="auto-setup-result">
                    {autoResult.messages.map((msg, i) => (
                      <div key={i} className="auto-setup-result__line">
                        {msg}
                      </div>
                    ))}
                    {autoResult.auto_setup_status === 'ok' && (
                      <div className="auto-setup-result__status auto-setup-result__status--ok">
                        ✓ 配置完整，可正常使用
                      </div>
                    )}
                    {autoResult.auto_setup_status === 'partial' && (
                      <div className="auto-setup-result__status auto-setup-result__status--warn">
                        ⚠ 部分配置缺失，可手动补充下方字段
                      </div>
                    )}
                    {autoResult.auto_setup_status === 'failed' && (
                      <div className="auto-setup-result__status auto-setup-result__status--error">
                        ✗ 自动检测失败，请参考下方提示或手动填写
                      </div>
                    )}
                  </div>
                )}

                <div className="settings-field">
                  <label className="settings-field__label">解密目录路径</label>
                  <input
                    type="text"
                    className="settings-field__input"
                    placeholder="自动检测，或手动填写 wechat-decrypt 解密后的 decrypted/ 路径"
                    value={draft.decrypted_dir}
                    onChange={(e) => updateField('decrypted_dir', e.target.value)}
                  />
                  <div className="settings-field__hint">
                    wechat-decrypt 解密后的目录，包含 contact/、session/、message/ 等子目录。点击「自动检测」可自动查找。
                  </div>
                </div>
                <div className="settings-field">
                  <label className="settings-field__label">微信数据根目录（可选）</label>
                  <input
                    type="text"
                    className="settings-field__input"
                    placeholder="xwechat_files 父目录，用于定位语音/图片文件"
                    value={draft.wechat_base_dir}
                    onChange={(e) => updateField('wechat_base_dir', e.target.value)}
                  />
                </div>
                <div className="settings-field">
                  <label className="settings-field__label">本账号 wxid</label>
                  <input
                    type="text"
                    className="settings-field__input"
                    placeholder="wxid_xxx（从目录名提取或手动填写）"
                    value={draft.self_wxid}
                    onChange={(e) => updateField('self_wxid', e.target.value)}
                  />
                  <div className="settings-field__hint">
                    用于识别自己发送的消息
                  </div>
                </div>
              </div>

              {/* whisper.cpp 配置 */}
              <div className="settings-section">
                <div className="settings-section__title">whisper.cpp 配置</div>
                <div className="settings-grid-2">
                  <div className="settings-field">
                    <label className="settings-field__label">binary_path</label>
                    <input
                      type="text"
                      className="settings-field__input"
                      placeholder="/opt/homebrew/bin/whisper-cpp"
                      value={draft.whisper.binary_path}
                      onChange={(e) => updateWhisper({ binary_path: e.target.value })}
                    />
                  </div>
                  <div className="settings-field">
                    <label className="settings-field__label">model_path</label>
                    <input
                      type="text"
                      className="settings-field__input"
                      placeholder="/opt/homebrew/share/whisper-cpp/ggml-base.bin"
                      value={draft.whisper.model_path}
                      onChange={(e) => updateWhisper({ model_path: e.target.value })}
                    />
                  </div>
                </div>
                <div className="settings-field">
                  <label className="settings-field__label">语言</label>
                  <select
                    className="settings-field__select"
                    value={draft.whisper.language}
                    onChange={(e) => updateWhisper({ language: e.target.value })}
                  >
                    {LANGUAGE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                  <div className="settings-field__hint">
                    空为自动检测；西班牙语=es、英语=en、普通话=zh
                  </div>
                </div>
              </div>

              {/* 多 LLM 配置 */}
              <div className="settings-section">
                <div className="settings-section__title">
                  LLM Provider 配置（{draft.llm_providers.length}）
                </div>
                <div className="llm-list">
                  {draft.llm_providers.map((p, idx) => {
                    const isActive = p.name === draft.active_llm && !!p.name
                    return (
                      <div
                        key={idx}
                        className={`llm-item ${isActive ? 'llm-item--active' : ''}`}
                      >
                        <div className="llm-item__header">
                          <div className="llm-item__name-row">
                            <input
                              type="radio"
                              className="llm-item__radio"
                              checked={isActive}
                              onChange={() => handleSetActive(p.name)}
                              disabled={!p.name}
                              title={p.name ? `激活 ${p.name}` : '请先填写名称'}
                            />
                            <span className="llm-item__name">
                              {p.name || `Provider ${idx + 1}`}
                              {isActive && '（当前激活）'}
                            </span>
                          </div>
                          <div className="llm-item__actions">
                            <button
                              className="llm-item__action-btn llm-item__action-btn--danger"
                              onClick={() => handleDeleteProvider(idx)}
                            >
                              删除
                            </button>
                          </div>
                        </div>
                        <div className="llm-item__fields">
                          <input
                            type="text"
                            className="llm-item__field-input"
                            placeholder="name（如 openai）"
                            value={p.name}
                            onChange={(e) => updateProvider(idx, { name: e.target.value })}
                          />
                          <input
                            type="text"
                            className="llm-item__field-input"
                            placeholder="model（如 gpt-4o-mini）"
                            value={p.model}
                            onChange={(e) => updateProvider(idx, { model: e.target.value })}
                          />
                          <input
                            type="text"
                            className="llm-item__field-input"
                            placeholder="api_base（如 https://api.openai.com/v1）"
                            value={p.api_base}
                            onChange={(e) => updateProvider(idx, { api_base: e.target.value })}
                          />
                          <input
                            type="password"
                            className="llm-item__field-input"
                            placeholder="api_key"
                            value={p.api_key}
                            onChange={(e) => updateProvider(idx, { api_key: e.target.value })}
                          />
                          <input
                            type="text"
                            className="llm-item__field-input"
                            placeholder="whisper_model（可选，如 whisper-1）"
                            value={p.whisper_model || ''}
                            onChange={(e) =>
                              updateProvider(idx, { whisper_model: e.target.value })
                            }
                          />
                        </div>
                      </div>
                    )
                  })}
                </div>
                <button className="btn btn--default btn--small" onClick={handleAddProvider}>
                  + 添加 Provider
                </button>
              </div>
            </>
          )}
        </div>

        <div className="modal__footer">
          {savedHint && (
            <span style={{ color: 'var(--color-primary)', marginRight: 'auto', fontSize: 13 }}>
              {savedHint}
            </span>
          )}
          <button className="btn btn--default" onClick={onClose} disabled={saving}>
            取消
          </button>
          <button className="btn btn--primary" onClick={handleSave} disabled={saving || loading}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}
