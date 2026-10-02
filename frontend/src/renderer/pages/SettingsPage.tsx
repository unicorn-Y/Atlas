import { useState, type FormEvent } from 'react';
import { Check, ChevronLeft, LoaderCircle, Plus, Radio } from 'lucide-react';
import type { CustomModelRequest, ModelInfo } from '@atlas/backend-adapter';
import DependencyCheckPanel from './DependencyCheckPanel';
import IntegrationPanel from './IntegrationPanel';
import styles from '../App.module.css';

export const STATUS_BAR_ITEMS = [
  ['model', '模型'], ['reasoning', '推理强度'], ['context', '上下文占用'], ['tokens', 'Token 用量'],
  ['cost', '费用估算'], ['git', 'Git 分支'], ['permission', '权限模式'], ['processes', '后台进程'],
] as const;
export type StatusBarPreferences = Record<(typeof STATUS_BAR_ITEMS)[number][0], boolean>;

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
  subagentsEnabled: boolean;
  subagentDefaultModel: string;
  onBack: () => void;
  onSelectModel: (model: string) => void;
  onSaveSubagentSettings: (enabled: boolean, defaultModel: string) => Promise<boolean>;
  onSaveProvider: (baseUrl: string, apiKey: string) => Promise<boolean>;
  onAddModel: (model: CustomModelRequest) => Promise<boolean>;
  onTestConnection: (model: string) => void;
  statusBar: StatusBarPreferences;
  onStatusBarChange: (key: keyof StatusBarPreferences, visible: boolean) => void;
}

export default function SettingsPage(props: SettingsPageProps) {
  const [baseUrl, setBaseUrl] = useState(props.providerBaseUrl);
  const [apiKey, setApiKey] = useState('');
  const [modelId, setModelId] = useState('');
  const [modelName, setModelName] = useState('');
  const [provider, setProvider] = useState('openai');
  const [litellmModel, setLitellmModel] = useState('');
  const [maxOutput, setMaxOutput] = useState('');
  const [price, setPrice] = useState({ input: '', output: '', cached_input: '' });
  const [username, setUsername] = useState(props.username);
  const saveProvider = async (event: FormEvent) => {
    event.preventDefault();
    if (await props.onSaveProvider(baseUrl, apiKey)) setApiKey('');
  };
  const addModel = async (event: FormEvent) => {
    event.preventDefault();
    const number = (value: string) => value.trim() === '' || Number.isNaN(Number(value)) ? undefined : Number(value);
    const prices = Object.fromEntries(Object.entries(price).map(([key, value]) => [key, number(value)]).filter(([, value]) => value !== undefined));
    const added = await props.onAddModel({
      id: modelId.trim(), name: modelName.trim() || modelId.trim(), provider: provider.trim(), litellm_model: litellmModel.trim(),
      ...(number(maxOutput) ? { max_output_tokens: number(maxOutput) } : {}),
      ...(Object.keys(prices).length ? { price: prices } : {}),
    });
    if (added) { setModelId(''); setModelName(''); setLitellmModel(''); setMaxOutput(''); setPrice({ input: '', output: '', cached_input: '' }); }
  };

  return <section className={styles.settingsPage} aria-label="设置">
    <header className={styles.settingsHeader}><button className={styles.quietButton} onClick={props.onBack}><ChevronLeft size={16} />返回对话</button><div><h1>模型与服务</h1><p>连接模型服务、选择 Atlas 用哪个模型，并查看它能用的能力。</p></div></header>
    {props.connected && !props.apiKeyConfigured && <section className={styles.settingsCard} role="status"><h2>首次设置</h2><p>先填写兼容 OpenAI 的 API 地址和密钥并保存，再测试当前模型连接。密钥仅保存在此设备。</p></section>}
    <section className={styles.settingsCard}>
      <h2>用户</h2>
      <form className={styles.settingsForm} onSubmit={(event) => { event.preventDefault(); props.onSaveUsername(username); }}>
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="User" /></label>
        <div className={styles.settingsFormFooter}><span>用户名会保存在此设备的浏览器存储中。</span><button className={styles.settingsAction}>保存用户名</button></div>
      </form>
    </section>
    <section className={styles.settingsCard}>
      <h2>状态栏</h2>
      <p>选择对话底部显示的状态信息。新安装时默认全部显示。</p>
      <div className={styles.settingsForm}>
        {STATUS_BAR_ITEMS.map(([key, label]) => <label key={key} className="flex items-center gap-2">
          <input type="checkbox" checked={props.statusBar[key]} onChange={(event) => props.onStatusBarChange(key, event.target.checked)} />{label}
        </label>)}
      </div>
    </section>
    <section className={styles.settingsCard}>
      <h2>子 Agent</h2>
      <p>设置只会用于之后新建的子 Agent。</p>
      <div className={styles.settingsForm}>
        <label className="flex items-center gap-2"><input type="checkbox" checked={props.subagentsEnabled} disabled={props.busy || !props.connected} onChange={(event) => void props.onSaveSubagentSettings(event.target.checked, props.subagentDefaultModel || props.selectedModel)} />启用子 Agent</label>
        <label>默认模型
          <select aria-label="默认子 Agent 模型" value={props.subagentDefaultModel || props.selectedModel} disabled={!props.subagentsEnabled || props.busy || !props.connected || !props.models.length} onChange={(event) => void props.onSaveSubagentSettings(props.subagentsEnabled, event.target.value)}>
            {props.models.map((model) => <option key={model.id} value={model.id}>{model.name ?? model.id}</option>)}
          </select>
        </label>
      </div>
    </section>
    <section className={styles.settingsCard}>
      <h2>API 提供商</h2>
      <form className={styles.settingsForm} onSubmit={saveProvider}>
        <label>OpenAI 兼容 API 地址<input type="url" required value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
        <p style={{ margin: '-4px 0 0', fontSize: 12, color: 'var(--ink3)' }}>本机模型：<button type="button" className="linklike" onClick={() => setBaseUrl('http://127.0.0.1:11434/v1')} style={{ color: 'var(--brand)', background: 'none', border: 0, padding: 0, cursor: 'pointer' }}>Ollama</button>
          {' · '}<button type="button" onClick={() => setBaseUrl('http://127.0.0.1:1234/v1')} style={{ color: 'var(--brand)', background: 'none', border: 0, padding: 0, cursor: 'pointer' }}>LM Studio</button>，本机模型不需要密钥，随便填一个即可。</p>
        <label>API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={props.apiKeyConfigured ? '已保存密钥；留空以保持不变' : '输入 API 密钥'} /></label>
        <div className={styles.settingsFormFooter}><span className={styles.settingsStatus}><i className={props.connected ? styles.connectedDot : ''} />{props.connected ? 'Atlas 后端已连接' : 'Atlas 后端未连接'}</span><button className={styles.settingsAction} disabled={props.busy || !props.connected}>保存 API 配置</button></div>
      </form>
      <p>密钥保存在本机 Atlas 用户配置文件中，设置接口不会返回密钥内容。</p>
    </section>
    <section className={styles.settingsCard}>
      <div className={styles.settingsCardHeading}><h2>模型</h2><button className={styles.settingsActionSecondary} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(props.selectedModel)}><Radio size={14} />测试当前模型</button></div>
      <div className={styles.settingsModels}>{props.models.map((model) => <div className={`${styles.settingsModelRow} ${model.id === props.selectedModel ? styles.settingsModelSelected : ''}`} key={model.id}><button onClick={() => props.onSelectModel(model.id)}><span><strong>{model.name ?? model.id}</strong><small>{model.provider ? `${model.provider}，${model.id}` : model.id}</small></span>{model.id === props.selectedModel && <Check size={17} />}</button><button aria-label={`测试 ${model.name ?? model.id} 连接`} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(model.id)} title="测试模型连接"><Radio size={14} /></button></div>)}{!props.models.length && <p>当前没有可用模型。</p>}</div>
      {props.connectionTest && <p className={props.connectionTest.ok ? styles.settingsSuccess : styles.settingsError} role="status">{props.connectionTest.ok ? '连接成功：' : '连接失败：'}{props.connectionTest.message}</p>}
    </section>
    <section className={styles.settingsCard}>
      <h2>添加自定义模型</h2>
      <form className={styles.settingsForm} onSubmit={addModel}>
        <div className={styles.settingsInputGrid}><label>模型 ID<input required value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="my-model" /></label><label>显示名称<input value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="My Model" /></label></div>
        <div className={styles.settingsInputGrid}><label>提供商<input required value={provider} onChange={(event) => setProvider(event.target.value)} placeholder="openai" /></label><label>LiteLLM 模型名<input required value={litellmModel} onChange={(event) => setLitellmModel(event.target.value)} placeholder="openai/model-name" /></label></div>
        <div className={styles.settingsInputGrid}><label>最长输出（token，可不填，默认 16384）<input inputMode="numeric" value={maxOutput} onChange={(event) => setMaxOutput(event.target.value)} placeholder="16384" /></label><span /></div>
        <div className={styles.settingsInputGrid} style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
          <label>输入价格（每百万 token）<input inputMode="decimal" value={price.input} onChange={(event) => setPrice({ ...price, input: event.target.value })} placeholder="可不填" /></label>
          <label>输出价格<input inputMode="decimal" value={price.output} onChange={(event) => setPrice({ ...price, output: event.target.value })} placeholder="可不填" /></label>
          <label>缓存命中价格<input inputMode="decimal" value={price.cached_input} onChange={(event) => setPrice({ ...price, cached_input: event.target.value })} placeholder="可不填" /></label>
        </div>
        <div className={styles.settingsFormFooter}><span>自定义模型会保存在本机 Atlas 用户配置中。填了价格，「用量」页才能估算费用。</span><button className={styles.settingsAction} disabled={props.busy || !props.connected}><Plus size={14} />添加模型</button></div>
      </form>
    </section>
    <IntegrationPanel apiBaseUrl={props.apiBaseUrl} />
    <DependencyCheckPanel apiBaseUrl={props.apiBaseUrl} />
    {(props.error || props.busy) && <div className={props.error ? styles.settingsError : styles.settingsStatus} role={props.error ? 'alert' : 'status'}>{props.busy && <LoaderCircle size={14} className={styles.settingsSpinner} />}{props.error ?? '正在保存或测试配置…'}</div>}
    <footer className={styles.settingsFooter}>Atlas 后端 {props.apiBaseUrl}　模型服务 {props.providerBaseUrl}</footer>
  </section>;
}
