import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type {
  DecryptStatusResponse,
  DecryptTriggerResponse,
  IncrementalDecryptResponse,
  LLMTestResult,
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
  // 后端不可达错误（loadAll 失败时设置）
  const [loadError, setLoadError] = useState('');

  // LLM 表单
  const [llmBase, setLlmBase] = useState('');
  const [llmKey, setLlmKey] = useState('');
  const [llmModel, setLlmModel] = useState('');
  // 手动密钥（单 key，3.x）
  const [manualKey, setManualKey] = useState('');
  // 多密钥 JSON（4.0.x）
  const [multiKeysJson, setMultiKeysJson] = useState('');
  const [multiKeysSaved, setMultiKeysSaved] = useState(false);
  // 手动数据目录
  const [dataDir, setDataDir] = useState('');
  const [dataDirSaved, setDataDirSaved] = useState(false);
  // 实时解析开关
  const [realtime, setRealtime] = useState(false);
  // 重签名密码（macOS）
  const [resignPwd, setResignPwd] = useState('');
  // 解密结果
  const [decryptResult, setDecryptResult] = useState<DecryptTriggerResponse | null>(null);
  // 增量同步结果
  const [incrementalResult, setIncrementalResult] = useState<IncrementalDecryptResponse | null>(null);
  const [syncing, setSyncing] = useState(false);
  // LLM 测试
  const [testingLLM, setTestingLLM] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<LLMTestResult | null>(null);

  // 后端启动错误（由 preload 从 Electron 主进程传入）
  const backendError = (window.api?.backendError as string) || '';

  const showToast = (msg: string) => {
    setToast(msg);
    window.setTimeout(() => setToast(''), 3500);
  };

  // 加载设置与解密状态
  const loadAll = () => {
    setLoading(true);
    setLoadError('');
    Promise.all([
      api.getSettings(),
      api.getDecryptStatus(),
      api.getManualKeysJson(),
      api.getDataDir(),
    ])
      .then(([s, d, mk, dd]) => {
        setSettings(s);
        setDecrypt(d);
        setLlmBase(s.llm_api_base || '');
        setLlmModel(s.llm_model || '');
        setRealtime(s.realtime_listen);
        if (mk.has_keys && mk.keys_json) {
          setMultiKeysJson(mk.keys_json);
          setMultiKeysSaved(true);
        }
        if (dd.has_dir && dd.data_dir) {
          setDataDir(dd.data_dir);
          setDataDirSaved(true);
        }
      })
      .catch((e) => {
        // 后端不可达：记录错误而非静默吞掉
        const msg = e instanceof Error ? e.message : String(e);
        setLoadError(msg);
      })
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

  // 测试 LLM 连通性（无需先保存，直接用当前表单值测试）
  const handleTestLLM = () => {
    setTestingLLM(true);
    setLlmTestResult(null);
    api
      .testLLM({ api_base: llmBase, api_key: llmKey, model: llmModel, timeout: 30 })
      .then((r) => setLlmTestResult(r))
      .catch((e) =>
        setLlmTestResult({ ok: false, error: e instanceof Error ? e.message : String(e) })
      )
      .finally(() => setTestingLLM(false));
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

  // 保存手动密钥（单 key）
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

  // 保存多密钥 JSON（4.0.x）
  const handleSaveMultiKeys = () => {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(multiKeysJson);
    } catch (e) {
      showToast('JSON 格式错误：' + (e as Error).message);
      return;
    }
    const keys = Object.keys(parsed);
    if (keys.length === 0) {
      showToast('JSON 为空');
      return;
    }
    setBusy(true);
    api
      .setManualKeysJson({ keys_json: multiKeysJson })
      .then(() => {
        setMultiKeysSaved(true);
        showToast(`多密钥 JSON 已保存（${keys.length} 个数据库）`);
      })
      .catch((e) => showToast('保存失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 保存数据目录
  const handleSaveDataDir = () => {
    setBusy(true);
    api
      .setDataDir(dataDir.trim())
      .then(() => {
        setDataDirSaved(true);
        showToast(dataDir.trim() ? '数据目录已保存' : '数据目录已清除');
      })
      .catch((e) => showToast('保存失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 触发解密（如果有多密钥 JSON 则用 multi_keys 模式）
  const handleDecrypt = () => {
    setBusy(true);
    setDecryptResult(null);
    const source = multiKeysJson.trim() ? 'multi_keys' : 'auto';
    const body = source === 'multi_keys'
      ? { source, manual_keys_json: multiKeysJson, data_dir: dataDir.trim() || undefined }
      : { source, data_dir: dataDir.trim() || undefined };
    api
      .triggerDecrypt(body)
      .then((r) => {
        setDecryptResult(r);
        showToast(r.message || '解密完成');
      })
      .catch((e) => showToast('解密失败：' + e.message))
      .finally(() => setBusy(false));
  };

  // 增量同步：仅拉取本地库中最新消息之后的新消息（无需重新解密联系人库）
  const handleIncrementalSync = () => {
    setSyncing(true);
    setIncrementalResult(null);
    api
      .decryptIncremental()
      .then((r) => {
        setIncrementalResult(r);
        showToast(r.message || (r.ok ? '增量同步完成' : '增量同步失败'));
      })
      .catch((e) => {
        setIncrementalResult({
          ok: false,
          message: e instanceof Error ? e.message : String(e),
          new_msg_count: 0,
          data_dir: '',
          db_path: '',
        });
        showToast('增量同步失败：' + (e instanceof Error ? e.message : String(e)));
      })
      .finally(() => setSyncing(false));
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

  // 后端不可达错误（优先显示 Electron 传入的启动错误，其次显示 API 加载错误）
  const fatalErr = backendError || loadError;

  return (
    <div>
      {/* 后端启动/连接错误提示 */}
      {fatalErr ? (
        <div className="settings-section" style={{ borderColor: '#e74c3c' }}>
          <div className="settings-section-title" style={{ color: '#e74c3c' }}>
            {backendError ? '后端启动失败' : '后端连接失败'}
          </div>
          <div className="kv-list" style={{ wordBreak: 'break-all' }}>
            <pre style={{ whiteSpace: 'pre-wrap', fontSize: 12, margin: 0 }}>
              {fatalErr}
            </pre>
          </div>
          <div className="muted text-sm" style={{ marginTop: 6 }}>
            后端不可达时所有 API 调用都会返回 Failed to fetch。请确认：
            <br />
            1. 已安装 Python 3.10+（开发态）或 backend-runtime/wta-backend 存在（打包态）
            <br />
            2. 已执行 pip install -r requirements.txt
            <br />
            3. 端口 8765 未被占用
            <br />
            4. 杀毒软件/防火墙未拦截本地回环
          </div>
        </div>
      ) : null}

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
        <div className="settings-row">
          <div className="settings-row-label">SQLCipher</div>
          <div className="settings-row-value">
            {settings?.sqlcipher_available ? '可用' : '不可用（需安装 pysqlcipher3 或 sqlcipher）'}
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

      {/* 手动数据目录（自动检测失败时用） */}
      <div className="settings-section">
        <div className="settings-section-title">
          <span>微信数据目录（手动指定）</span>
          {dataDirSaved && dataDir ? <span className="badge">已保存</span> : null}
        </div>
        <div className="muted text-sm" style={{ marginBottom: 8 }}>
          自动检测失败时，可手动填写微信数据目录的绝对路径。
          该目录应包含 message/、contact/ 等子目录（含 .db 文件）。
        </div>
        <div className="settings-row">
          <div className="settings-row-label">路径</div>
          <input
            className="input"
            style={{ flex: 1 }}
            value={dataDir}
            placeholder="/Users/xxx/Library/Containers/com.tencent.xinWeChat/Data/.../2.0b4.0.9/<wxid>"
            onChange={(e) => {
              setDataDir(e.target.value);
              setDataDirSaved(false);
            }}
          />
          <button className="btn btn-primary" disabled={busy} onClick={handleSaveDataDir} style={{ marginLeft: 8 }}>
            保存
          </button>
        </div>
      </div>

      {/* 多密钥 JSON 区（4.0.x） */}
      <div className="settings-section">
        <div className="settings-section-title">
          <span>多密钥 JSON（微信 4.0.x）</span>
          {multiKeysSaved ? <span className="badge">已保存</span> : null}
        </div>
        <div className="muted text-sm" style={{ marginBottom: 8 }}>
          从 PyWxDump / wechat-decrypt 等工具导出的多数据库密钥 JSON。
          格式：<code>{'{"message/message_0.db": {"enc_key": "..."}, ...}'}</code>
        </div>
        <textarea
          className="input"
          style={{ width: '100%', minHeight: 120, fontFamily: 'monospace', fontSize: 11 }}
          placeholder={'{\n  "message/message_0.db": {"enc_key": "4fb2..."},\n  "contact/contact.db": {"enc_key": "6498..."}\n}'}
          value={multiKeysJson}
          onChange={(e) => {
            setMultiKeysJson(e.target.value);
            setMultiKeysSaved(false);
          }}
        />
        <div className="settings-row">
          <div className="settings-row-label" />
          <button className="btn btn-primary" disabled={busy} onClick={handleSaveMultiKeys}>
            保存多密钥 JSON
          </button>
        </div>
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
            {busy ? '解密中...' : multiKeysSaved ? '开始解密（多密钥）' : '开始解密'}
          </button>
          <span className="muted text-sm" style={{ marginLeft: 10 }}>
            {multiKeysSaved
              ? '将使用已保存的多密钥 JSON 解密所有数据库'
              : '需先保存多密钥 JSON 或配置手动密钥'}
          </span>
        </div>
        {decryptResult ? (
          <div className="kv-list" style={{ marginTop: 8 }}>
            <div>结果：{decryptResult.message}</div>
            <div>消息数：{decryptResult.msg_count}</div>
            <div>客户数：{decryptResult.contact_count}</div>
            {decryptResult.db_results && decryptResult.db_results.length > 0 ? (
              <details>
                <summary>各数据库明细（{decryptResult.db_results.length} 个）</summary>
                <table style={{ width: '100%', fontSize: 12, marginTop: 6 }}>
                  <thead>
                    <tr>
                      <th>数据库</th>
                      <th>状态</th>
                      <th>消息</th>
                      <th>联系人</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {decryptResult.db_results.map((r, i) => (
                      <tr key={i}>
                        <td>{r.db_path}</td>
                        <td>{r.ok ? '✓' : '✗'}</td>
                        <td>{r.msg_count}</td>
                        <td>{r.contact_count}</td>
                        <td>{r.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            ) : null}
          </div>
        ) : null}
      </div>

      {/* 增量同步：仅拉取本地库中最新消息之后的新消息 */}
      <div className="settings-section">
        <div className="settings-section-title">增量同步</div>
        <div className="muted text-sm" style={{ marginBottom: 8 }}>
          只拉取本地库中已存在消息之后的新消息，不重新解密联系人库。
          适合未开启实时监听时，手动点一下获取最新聊天记录。
        </div>
        <div className="settings-row">
          <button
            className="btn btn-primary"
            disabled={busy || syncing}
            onClick={handleIncrementalSync}
          >
            {syncing ? '同步中...' : '立即增量同步'}
          </button>
        </div>
        {incrementalResult ? (
          <div
            className="kv-list"
            style={{
              marginTop: 8,
              borderColor: incrementalResult.ok ? '#07C160' : '#FA5151',
            }}
          >
            <div>结果：{incrementalResult.message}</div>
            <div>新增消息：{incrementalResult.new_msg_count}</div>
            {incrementalResult.data_dir ? (
              <div className="muted text-sm" style={{ wordBreak: 'break-all' }}>
                数据目录：{incrementalResult.data_dir}
              </div>
            ) : null}
            {incrementalResult.db_path ? (
              <div className="muted text-sm" style={{ wordBreak: 'break-all' }}>
                消息库：{incrementalResult.db_path}
              </div>
            ) : null}
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
            <button className="btn" disabled={busy || testingLLM} onClick={handleTestLLM}>
              {testingLLM ? '测试中...' : '测试连通性'}
            </button>
            <button className="btn btn-danger" disabled={busy} onClick={handleClearLLM}>
              清除
            </button>
          </div>
        </div>
        {llmTestResult ? (
          <div
            className={`llm-test-result ${llmTestResult.ok ? 'llm-test-result-ok' : 'llm-test-result-error'}`}
          >
            {llmTestResult.ok ? (
              <>
                <div className="llm-test-result-title">
                  ✓ 连通成功{llmTestResult.model ? ` · ${llmTestResult.model}` : ''}
                </div>
                {llmTestResult.response ? (
                  <div className="llm-test-result-detail">响应：{llmTestResult.response}</div>
                ) : null}
                {llmTestResult.api_base ? (
                  <div className="llm-test-result-detail">api_base：{llmTestResult.api_base}</div>
                ) : null}
              </>
            ) : (
              <>
                <div className="llm-test-result-title">✗ 测试失败</div>
                {llmTestResult.error ? (
                  <div className="llm-test-result-detail">{llmTestResult.error}</div>
                ) : null}
                {llmTestResult.config_hint ? (
                  <div className="llm-test-result-hint">💡 {llmTestResult.config_hint}</div>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>

      {/* 单密钥区（3.x 或单一 key） */}
      <div className="settings-section">
        <div className="settings-section-title">手动密钥（单 key，3.x 用）</div>
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
