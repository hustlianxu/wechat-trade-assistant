import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type {
  DecryptStatusResponse,
  DecryptTriggerResponse,
  SettingsResponse,
} from '../types/api';
import Loading from '../components/Loading';

// 设置页：微信检测 / 解密 / 实时解析 / LLM / 手动密钥 / STT / 数据目录
export default function Settings() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [decrypt, setDecrypt] = useState<DecryptStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState('');

  // LLM 表单
  const [llmBase, setLlmBase] = useState('');
  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState('');
  // 手动密钥
  const [manualKey, setManualKey] = useState('');
  // 实时解析开关
  const [realtime, setRealtime] = useState(false);
  // 重签名密码（macOS）
  const [resignPwd, setResignPwd] = useState('');
  // 解密结果
  const [decryptResult, setDecryptResult] = useState<DecryptTriggerResponse | null>(null);

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(''), 2500);
  };

  // 加载设置与解密状态
  const loadAll = () => {
    setLoading(true);
    Promise.all([api.getSettings(), api.getDecryptStatus()])
      .then(([s, d]) => {
        setSettings(s);
        setDecrypt(d);
        setLlmBase(s.llm_api_base || '');
        setLlmModel(s.llm_model || '');
        setRealtime(s.realtime_listen);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadAll();
  }, []);

  // 保存 LLM 配置
  const handleSaveLLM = () => {
    setBusy(true);
    api
      .setLLM({ api_base: llmBase, api_key: llmKey, model: llmModel, timeout: 30 })
      .then(() => showToast('LLM 配置已保存'))
      .then(() => api.getSettings())
      .then((s) => setSettings(s))
      .catch((e) => showToast('保存失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 清除 LLM 配置
  const handleClearLLM = () => {
    setBusy(true);
    api
      .clearLLM()
      .then(() => showToast('LLM 配置已清除'))
      .then(() => api.getSettings())
      .then((s) => setSettings(s))
      .catch((e) => showToast('清除失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 切换实时解析
  const handleToggleRealtime = () => {
    const next = !realtime;
    setRealtime(next);
    api
      .setRealtime({ enabled: next })
      .then(() => showToast(next ? '已开启实时解析' : '已关闭实时解析'))
      .catch((e) => {
        setRealtime(!next);
        showToast('切换失败：' + e.message);
      });
  };

  // 保存手动密钥
  const handleSaveKey = () => {
    if (!/^[0-9a-fA-F]{64}$/.test(manualKey)) {
      showToast('密钥需为 64 位 hex');
      return;
    }
    setBusy(true);
    api
      .setManualKey({ key_hex: manualKey })
      .then(() => showToast('手动密钥已保存'))
      .catch((e) => showToast('保存失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 触发解密
  const handleDecrypt = () => {
    setBusy(true);
    setDecryptResult(null);
    api
      .triggerDecrypt({ source: 'auto' })
      .then((r) => {
        setDecryptResult(r);
        showToast(r.message || '解密完成');
      })
      .catch((e) => showToast('解密失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // macOS 重签名
  const handleResign = () => {
    setBusy(true);
    api
      .resign({ password: resignPwd || null })
      .then(() => showToast('重签名已完成'))
      .then(() => api.getDecryptStatus())
      .then((d) => setDecrypt(d))
      .catch((e) => showToast('重签名失败：' + e.message))
      .finally(() => setBusy(false));
  };

  if (loading) return <Loading />;
  const isMac = navigator.platform.toLowerCase().includes('mac');

  return (
    <div>
      {/* 微信检测区 */}
      <div className="settings-section">
        <div className="settings-section-title">微信检测</div>
        <div className="settings-row">
          <div className="settings-row-label">版本</div>
          <div className="settings-row-value">
            {settings?.wechat_version || '未检测到'}
            {settings?.wechat_generation ? `（${settings.wechat_generation}）` : ''}
          </div>
        </div>
        <div className="settings-row">
          <div className="settings-row-label">数据目录</div>
          <div className="settings-row-value">
            {(settings?.wechat_data_dirs || []).join('；') || '-'}
          </div>
        </div>
        {settings?.needs_resign && isMac ? (
          <div className="settings-row">
            <div className="settings-row-label">重签名</div>
            <div className="settings-row-value flex gap-8">
              <input
                className="input"
                style={{ flex: 1 }}
                placeholder="macOS 用户密码（可选）"
                type="password"
                value={resignPwd}
                onChange={(e) => setResignPwd(e.target.value)}
              />
              <button className="btn btn-blue" disabled={busy} onClick={handleResign}>
                一键重签名
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {/* 解密区 */}
      <div className="settings-section">
        <div className="settings-section-title">数据解密</div>
        <div className="kv-list">
          <div>需重签名：{decrypt?.needs_resign ? '是' : '否'}</div>
          <div>需管理员：{decrypt?.needs_admin ? '是' : '否'}</div>
          <div>
            上次解密：
            {decrypt?.last_decrypt_run
              ? JSON.stringify(decrypt.last_decrypt_run)
              : '尚未运行'}
          </div>
        </div>
        <div className="settings-row" style={{ marginTop: 10 }}>
          <button className="btn btn-primary" disabled={busy} onClick={handleDecrypt}>
            {busy ? '解密中...' : '开始解密'}
          </button>
        </div>
        {decryptResult ? (
          <div className="kv-list" style={{ marginTop: 8 }}>
            <div>消息数：{decryptResult.msg_count}</div>
            <div>客户数：{decryptResult.contact_count}</div>
          </div>
        ) : null}
      </div>

      {/* 实时解析开关 */}
      <div className="settings-section">
        <div className="settings-section-title">实时解析</div>
        <div className="settings-row">
          <div className="settings-row-label">实时监听</div>
          <div className="settings-row-value flex gap-8">
            <button
              className={`toggle ${realtime ? 'on' : ''}`}
              onClick={handleToggleRealtime}
            />
            <span className="muted text-sm">{realtime ? '已开启' : '已关闭'}</span>
          </div>
        </div>
      </div>

      {/* LLM 配置区 */}
      <div className="settings-section">
        <div className="settings-section-title">
          <span>LLM 配置</span>
          {settings?.llm_api_key_set ? <span className="badge">已配置</span> : null}
        </div>
        <div className="settings-row">
          <div className="settings-row-label">API Base</div>
          <input
            className="input"
            style={{ flex: 1 }}
            value={llmBase}
            placeholder="https://api.example.com/v1"
            onChange={(e) => setLlmBase(e.target.value)}
          />
        </div>
        <div className="settings-row">
          <div className="settings-row-label">API Key</div>
          <input
            className="input"
            style={{ flex: 1 }}
            type="password"
            value={llmKey}
            placeholder="sk-..."
            onChange={(e) => setLlmKey(e.target.value)}
          />
        </div>
        <div className="settings-row">
          <div className="settings-row-label">模型</div>
          <input
            className="input"
            style={{ flex: 1 }}
            value={llmModel}
            placeholder="gpt-4o-mini"
            onChange={(e) => setLlmModel(e.target.value)}
          />
        </div>
        <div className="settings-row">
          <div className="settings-row-label" />
          <div className="flex gap-8">
            <button className="btn btn-primary" disabled={busy} onClick={handleSaveLLM}>
              保存
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={handleClearLLM}>
              清除
            </button>
          </div>
        </div>
      </div>

      {/* 手动密钥区 */}
      <div className="settings-section">
        <div className="settings-section-title">手动密钥</div>
        <div className="settings-row">
          <div className="settings-row-label">64 位 Hex</div>
          <input
            className="input"
            style={{ flex: 1 }}
            value={manualKey}
            placeholder="64 位十六进制密钥"
            onChange={(e) => setManualKey(e.target.value)}
          />
        </div>
        <div className="settings-row">
          <div className="settings-row-label" />
          <button className="btn btn-primary" disabled={busy} onClick={handleSaveKey}>
            保存密钥
          </button>
        </div>
      </div>

      {/* STT 状态区（异步加载，避免阻塞首屏） */}
      <SttSection />

      {/* 数据目录 */}
      <div className="settings-section">
        <div className="settings-section-title">数据目录</div>
        <div className="kv-list">
          <div>数据目录：{settings?.data_dir || '-'}</div>
          <div>数据库：{settings?.db_path || '-'}</div>
        </div>
      </div>

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
}

// STT 状态子区块：独立加载避免影响首屏
function SttSection() {
  const [status, setStatus] = useState<{
    available: boolean;
    whisper_bin: string;
    model_path: string;
    language: string;
  } | null>(null);
  const [err, setErr] = useState('');

  useEffect(() => {
    api
      .getSttStatus()
      .then(setStatus)
      .catch((e) => setErr(String(e.message || e)));
  }, []);

  return (
    <div className="settings-section">
      <div className="settings-section-title">语音转写 STT</div>
      {err ? (
        <div className="kv-list">加载失败：{err}</div>
      ) : !status ? (
        <Loading />
      ) : (
        <div className="kv-list">
          <div>可用：{status.available ? '是' : '否'}</div>
          <div>Whisper 程序：{status.whisper_bin || '-'}</div>
          <div>模型路径：{status.model_path || '-'}</div>
          <div>语言：{status.language || '-'}</div>
        </div>
      )}
    </div>
  );
}
