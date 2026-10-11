import { useRef, useState, type ChangeEvent } from 'react';
import { api } from '../../services/api';
import styles from '../../App.module.css';

type SettingsDocument = {
  format: 'atlas-settings';
  version: 1;
  exported_at?: string;
  settings: Record<string, unknown>;
};

type ImportChange = {
  key: string;
  before?: unknown;
  before_set: boolean;
  after: unknown;
  changed: boolean;
};

type ImportPreview = {
  preview_hash: string;
  changes: ImportChange[];
  unchanged_fields: string[];
};

type ExportResult = SettingsDocument;

const MAX_IMPORT_BYTES = 128 * 1024;

function downloadJson(name: string, value: unknown) {
  const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  URL.revokeObjectURL(url);
}

function displayValue(value: unknown, isSet = true) {
  return !isSet ? '（未设置）' : JSON.stringify(value);
}

export default function ConfigTransferPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [documentToImport, setDocumentToImport] = useState<unknown>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const exportSettings = async () => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const exported = await api<ExportResult>(apiBaseUrl, '/api/settings/export');
      const date = new Date().toISOString().slice(0, 10).replaceAll('-', '');
      downloadJson(`atlas-settings-${date}.json`, exported);
      setMessage('安全设置已导出。文件只包含 Atlas 支持的非秘密偏好。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const previewFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    setDocumentToImport(null);
    setPreview(null);
    setReviewed(false);
    setError(null);
    setMessage(null);
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) {
      setError('文件超过 128 KiB，无法导入。');
      return;
    }
    setBusy(true);
    try {
      const parsed: unknown = JSON.parse(await file.text());
      const result = await api<ImportPreview>(apiBaseUrl, '/api/settings/import/preview', {
        method: 'POST', json: { document: parsed },
      });
      setDocumentToImport(parsed);
      setPreview(result);
      setMessage('预览已生成。检查每项变更后，勾选确认再应用。');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '文件格式无效');
    } finally {
      setBusy(false);
    }
  };

  const applyImport = async () => {
    if (!preview || documentToImport === null || !reviewed) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const result = await api<{ applied: string[] }>(apiBaseUrl, '/api/settings/import/apply', {
        method: 'POST', json: { document: documentToImport, preview_hash: preview.preview_hash },
      });
      setMessage(result.applied.length ? `已导入：${result.applied.join('、')}` : '设置内容与当前值相同，没有需要应用的更改。');
      setDocumentToImport(null);
      setPreview(null);
      setReviewed(false);
      if (fileRef.current) fileRef.current.value = '';
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="设置导入与导出">
    <div className={styles.settingsCardHeading}><h2>安全设置转移</h2></div>
    <p>导出和导入已知的非秘密偏好。API 密钥、令牌、服务地址、路径、插件安装状态等本机数据不会进入文件。</p>
    <div className="flex flex-wrap items-end gap-3">
      <button className={styles.settingsActionSecondary} type="button" disabled={busy} onClick={() => void exportSettings()}>
        {busy ? '处理中…' : '导出安全设置'}
      </button>
      <label className="min-w-0 flex-1">选择 Atlas 设置文件
        <input ref={fileRef} type="file" accept="application/json,.json" disabled={busy} onChange={(event) => void previewFile(event)} />
      </label>
    </div>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {preview && <div className="mt-3 grid gap-3" aria-live="polite">
      <div>
        <strong>导入预览</strong>
        {preview.changes.length ? <ul>
          {preview.changes.map((change) => <li key={change.key}>
            <code>{change.key}</code>：{displayValue(change.before, change.before_set)} → {displayValue(change.after)}
            {!change.changed && <span className="ml-2 text-fg-3">（无变化）</span>}
          </li>)}
        </ul> : <p>文件中没有可导入的设置。</p>}
        {preview.unchanged_fields.length > 0 && <p>与当前值相同：{preview.unchanged_fields.join('、')}</p>}
      </div>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={reviewed} disabled={busy || preview.changes.length === 0}
          onChange={(event) => setReviewed(event.target.checked)} style={{ width: 16, minHeight: 16 }} />
        我已检查以上预览，确认应用这些更改。
      </label>
      <div><button className={styles.settingsAction} type="button" disabled={busy || !reviewed || preview.changes.length === 0} onClick={() => void applyImport()}>
        {busy ? '正在应用…' : '确认并应用设置'}
      </button></div>
    </div>}
  </section>;
}
