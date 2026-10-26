import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Check, ChevronLeft, LoaderCircle, Pencil, Pin, Radio, Search, Star, Trash2, X } from 'lucide-react';
import type { CustomModelRequest, CustomModelUpdateRequest, ModelInfo, ProviderState, ReasoningStagesConfig } from '@atlas/backend-adapter';
import DependencyCheckPanel from './DependencyCheckPanel';
import IntegrationPanel from './IntegrationPanel';
import { BrowserSettingsSection, ComputerStatusSection } from '../components/x2';
import KeyManager from './models/KeyManager';
import ModelForm, { buildCreateRequest, buildUpdatePatch, type ModelFormValues } from './models/ModelForm';
import ProviderGrid from './models/ProviderGrid';
import ReasoningStages from './models/ReasoningStages';
import { cn } from '../ui/cn';
import styles from '../App.module.css';
import ModelCatalogPreferencesPanel, { type ModelCatalogPreferences } from '../components/settings/ModelCatalogPreferencesPanel';
import WslSessionPolicyPanel from '../components/settings/WslSessionPolicyPanel';

export const STATUS_BAR_ITEMS = [
  ['model', '模型'], ['reasoning', '推理强度'], ['context', '上下文占用'], ['tokens', 'Token 用量'],
  ['cost', '费用估算'], ['git', 'Git 分支'], ['permission', '权限模式'], ['processes', '后台进程'],
] as const;
export type StatusBarPreferences = Record<(typeof STATUS_BAR_ITEMS)[number][0], boolean>;

type ProviderFilter = 'all' | 'configured' | 'unconfigured' | 'attention';
type ModelFilter = 'all' | 'selected' | 'provider' | 'gateway' | 'configured' | 'unconfigured';

const PINNED_PROVIDERS_KEY = 'atlas.settings.providers.pinned.v1';
const MODEL_CYCLE_KEY = 'atlas.model-cycle';
const searchFieldClass = 'h-9 min-w-0 rounded-lg border border-line bg-surface px-3 text-[12.5px] text-fg placeholder:text-fg-3';
const filterFieldClass = 'h-9 rounded-lg border border-line bg-surface px-2.5 text-[12.5px] text-fg';

function readPinnedProviders(): string[] {
  try {
    if (typeof localStorage === 'undefined') return [];
    const saved: unknown = JSON.parse(localStorage.getItem(PINNED_PROVIDERS_KEY) ?? '[]');
    return Array.isArray(saved) ? saved.filter((item): item is string => typeof item === 'string') : [];
  } catch { return []; }
}

function readModelCycle(): string[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(MODEL_CYCLE_KEY) ?? '[]');
    return Array.isArray(saved) ? saved.filter((item): item is string => typeof item === 'string') : [];
  } catch { return []; }
}

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
  errorDetail?: string | null;
  models: ModelInfo[];
  selectedModel: string;
  subagentsEnabled: boolean;
  subagentDefaultModel: string;
  subagentMaxConcurrent: number;
  /** Catalog of supported model services with this installation's keys and endpoints. */
  providers: ProviderState[];
  reasoningStages: ReasoningStagesConfig;
  onBack: () => void;
  onSelectModel: (model: string) => void;
  onSaveSubagentSettings: (enabled: boolean, defaultModel: string, maxConcurrent?: number) => Promise<boolean>;
  onSaveProvider: (baseUrl: string, apiKey: string) => Promise<boolean>;
  onAddModel: (model: CustomModelRequest) => Promise<boolean>;
  onTestConnection: (model: string) => void;
  statusBar: StatusBarPreferences;
  onStatusBarChange: (key: keyof StatusBarPreferences, visible: boolean) => void;
  statusBarVisible: boolean;
  onStatusBarVisibleChange: (visible: boolean) => void;
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
  const [providerSearch, setProviderSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState<ProviderFilter>('all');
  const [modelSearch, setModelSearch] = useState('');
  const [modelFilter, setModelFilter] = useState<ModelFilter>('all');
  const [modelCatalogPreferences, setModelCatalogPreferences] = useState<ModelCatalogPreferences | null>(null);
  const [pinnedProviderIds, setPinnedProviderIds] = useState<string[]>(readPinnedProviders);
  const [cycleModels, setCycleModels] = useState<string[]>(readModelCycle);
  const [editingModelId, setEditingModelId] = useState<string | null>(null);
  const [deletingModelId, setDeletingModelId] = useState<string | null>(null);
  const [parallelLimit, setParallelLimit] = useState(String(props.subagentMaxConcurrent));
  useEffect(() => setParallelLimit(String(props.subagentMaxConcurrent)), [props.subagentMaxConcurrent]);

  useEffect(() => { props.onLoadProviders(); }, []);
  useEffect(() => {
    try { localStorage.setItem(PINNED_PROVIDERS_KEY, JSON.stringify(pinnedProviderIds)); }
    catch { /* The pin is only a local display preference. */ }
  }, [pinnedProviderIds]);
  useEffect(() => {
    const available = new Set(props.models.map((model) => model.id));
    const next = cycleModels.filter((id) => available.has(id));
    if (next.length !== cycleModels.length) setCycleModels(next);
    try { localStorage.setItem(MODEL_CYCLE_KEY, JSON.stringify(next)); } catch { /* Local shortcut preference. */ }
  }, [cycleModels, props.models]);

  const provider = props.providers.find((item) => item.id === selectedProviderId) ?? null;
  // Nothing picked yet (or the list just arrived): start on the first configured provider.
  useEffect(() => {
    if (!provider && props.providers.length) {
      const preferred = props.providers.find((item) => item.configured) ?? props.providers[0];
      setSelectedProviderId(preferred.id);
    }
  }, [provider, props.providers]);

  const providerResults = useMemo(() => {
    const query = providerSearch.trim().toLocaleLowerCase();
    const now = Date.now() / 1000;
    return props.providers
      .filter((item) => {
        const attention = item.keys.some((key) => Boolean(key.last_error?.trim()) || (key.cooldown_until ?? 0) > now);
        const matchesStatus = providerFilter === 'all'
          || (providerFilter === 'configured' && item.configured)
          || (providerFilter === 'unconfigured' && !item.configured)
          || (providerFilter === 'attention' && attention);
        const matchesSearch = !query || `${item.label} ${item.id} ${item.hermes_provider}`.toLocaleLowerCase().includes(query);
        return matchesStatus && matchesSearch;
      })
      .sort((a, b) => Number(pinnedProviderIds.includes(b.id)) - Number(pinnedProviderIds.includes(a.id)));
  }, [props.providers, providerSearch, providerFilter, pinnedProviderIds]);
  const providerVisible = providerResults.some((item) => item.id === provider?.id);

  const modelProvider = (model: ModelInfo) => model.hermes_provider
    ? props.providers.find((item) => item.id === model.hermes_provider || item.hermes_provider === model.hermes_provider) ?? null
    : null;
  const hiddenModelIds = useMemo(() => new Set(modelCatalogPreferences?.hidden_ids ?? []), [modelCatalogPreferences]);
  const pinnedModelIds = useMemo(() => new Set(modelCatalogPreferences?.pinned_ids ?? []), [modelCatalogPreferences]);
  const modelOrder = useMemo(() => new Map<string, number>((modelCatalogPreferences?.order_ids ?? []).map((id, index): [string, number] => [id, index])), [modelCatalogPreferences]);
  const orderedModels = useMemo(() => {
    const orderedKnownModels = props.models.filter((model) => modelOrder.has(model.id)).sort((left, right) => {
      const pinDifference = Number(pinnedModelIds.has(right.id)) - Number(pinnedModelIds.has(left.id));
      if (pinDifference) return pinDifference;
      return (modelOrder.get(left.id) ?? 0) - (modelOrder.get(right.id) ?? 0);
    });
    let nextKnownIndex = 0;
    return props.models.map((model) => {
      if (!modelOrder.has(model.id)) return model;
      return orderedKnownModels[nextKnownIndex++] ?? model;
    });
  }, [props.models, pinnedModelIds, modelOrder]);
  const modelResults = useMemo(() => {
    const query = modelSearch.trim().toLocaleLowerCase();
    return orderedModels.filter((model) => {
      const routedProvider = model.hermes_provider ? props.providers.find((item) =>
        item.id === model.hermes_provider || item.hermes_provider === model.hermes_provider,
      ) : undefined;
      const usesProvider = Boolean(model.hermes_provider);
      const savedRoute = model.base_url?.trim() ? true : routedProvider ? routedProvider.configured : !model.hermes_provider && props.apiKeyConfigured;
      const matchesFilter = modelFilter === 'all'
        || (modelFilter === 'selected' && model.id === props.selectedModel)
        || (modelFilter === 'provider' && usesProvider)
        || (modelFilter === 'gateway' && !usesProvider)
        || (modelFilter === 'configured' && savedRoute)
        || (modelFilter === 'unconfigured' && !savedRoute);
      const matchesSearch = !query || [model.name, model.id, model.provider, model.hermes_provider, model.native_model, model.litellm_model]
        .some((value) => typeof value === 'string' && value.toLocaleLowerCase().includes(query));
      const selectedHidden = model.id === props.selectedModel && hiddenModelIds.has(model.id);
      return selectedHidden || (!hiddenModelIds.has(model.id) && matchesFilter && matchesSearch);
    });
  }, [orderedModels, props.providers, props.selectedModel, props.apiKeyConfigured, modelSearch, modelFilter, hiddenModelIds]);

  // The model entry this provider already has, if any; legacy gateway models (no hermes_provider) never match.
  const providerModel = provider
    ? props.models.find((model) => Boolean(model.hermes_provider) && (model.provider === provider.id || model.hermes_provider === provider.hermes_provider)) ?? null
    : null;
  const editingModel = editingModelId ? props.models.find((model) => model.id === editingModelId) ?? null : null;
  const subagentSelectedModel = props.subagentDefaultModel || props.selectedModel;
  const subagentModelOptions = orderedModels.filter((model) => !hiddenModelIds.has(model.id) || model.id === subagentSelectedModel);

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
      <div className={styles.settingsCardHeading}><h2>服务商</h2><span className="text-[11.5px] text-fg-3">{providerResults.length}/{props.providers.length}</span></div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative min-w-[190px] flex-1">
          <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-3" />
          <input type="search" aria-label="搜索服务商" className={`${searchFieldClass} w-full pl-8`} value={providerSearch} onChange={(event) => setProviderSearch(event.target.value)} placeholder="搜索名称或 ID" />
        </label>
        <select aria-label="筛选服务商状态" className={filterFieldClass} value={providerFilter} onChange={(event) => setProviderFilter(event.target.value as ProviderFilter)}>
          <option value="all">全部状态</option><option value="configured">已配置</option><option value="unconfigured">未配置</option><option value="attention">有密钥错误记录或冷却</option>
        </select>
        <button type="button" className={styles.settingsActionSecondary} disabled={!provider} aria-pressed={Boolean(provider && pinnedProviderIds.includes(provider.id))}
          onClick={() => { if (!provider) return; setPinnedProviderIds((ids) => ids.includes(provider.id) ? ids.filter((id) => id !== provider.id) : [...ids, provider.id]); }}>
          <Pin size={14} />{provider && pinnedProviderIds.includes(provider.id) ? '取消置顶当前项' : '置顶当前项'}
        </button>
      </div>
      <p className="mb-3 text-[11.5px] text-fg-3">置顶仅影响此设备上的列表顺序。已配置表示保存了密钥或自定义地址，不代表连接已验证。</p>
      <ProviderGrid providers={providerResults} selectedId={providerVisible ? provider?.id ?? '' : ''} onSelect={(id) => { setSelectedProviderId(id); setDeletingModelId(null); setEditingModelId(null); }} />
      {provider && !providerVisible && <p className="mt-3 mb-0 text-[12px] text-fg-3">当前选择的服务商被搜索或筛选隐藏；选择列表中的项目后可编辑其配置。</p>}
    </section>

    {provider && providerVisible && <section className={styles.settingsCard}>
      <div className={styles.settingsCardHeading}>
        <h2>{provider.label} · 接口与模型</h2>
        <span className="text-[11.5px] text-fg-3">{provider.configured ? '配置已保存，连接需实测' : '未保存密钥或自定义地址'}</span>
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
      {provider.keys.some((key) => key.last_error || ((key.cooldown_until ?? 0) * 1000 > Date.now())) && <details className="mt-3 rounded-lg border border-line px-3 py-2 text-[12px]">
        <summary className="cursor-pointer text-danger">密钥错误记录与冷却详情</summary>
        <div className="mt-2 grid gap-2">
          {provider.keys.filter((key) => key.last_error || ((key.cooldown_until ?? 0) * 1000 > Date.now())).map((key) => <div key={key.id} className="rounded-md bg-sunken p-2">
            <strong>{key.label || key.id}</strong>
            {key.last_error && <pre className="mt-1 mb-0 max-h-32 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] text-danger">{key.last_error}</pre>}
            {(key.cooldown_until ?? 0) * 1000 > Date.now() && <p className="mt-1 mb-0 text-fg-3">冷却至 {new Date((key.cooldown_until ?? 0) * 1000).toLocaleString()}</p>}
          </div>)}
        </div>
      </details>}
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
      <h2>状态栏</h2>
      <p>选择对话底部显示的状态信息。新安装时默认全部显示。</p>
      <div className={styles.settingsForm}>
        <label className="flex items-center gap-2"><input type="checkbox" checked={props.statusBarVisible} onChange={(event) => props.onStatusBarVisibleChange(event.target.checked)} />显示整行状态栏</label>
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
            {subagentModelOptions.map((model) => <option key={model.id} value={model.id} disabled={hiddenModelIds.has(model.id)}>{model.name ?? model.id}{hiddenModelIds.has(model.id) ? '（当前值已隐藏）' : ''}</option>)}
          </select>
        </label>
        <label>最多同时运行的子 Agent
          <input aria-label="并行子 Agent 上限" type="number" min={1} max={128} step={1} value={parallelLimit} disabled={props.busy || !props.connected} onChange={(event) => setParallelLimit(event.target.value)} />
          <button type="button" className="btn ghost" disabled={props.busy || !props.connected || !Number.isInteger(Number(parallelLimit)) || Number(parallelLimit) < 1 || Number(parallelLimit) > 128} onClick={() => void props.onSaveSubagentSettings(props.subagentsEnabled, props.subagentDefaultModel || props.selectedModel, Number(parallelLimit))}>保存并行上限</button>
        </label>
      </div>
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
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label className="relative min-w-[190px] flex-1">
          <Search size={14} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-fg-3" />
          <input type="search" aria-label="搜索模型" className={`${searchFieldClass} w-full pl-8`} value={modelSearch} onChange={(event) => setModelSearch(event.target.value)} placeholder="搜索名称、模型 ID 或服务商" />
        </label>
        <select aria-label="筛选模型" className={filterFieldClass} value={modelFilter} onChange={(event) => setModelFilter(event.target.value as ModelFilter)}>
          <option value="all">全部模型</option><option value="selected">当前默认</option><option value="provider">服务商路由</option><option value="gateway">网关路由</option><option value="configured">已保存路由配置</option><option value="unconfigured">待配置路由</option>
        </select>
      </div>
      <p className="mb-3 text-[11.5px] text-fg-3">“当前默认”表示新会话使用的模型；配置状态只检查已保存的密钥或地址，实际可用性请运行连接测试。思考档位来自后端路由入口，部分服务商会在实际请求时进一步映射或降档。</p>
      <div className={styles.settingsModels}>{modelResults.map((model) => {
        const selected = model.id === props.selectedModel;
        const inCycle = cycleModels.includes(model.id);
        const hidden = hiddenModelIds.has(model.id);
        const routeProvider = modelProvider(model);
        const availability = model.base_url?.trim() ? '已设置每模型地址'
          : routeProvider ? routeProvider.configured ? `${routeProvider.label}已保存密钥或地址` : `${routeProvider.label}未保存密钥或地址`
            : model.hermes_provider ? '服务商状态未加载'
              : props.apiKeyConfigured ? '网关密钥已保存' : '网关密钥未配置（本机模型可能无需密钥）';
        const effortHint = Array.isArray(model.reasoning_efforts) && model.reasoning_efforts.length
          ? `Atlas 路由入口档位：${model.reasoning_efforts.join(' / ')}` : null;
        return <div className={`${styles.settingsModelRow} ${selected ? styles.settingsModelSelected : ''}`} key={model.id}>
          <button disabled={hidden && selected} title={hidden && selected ? '当前模型已隐藏；切换模型后此项会从列表隐藏' : undefined} onClick={() => props.onSelectModel(model.id)}><span><strong>{model.name ?? model.id}</strong><small>{model.provider ? `${model.provider}，${model.id}` : model.id} · {selected ? (hidden ? '当前默认 · 已隐藏；切换后从列表隐藏 · ' : '当前默认 · ') : ''}{availability}</small>{effortHint && <small>{effortHint}</small>}</span>{selected && <Check size={17} />}</button>
          <div className="flex items-stretch gap-1.5">
            <button type="button" className={cn(rowButton, inCycle && 'text-amber-500')} aria-label={`${inCycle ? '从收藏循环移除' : '加入收藏循环'}：${model.name ?? model.id}`} aria-pressed={inCycle} title={inCycle ? '从 Ctrl+P 收藏模型循环移除' : '加入 Ctrl+P 收藏模型循环'} onClick={() => setCycleModels((current) => current.includes(model.id) ? current.filter((id) => id !== model.id) : [...current, model.id])}><Star size={14} fill={inCycle ? 'currentColor' : 'none'} /></button>
            <button type="button" className={rowButton} aria-label={`测试 ${model.name ?? model.id} 连接`} disabled={props.busy || !props.connected} onClick={() => props.onTestConnection(model.id)} title="测试模型连接"><Radio size={14} /></button>
            <button type="button" className={rowButton} aria-label={`编辑 ${model.name ?? model.id}`} disabled={!props.connected} onClick={() => { setEditingModelId(model.id); setDeletingModelId(null); }} title="编辑模型"><Pencil size={14} /></button>
            <button type="button" className={cn(rowButton, deletingModelId === model.id && 'bg-danger-soft text-danger hover:bg-danger-soft hover:text-danger')} aria-label={`删除 ${model.name ?? model.id}`} disabled={props.busy || !props.connected} onClick={() => removeModel(model)} title="删除模型（再点一次确认）"><Trash2 size={14} /></button>
          </div>
        </div>;
      })}{!props.models.length && <p>当前没有已登记模型。</p>}{props.models.length > 0 && !modelResults.length && <p>没有匹配的模型；调整搜索词或筛选条件。</p>}</div>
      {deletingModelId && <p role="status" className="m-0 text-[12.5px] text-danger">再点一次「删除」确认删除。{deletingModelId === props.selectedModel ? '这是当前选中的模型，删除后 Atlas 会切换到列表里的第一个模型。' : ''}</p>}
      {props.connectionTest && (props.connectionTest.ok
        ? <p className={styles.settingsSuccess} role="status">{props.connectionTest.message}</p>
        : <div className={styles.settingsError} role="status"><p className="m-0">连接测试失败</p><details className="mt-1"><summary className="cursor-pointer">查看错误详情</summary><pre className="mt-1 mb-0 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11.5px]">{props.connectionTest.message}</pre></details></div>)}
    </section>
    <section className={styles.settingsCard}><ModelCatalogPreferencesPanel apiBaseUrl={props.apiBaseUrl} onPreferencesChange={setModelCatalogPreferences} /></section>
    {editingModel && <section className={styles.settingsCard} aria-label="编辑模型">
      <div className={styles.settingsCardHeading}><h2>编辑模型：{editingModel.name ?? editingModel.id}</h2><button type="button" className={styles.quietButton} onClick={() => setEditingModelId(null)}><X size={14} />取消编辑</button></div>
      <ModelForm key={`edit-${editingModel.id}`} model={editingModel} busy={props.busy} disabled={!props.connected} submitLabel="保存修改" onSubmit={saveEdit} />
    </section>}
    <section className={styles.settingsCard}>
      <h2>按阶段分配思考量</h2>
      <ReasoningStages config={props.reasoningStages} busy={props.busy} onChange={props.onSaveReasoningStages} />
    </section>
    <IntegrationPanel apiBaseUrl={props.apiBaseUrl} />
    <BrowserSettingsSection apiBaseUrl={props.apiBaseUrl} />
    <WslSessionPolicyPanel apiBaseUrl={props.apiBaseUrl} />
    <ComputerStatusSection apiBaseUrl={props.apiBaseUrl} />
    <DependencyCheckPanel apiBaseUrl={props.apiBaseUrl} />
    {(props.error || props.busy) && <div className={props.error ? styles.settingsError : styles.settingsStatus} role={props.error ? 'alert' : 'status'}>
      {props.busy && <LoaderCircle size={14} className={styles.settingsSpinner} />}{props.error ?? '正在保存或测试配置…'}
      {props.error && props.errorDetail && <details className="mt-1"><summary className="cursor-pointer text-[12px]">详细信息</summary><pre className="mt-1 mb-0 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11.5px]">{props.errorDetail}</pre></details>}
    </div>}
    <footer className={styles.settingsFooter}>Atlas 后端 {props.apiBaseUrl}　模型服务 {props.providerBaseUrl}</footer>
  </section>;
}
