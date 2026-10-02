import { useEffect, useState, type FormEvent } from 'react';
import { Check, ChevronLeft, LoaderCircle, Pencil, Radio, Trash2, X } from 'lucide-react';
import type { CustomModelRequest, CustomModelUpdateRequest, ModelInfo, ProviderState, ReasoningStagesConfig } from '@atlas/backend-adapter';
import DependencyCheckPanel from './DependencyCheckPanel';
import IntegrationPanel from './IntegrationPanel';
import KeyManager from './models/KeyManager';
import ModelForm, { buildCreateRequest, buildUpdatePatch, type ModelFormValues } from './models/ModelForm';
import ProviderGrid from './models/ProviderGrid';
import ReasoningStages from './models/ReasoningStages';
import { cn } from '../ui/cn';
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
  /** Catalog of supported model services with this installation's keys and endpoints. */
  providers: ProviderState[];
  reasoningStages: ReasoningStagesConfig;
  onBack: () => void;
  onSelectModel: (model: string) => void;
  onSaveProvider: (baseUrl: string, apiKey: string) => Promise<boolean>;
  onAddModel: (model: CustomModelRequest) => Promise<boolean>;
  onTestConnection: (model: string) => void;
  onLoadProviders: () => void;
  onSaveProviderConfig: (providerId: string, baseUrl: string | null) => Promise<boolean>;
  onAddProviderKey: (providerId: string, secret: string, label: string) => Promise<boolean>;
  onRemoveProviderKey: (providerId: string, keyId: string) => void;
  onUpdateModel: (modelId: string, patch: CustomModelUpdateRequest) => Promise<boolean>;
  onDeleteModel: (modelId: string) => Promise<boolean>;
  onSaveReasoningStages: (config: ReasoningStagesConfig) => void;
}

export default function SettingsPage(props: SettingsPageProps) {
  const [baseUrl, setBaseUrl] = useState(props.providerBaseUrl);
  const [apiKey, setApiKey] = useState('');
  const [username, setUsername] = useState(props.username);
  const [selectedProviderId, setSelectedProviderId] = useState('');
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [deletingModelId, setDeletingModelId] = useState<string | null>(null);

  useEffect(() => { props.onLoadProviders(); }, []);

  const provider = props.providers.find((item) => item.id === selectedProviderId) ?? null;
  // Nothing picked yet (or the list just arrived): start on the first configured provider.
  useEffect(() => {
    if (!provider && props.providers.length) {
      const preferred = props.providers.find((item) => item.configured) ?? props.providers[0];
      setSelectedProviderId(preferred.id);
    }
  }, [provider, props.providers]);

  // The model entry this provider already has, if any; legacy gateway models (no hermes_provider) never match.
  const providerModel = provider
    ? props.models.find((model) => Boolean(model.hermes_provider) && (model.provider === provider.id || model.hermes_provider === provider.hermes_provider)) ?? null
    : null;
  const editingModel = editingModelId ? props.models.find((model) => model.id === editingModelId) ?? null : null;

  const saveProvider = async (event: FormEvent) => {
    event.preventDefault();
    if (await props.onSaveProvider(baseUrl, apiKey)) setApiKey('');
  };

  /** Provider form: saves the provider base URL, then creates or updates its model entry. */
  const submitProviderForm = async (values: ModelFormValues) => {
    if (!provider) return false;
    const desired = values.providerBaseUrl.trim();
    const current = provider.base_url ?? provider.default_base_url;
    if (desired !== current) {
      const next = !desired || desired === provider.default_base_url ? null : desired;
      if (!await props.onSaveProviderConfig(provider.id, next)) return false;
    }
    if (providerModel) return props.onUpdateModel(providerModel.id, buildUpdatePatch(providerModel, values, false));
    return props.onAddModel(buildCreateRequest(provider, values));
  };

  const saveEdit = async (values: ModelFormValues) => {
    if (!editingModel) return false;
    if (await props.onUpdateModel(editingModel.id, buildUpdatePatch(editingModel, values, true))) {
      setEditingModelId(null);
      return true;
    }
    return false;
  };

  /** Two-step delete: first click arms the button, second click removes the model. */
  const removeModel = (model: ModelInfo) => {
    if (deletingModelId !== model.id) { setDeletingModelId(model.id); return; }
    setDeletingModelId(null);
    void props.onDeleteModel(model.id);
  };

  const rowButton = 'grid w-9 place-items-center self-stretch rounded-[11px] bg-sunken text-fg-3 shadow-[inset_0_0_0_1px_var(--line)] hover:bg-hover hover:text-fg';

  return <section className={styles.settingsPage} aria-label="设置">
    <header className={styles.settingsHeader}><button className={styles.quietButton} onClick={props.onBack}><ChevronLeft size={16} />返回对话</button><div><h1>模型与服务</h1><p>选择一家服务商，填好它的接口地址和密钥，再告诉 Atlas 用哪个模型。</p></div></header>
    {props.connected && !props.apiKeyConfigured && <section className={styles.settingsCard} role="status"><h2>首次设置</h2><p>在下面的服务商网格里选一家、填入密钥并保存，再测试当前模型连接。密钥仅保存在此设备。</p></section>}

    <section className={styles.settingsCard}>
      <h2>服务商</h2>
      <ProviderGrid providers={props.providers} selectedId={provider?.id ?? ''} onSelect={(id) => { setSelectedProviderId(id); setDeletingModelId(null); setEditingModelId(null); }} />
    </section>

    {provider && <section className={styles.settingsCard}>
      <div className={styles.settingsCardHeading}>
        <h2>{provider.label} · 接口与模型</h2>
        {provider.docs_url && <a className={styles.settingsActionSecondary} href={provider.docs_url} target="_blank" rel="noreferrer">官方文档</a>}
      </div>
      <ModelForm key={`provider-${provider.id}-${providerModel?.id ?? 'new'}`} provider={provider} model={providerModel}
        busy={props.busy} disabled={!props.connected}
        submitLabel={providerModel ? '保存这家服务商的模型' : '添加这家服务商的模型'}
        onSubmit={submitProviderForm} />
      <div className="mt-4 border-t border-line pt-4">
        <KeyManager keys={provider.keys} busy={props.busy} disabled={!props.connected}
          onAdd={(secret, label) => props.onAddProviderKey(provider.id, secret, label)}
          onRemove={(keyId) => props.onRemoveProviderKey(provider.id, keyId)} />
      </div>
      {provider.notes && <p className="mt-3">{provider.notes}</p>}
    </section>}

    <section className={styles.settingsCard}>
      <h2>用户</h2>
      <form className={styles.settingsForm} onSubmit={(event) => { event.preventDefault(); props.onSaveUsername(username); }}>
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="User" /></label>
        <div className={styles.settingsFormFooter}><span>用户名会保存在此设备的浏览器存储中。</span><button className={styles.settingsAction}>保存用户名</button></div>
      </form>
    </section>
    <section className={styles.settingsCard}>
      <h2>Atlas 网关</h2>
      <form className={styles.settingsForm} onSubmit={saveProvider}>
        <label>OpenAI 兼容 API 地址<input type="url" required value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" /></label>
        <p style={{ margin: '-4px 0 0', fontSize: 12, color: 'var(--ink3)' }}>本机模型：<button type="button" className="linklike" onClick={() => setBaseUrl('http://127.0.0.1:11434/v1')} style={{ color: 'var(--brand)', background: 'none', border: 0, padding: 0, cursor: 'pointer' }}>Ollama</button>
          {' · '}<button type="button" onClick={() => setBaseUrl('http://127.0.0.1:1234/v1')} style={{ color: 'var(--brand)', background: 'none', border: 0, padding: 0, cursor: 'pointer' }}>LM Studio</button>，本机模型不需要密钥，随便填一个即可。</p>
        <label>API 密钥<input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={props.apiKeyConfigured ? '已保存密钥；留空以保持不变' : '输入 API 密钥'} /></label>
        <div className={styles.settingsFormFooter}><span className={styles.settingsStatus}><i className={props.connected ? styles.connectedDot : ''} />{props.connected ? 'Atlas 后端已连接' : 'Atlas 后端未连接'}</span><button className={styles.settingsAction} disabled={props.busy || !props.connected}>保存 API 配置</button></div>
      </form>
      <p>网关是上面服务商之外的备用通道：没在服务商网格里配置密钥的模型，会走这里填的地址和密钥。密钥保存在本机 Atlas 用户配置文件中，设置接口不会返回密钥内容。</p>
    </section>
    <section className={styles.settingsCard}>
      <div className={styles.settingsCardHeading}><h2>模型</h2><button className={styles.settingsActionSecondary} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(props.selectedModel)}><Radio size={14} />测试当前模型</button></div>
      <div className={styles.settingsModels}>{props.models.map((model) => {
        const selected = model.id === props.selectedModel;
        return <div className={`${styles.settingsModelRow} ${selected ? styles.settingsModelSelected : ''}`} key={model.id}>
          <button onClick={() => props.onSelectModel(model.id)}><span><strong>{model.name ?? model.id}</strong><small>{model.provider ? `${model.provider}，${model.id}` : model.id}</small></span>{selected && <Check size={17} />}</button>
          <div className="flex items-stretch gap-1.5">
            <button type="button" className={rowButton} aria-label={`测试 ${model.name ?? model.id} 连接`} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(model.id)} title="测试模型连接"><Radio size={14} /></button>
            <button type="button" className={rowButton} aria-label={`编辑 ${model.name ?? model.id}`} disabled={!props.connected} onClick={() => { setEditingModelId(model.id); setDeletingModelId(null); }} title="编辑模型"><Pencil size={14} /></button>
            <button type="button" className={cn(rowButton, deletingModelId === model.id && 'bg-danger-soft text-danger hover:bg-danger-soft hover:text-danger')} aria-label={`删除 ${model.name ?? model.id}`} disabled={props.busy || !props.connected} onClick={() => removeModel(model)} title="删除模型（再点一次确认）"><Trash2 size={14} /></button>
          </div>
        </div>;
      })}{!props.models.length && <p>当前没有可用模型。</p>}</div>
      {deletingModelId && <p role="status" className="m-0 text-[12.5px] text-danger">再点一次「删除」确认删除。{deletingModelId === props.selectedModel ? '这是当前选中的模型，删除后 Atlas 会切换到列表里的第一个模型。' : ''}</p>}
      {props.connectionTest && <p className={props.connectionTest.ok ? styles.settingsSuccess : styles.settingsError} role="status">{props.connectionTest.ok ? '连接成功：' : '连接失败：'}{props.connectionTest.message}</p>}
    </section>
    {editingModel && <section className={styles.settingsCard} aria-label="编辑模型">
      <div className={styles.settingsCardHeading}><h2>编辑模型：{editingModel.name ?? editingModel.id}</h2><button type="button" className={styles.quietButton} onClick={() => setEditingModelId(null)}><X size={14} />取消编辑</button></div>
      <ModelForm key={`edit-${editingModel.id}`} model={editingModel} busy={props.busy} disabled={!props.connected} submitLabel="保存修改" onSubmit={saveEdit} />
    </section>}
    <section className={styles.settingsCard}>
      <h2>按阶段分配思考量</h2>
      <ReasoningStages config={props.reasoningStages} busy={props.busy} onChange={props.onSaveReasoningStages} />
    </section>
    <IntegrationPanel apiBaseUrl={props.apiBaseUrl} />
    <DependencyCheckPanel apiBaseUrl={props.apiBaseUrl} />
    {(props.error || props.busy) && <div className={props.error ? styles.settingsError : styles.settingsStatus} role={props.error ? 'alert' : 'status'}>{props.busy && <LoaderCircle size={14} className={styles.settingsSpinner} />}{props.error ?? '正在保存或测试配置…'}</div>}
    <footer className={styles.settingsFooter}>Atlas 后端 {props.apiBaseUrl}　模型服务 {props.providerBaseUrl}</footer>
  </section>;
}
