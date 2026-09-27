import { useState, type FormEvent } from 'react';
import { Check, ChevronLeft, LoaderCircle, Plus, Radio } from 'lucide-react';
import type { ModelInfo } from '@atlas/backend-adapter';
import DependencyCheckPanel from './DependencyCheckPanel';
import styles from '../App.module.css';

interface SettingsPageProps {
  username: string;
  onSaveUsername: (username: string) => void;
  apiBaseUrl: string;
  providerBaseUrl: string;
  connected: boolean;
  apiKeyConfigured: boolean;
  busy: boolean;
  connectionTest: { ok: boolean; message: string } | null;
  error: string | null;
  models: ModelInfo[];
  selectedModel: string;
  onBack: () => void;
  onSelectModel: (model: string) => void;
  onSaveProvider: (baseUrl: string, apiKey: string) => Promise<boolean>;
  onAddModel: (model: { id: string; name: string; provider: string; litellm_model: string }) => Promise<boolean>;
  onTestConnection: (model: string) => void;
}

export default function SettingsPage(props: SettingsPageProps) {
  const [baseUrl, setBaseUrl] = useState(props.providerBaseUrl);
  const [apiKey, setApiKey] = useState('');
  const [modelId, setModelId] = useState('');
  const [modelName, setModelName] = useState('');
  const [provider, setProvider] = useState('openai');
  const [litellmModel, setLitellmModel] = useState('');
  const [username, setUsername] = useState(props.username);
  const saveProvider = async (event: FormEvent) => {
    event.preventDefault();
    if (await props.onSaveProvider(baseUrl, apiKey)) setApiKey('');
  };
  const addModel = async (event: FormEvent) => {
    event.preventDefault();
    const added = await props.onAddModel({ id: modelId.trim(), name: modelName.trim() || modelId.trim(), provider: provider.trim(), litellm_model: litellmModel.trim() });
    if (added) { setModelId(''); setModelName(''); setLitellmModel(''); }
  };

  return <section className={styles.settingsPage} aria-label="设置">
    <header className={styles.settingsHeader}><button className={styles.quietButton} onClick={props.onBack}><ChevronLeft size={16} />返回对话</button><div><h1>设置</h1><p>配置模型服务并管理 Atlas 用户偏好。</p></div></header>
    <DependencyCheckPanel apiBaseUrl={props.apiBaseUrl} />
    {props.connected && !props.apiKeyConfigured && <section className={styles.settingsCard} role="status"><h2>首次设置</h2><p>先填写兼容 OpenAI 的 API 地址和密钥并保存，再测试当前模型连接。密钥仅保存在此设备。</p></section>}
    <section className={styles.settingsCard}>
      <h2>用户</h2>
      <form className={styles.settingsForm} onSubmit={(event) => { event.preventDefault(); props.onSaveUsername(username); }}>
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="User" /></label>
        <div className={styles.settingsFormFooter}><span>用户名会保存在此设备的浏览器存储中。</span><button className={styles.settingsAction}>保存用户名</button></div>
      </form>
    </section>
    <section className={styles.settingsCard}>
      <h2>API 提供商</h2>
      <form className={styles.settingsForm} onSubmit={saveProvider}>
        <label>OpenAI 兼容 API 地址<input type="url" required value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
        <label>API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={props.apiKeyConfigured ? '已保存密钥；留空以保持不变' : '输入 API 密钥'} /></label>
        <div className={styles.settingsFormFooter}><span className={styles.settingsStatus}><i className={props.connected ? styles.connectedDot : ''} />{props.connected ? 'Atlas 后端已连接' : 'Atlas 后端未连接'}</span><button className={styles.settingsAction} disabled={props.busy || !props.connected}>保存 API 配置</button></div>
      </form>
      <p>密钥保存在本机 Atlas 用户配置文件中，设置接口不会返回密钥内容。</p>
    </section>
    <section className={styles.settingsCard}>
      <div className={styles.settingsCardHeading}><h2>模型</h2><button className={styles.settingsActionSecondary} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(props.selectedModel)}><Radio size={14} />测试当前模型</button></div>
      <div className={styles.settingsModels}>{props.models.map((model) => <div className={`${styles.settingsModelRow} ${model.id === props.selectedModel ? styles.settingsModelSelected : ''}`} key={model.id}><button onClick={() => props.onSelectModel(model.id)}><span><strong>{model.name ?? model.id}</strong><small>{model.provider ?? model.id} · {model.id}</small></span>{model.id === props.selectedModel && <Check size={17} />}</button><button aria-label={`测试 ${model.name ?? model.id} 连接`} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(model.id)} title="测试模型连接"><Radio size={14} /></button></div>)}{!props.models.length && <p>当前没有可用模型。</p>}</div>
      {props.connectionTest && <p className={props.connectionTest.ok ? styles.settingsSuccess : styles.settingsError} role="status">{props.connectionTest.ok ? '连接成功：' : '连接失败：'}{props.connectionTest.message}</p>}
    </section>
    <section className={styles.settingsCard}>
      <h2>添加自定义模型</h2>
      <form className={styles.settingsForm} onSubmit={addModel}>
        <div className={styles.settingsInputGrid}><label>模型 ID<input required value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="my-model" /></label><label>显示名称<input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="My Model" /></label></div>
        <div className={styles.settingsInputGrid}><label>提供商<input required value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="openai" /></label><label>LiteLLM 模型名<input required value={litellmModel} onChange={(event) => setLitellmModel(event.target.value)} placeholder="openai/model-name" /></label></div>
        <div className={styles.settingsFormFooter}><span>自定义模型会保存在本机 Atlas 用户配置中。</span><button className={styles.settingsAction} disabled={props.busy || !props.connected}><Plus size={14} />添加模型</button></div>
      </form>
    </section>
    {(props.error || props.busy) && <div className={props.error ? styles.settingsError : styles.settingsStatus} role={props.error ? 'alert' : 'status'}>{props.busy && <LoaderCircle size={14} className={styles.settingsSpinner} />}{props.error ?? '正在保存或测试配置…'}</div>}
    <footer className={styles.settingsFooter}>Atlas API：{props.apiBaseUrl} · 提供商：{props.providerBaseUrl}</footer>
  </section>;
}
