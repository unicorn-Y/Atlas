import { ChevronLeft, Check } from 'lucide-react';
import type { ModelInfo } from '@atlas/backend-adapter';
import styles from '../App.module.css';

interface SettingsPageProps {
  apiBaseUrl: string;
  connected: boolean;
  models: ModelInfo[];
  selectedModel: string;
  onBack: () => void;
  onSelectModel: (model: string) => void;
}

export default function SettingsPage({ apiBaseUrl, connected, models, selectedModel, onBack, onSelectModel }: SettingsPageProps) {
  return <section className={styles.settingsPage} aria-label="设置">
    <header className={styles.settingsHeader}><button className={styles.quietButton} onClick={onBack}><ChevronLeft size={16} />返回对话</button><div><h1>设置</h1><p>管理 Atlas 的服务连接与模型选择。</p></div></header>
    <section className={styles.settingsCard}>
      <h2>API 连接</h2>
      <label>服务地址<input value={apiBaseUrl} readOnly /></label>
      <p className={styles.settingsStatus}><i className={connected ? styles.connectedDot : ''} />{connected ? '已连接 Atlas 后端' : '后端未连接；配置来源为 VITE_API_BASE_URL'}</p>
    </section>
    <section className={styles.settingsCard}>
      <h2>模型</h2>
      {models.length ? <div className={styles.settingsModels}>{models.map((model) => <button key={model.id} className={model.id === selectedModel ? styles.settingsModelSelected : ''} onClick={() => onSelectModel(model.id)}><span><strong>{model.name ?? model.id}</strong><small>{model.provider ?? model.id}</small></span>{model.id === selectedModel && <Check size={17} />}</button>)}</div> : <p>连接后端后，可在这里选择已配置的模型。</p>}
    </section>
    <section className={styles.settingsCard}>
      <h2>API 与模型配置</h2>
      <p>服务地址和凭据由 Atlas 后端配置管理。此页面提供前端连接状态与模型选择入口。</p>
    </section>
  </section>;
}
