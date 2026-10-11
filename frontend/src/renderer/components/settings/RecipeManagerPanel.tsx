/**
 * Parameterized session recipes, modeled after Goose session recipes:
 * https://goose-docs.ai/docs/guides/recipes/session-recipes/
 * https://goose-docs.ai/docs/guides/recipes/recipe-reference/
 */
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Play, Plus, Save, Trash2 } from 'lucide-react';
import type { ModelInfo, ProviderState } from '@atlas/backend-adapter';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

export type RecipeParameter = {
  name: string;
  label: string;
  description?: string | null;
  type: 'string' | 'number' | 'boolean';
  required: boolean;
  default?: string | number | boolean | null;
};

export type RecipeRecord = {
  id: string;
  name: string;
  description: string;
  prompt: string;
  parameters: RecipeParameter[];
  provider_id: string;
  model_id: string;
  allowed_extension_ids: string[];
  activity_button_label: string;
  output_shape: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

/** Host contract: the owner decides how this prepared session enters chat/runtime. */
export type RecipeLaunchRequest = {
  recipe: RecipeRecord;
  parameterValues: Record<string, unknown>;
  renderedPrompt: string;
  activity: string;
  providerId: string;
  modelId: string;
  allowedExtensionIds: string[];
  outputShape: Record<string, unknown>;
  metadata: Record<string, unknown>;
};

type Draft = RecipeRecord & { allowedIdsText: string; outputShapeText: string; metadataText: string };
const blank = (): Draft => ({
  id: globalThis.crypto?.randomUUID?.() ?? `recipe-${Date.now()}`,
  name: '', description: '', prompt: '', parameters: [], provider_id: '', model_id: '',
  allowed_extension_ids: [], activity_button_label: '开始配方', output_shape: {}, metadata: {},
  allowedIdsText: '', outputShapeText: '{}', metadataText: '{}',
});
const toDraft = (recipe: RecipeRecord): Draft => ({
  ...recipe,
  allowedIdsText: recipe.allowed_extension_ids.join('\n'),
  outputShapeText: JSON.stringify(recipe.output_shape, null, 2),
  metadataText: JSON.stringify(recipe.metadata, null, 2),
});
const makeParameter = (): RecipeParameter => ({ name: '', label: '', description: '', type: 'string', required: false, default: '' });
const renderPrompt = (prompt: string, values: Record<string, unknown>) => prompt.replace(/\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}/g, (_match, key: string) => String(values[key] ?? ''));

export default function RecipeManagerPanel({ apiBaseUrl, models, providers, extensionIds = [], onLaunch }: {
  apiBaseUrl: string;
  models: ModelInfo[];
  providers: ProviderState[];
  extensionIds?: string[];
  onLaunch: (request: RecipeLaunchRequest) => void | Promise<void>;
}) {
  const [recipes, setRecipes] = useState<RecipeRecord[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60';
  const area = cn(field, 'h-auto py-2 font-mono text-[12px] leading-[1.55]');

  const load = async () => {
    const result = await api<{ recipes: RecipeRecord[] }>(apiBaseUrl, '/api/recipe-templates');
    setRecipes(result.recipes ?? []);
    if (!selectedId && result.recipes?.length) setSelectedId(result.recipes[0].id);
  };
  useEffect(() => { void load().catch((error) => setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) })); }, [apiBaseUrl]);
  useEffect(() => {
    if (isNew) return;
    const recipe = recipes.find((item) => item.id === selectedId);
    setDraft(recipe ? toDraft(recipe) : null);
    setValues(Object.fromEntries((recipe?.parameters ?? []).map((parameter) => [parameter.name, parameter.default ?? ''])));
    setDeleteArmed(false);
  }, [recipes, selectedId, isNew]);

  const selectedModelOptions = useMemo(() => {
    if (!draft?.provider_id) return models;
    return models.filter((model) => model.provider === draft.provider_id || model.hermes_provider === draft.provider_id || model.hermes_provider === providers.find((provider) => provider.id === draft.provider_id)?.hermes_provider);
  }, [draft?.provider_id, models, providers]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft) return;
    let outputShape: Record<string, unknown>;
    let metadata: Record<string, unknown>;
    try {
      outputShape = JSON.parse(draft.outputShapeText || '{}') as Record<string, unknown>;
      metadata = JSON.parse(draft.metadataText || '{}') as Record<string, unknown>;
      if (!outputShape || Array.isArray(outputShape) || typeof outputShape !== 'object') throw new Error('输出格式必须是 JSON 对象。');
      if (!metadata || Array.isArray(metadata) || typeof metadata !== 'object') throw new Error('嵌套元数据必须是 JSON 对象。');
    } catch (error) {
      setMessage({ ok: false, text: error instanceof Error ? error.message : 'JSON 格式无效。' });
      return;
    }
    const payload: RecipeRecord = {
      id: draft.id, name: draft.name.trim(), description: draft.description.trim(), prompt: draft.prompt,
      parameters: draft.parameters.map((parameter) => ({ ...parameter, name: parameter.name.trim(), label: parameter.label.trim() })),
      provider_id: draft.provider_id, model_id: draft.model_id,
      allowed_extension_ids: draft.allowedIdsText.split(/\r?\n/).map((id) => id.trim()).filter(Boolean),
      activity_button_label: draft.activity_button_label.trim() || '开始配方', output_shape: outputShape, metadata,
    };
    if (!payload.name || !payload.prompt.trim()) { setMessage({ ok: false, text: '名称和提示词不能为空。' }); return; }
    if (payload.parameters.some((parameter) => !parameter.name || !parameter.label)) { setMessage({ ok: false, text: '每个参数都需要填写键名和显示名称。' }); return; }
    setBusy(true);
    try {
      const saved = await api<RecipeRecord>(apiBaseUrl, isNew ? '/api/recipe-templates' : `/api/recipe-templates/${encodeURIComponent(payload.id)}`, { method: isNew ? 'POST' : 'PUT', json: payload });
      setRecipes((current) => isNew ? [...current, saved] : current.map((item) => item.id === saved.id ? saved : item));
      setSelectedId(saved.id); setIsNew(false); setMessage({ ok: true, text: '配方已保存。' });
    } catch (error) { setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) }); }
    finally { setBusy(false); }
  };

  const remove = async () => {
    if (!draft || isNew) return;
    if (!deleteArmed) { setDeleteArmed(true); return; }
    setBusy(true);
    try {
      await api(apiBaseUrl, `/api/recipe-templates/${encodeURIComponent(draft.id)}`, { method: 'DELETE' });
      const remaining = recipes.filter((item) => item.id !== draft.id);
      setRecipes(remaining); setSelectedId(remaining[0]?.id ?? ''); setDraft(remaining[0] ? toDraft(remaining[0]) : null); setMessage({ ok: true, text: '配方已删除。' });
    } catch (error) { setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) }); }
    finally { setBusy(false); setDeleteArmed(false); }
  };

  const launchRecipe = (recipe: RecipeRecord) => {
    const parameterValues = Object.fromEntries(recipe.parameters.map((parameter) => {
      const raw = values[parameter.name] ?? parameter.default ?? '';
      return [parameter.name, parameter.type === 'number' ? Number(raw) : parameter.type === 'boolean' ? Boolean(raw) : String(raw)];
    }));
    const missing = recipe.parameters.find((parameter) => parameter.required && (parameterValues[parameter.name] === '' || parameterValues[parameter.name] === undefined));
    if (missing) { setMessage({ ok: false, text: `请填写「${missing.label}」。` }); return; }
    try {
      void Promise.resolve(onLaunch({
        recipe, parameterValues, renderedPrompt: renderPrompt(recipe.prompt, parameterValues),
        activity: recipe.activity_button_label, providerId: recipe.provider_id, modelId: recipe.model_id,
        allowedExtensionIds: recipe.allowed_extension_ids, outputShape: recipe.output_shape, metadata: recipe.metadata,
      })).then(() => setMessage({ ok: true, text: '配方提示词已填入当前会话输入框，请检查后发送。' })).catch((error) => setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) }));
    } catch (error) { setMessage({ ok: false, text: error instanceof Error ? error.message : String(error) }); }
  };

  const currentSaved = recipes.find((item) => item.id === selectedId);
  const updateParameter = (index: number, patch: Partial<RecipeParameter>) => setDraft((current) => current ? ({ ...current, parameters: current.parameters.map((item, i) => i === index ? { ...item, ...patch } : item) }) : current);

  return <section className="grid gap-4" aria-label="参数化配方">
    <header><h2 className="text-[15px] font-semibold text-fg">配方</h2><p className="mt-1 text-[12.5px] text-fg-3">保存带参数的会话模板。提示词用 <code>{'{{参数键}}'}</code> 插入参数；启动由当前会话接手。</p></header>
    <div className="grid grid-cols-[190px_minmax(0,1fr)] gap-5">
      <nav className="grid content-start gap-1" aria-label="配方列表">
        {recipes.map((recipe) => <button key={recipe.id} onClick={() => { setSelectedId(recipe.id); setIsNew(false); setMessage(null); }} aria-current={!isNew && recipe.id === selectedId}
          className={cn('rounded-lg px-2.5 py-2 text-left text-[13px]', !isNew && recipe.id === selectedId ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover')}>
          <span className="block truncate font-medium">{recipe.name}</span><span className="mt-0.5 block truncate text-[11px] text-fg-3">{recipe.description || recipe.activity_button_label}</span>
        </button>)}
        <Button variant="ghost" size="sm" className="justify-start" onClick={() => { setDraft(blank()); setSelectedId(''); setIsNew(true); setMessage(null); }}><Plus />新建配方</Button>
        {!recipes.length && !isNew && <p className="px-2 py-3 text-[12px] text-fg-3">还没有配方。</p>}
      </nav>

      {draft ? <div className="grid content-start gap-4">
        <form onSubmit={(event) => void save(event)} className="grid gap-3 text-[12.5px] text-fg-2">
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1">名称<input required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} className={field} /></label>
            <label className="grid gap-1">活动按钮文字<input value={draft.activity_button_label} onChange={(event) => setDraft({ ...draft, activity_button_label: event.target.value })} className={field} /></label>
          </div>
          <label className="grid gap-1">说明<input value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} className={field} /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1">服务商<select value={draft.provider_id} onChange={(event) => setDraft({ ...draft, provider_id: event.target.value, model_id: '' })} className={field}><option value="">跟随当前选择</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}</select></label>
            <label className="grid gap-1">模型<select value={draft.model_id} onChange={(event) => setDraft({ ...draft, model_id: event.target.value })} className={field}><option value="">跟随当前选择</option>{selectedModelOptions.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}</select></label>
          </div>
          <label className="grid gap-1">提示词模板 <small className="text-fg-3">在正文中用 {'{{参数键}}'} 引用下面的参数。</small><textarea required rows={6} value={draft.prompt} onChange={(event) => setDraft({ ...draft, prompt: event.target.value })} className={area} /></label>
          <section className="grid gap-2 rounded-xl bg-sunken p-3 shadow-[inset_0_0_0_1px_var(--line)]">
            <div className="flex items-center justify-between"><h3 className="font-medium text-fg">参数</h3><Button variant="ghost" size="sm" onClick={() => setDraft({ ...draft, parameters: [...draft.parameters, makeParameter()] })}><Plus />添加参数</Button></div>
            {draft.parameters.map((parameter, index) => <div key={`${index}-${parameter.name}`} className="grid grid-cols-[1fr_1fr_100px_1fr_auto] gap-2">
              <input aria-label="参数键" placeholder="topic" value={parameter.name} onChange={(event) => updateParameter(index, { name: event.target.value.replace(/[^A-Za-z0-9_.-]/g, '_') })} className={field} />
              <input aria-label="参数名称" placeholder="研究主题" value={parameter.label} onChange={(event) => updateParameter(index, { label: event.target.value })} className={field} />
              <select aria-label="参数类型" value={parameter.type} onChange={(event) => updateParameter(index, { type: event.target.value as RecipeParameter['type'] })} className={field}><option value="string">文字</option><option value="number">数字</option><option value="boolean">开关</option></select>
              {parameter.type === 'boolean' ? <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={Boolean(parameter.default)} onChange={(event) => updateParameter(index, { default: event.target.checked })} />默认开启</label> : <input aria-label="默认值" placeholder="默认值" value={String(parameter.default ?? '')} onChange={(event) => updateParameter(index, { default: parameter.type === 'number' && event.target.value !== '' ? Number(event.target.value) : event.target.value })} className={field} />}
              <button type="button" aria-label="移除参数" onClick={() => setDraft({ ...draft, parameters: draft.parameters.filter((_, i) => i !== index) })} className="grid size-9 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-danger"><Trash2 size={15} /></button>
              <input placeholder="帮助说明（可选）" value={parameter.description ?? ''} onChange={(event) => updateParameter(index, { description: event.target.value })} className={cn(field, 'col-span-4')} />
              <label className="flex items-center gap-1 text-[11px]"><input type="checkbox" checked={parameter.required} onChange={(event) => updateParameter(index, { required: event.target.checked })} />必填</label>
            </div>)}
            {!draft.parameters.length && <p className="text-[12px] text-fg-3">无参数的配方也可以直接启动。</p>}
          </section>
          <label className="grid gap-1">允许使用的扩展 ID <small className="text-fg-3">每行一个 ID。留空表示不声明限制。可用 ID：{extensionIds.join('、') || '尚未提供扩展目录'}</small><textarea rows={3} value={draft.allowedIdsText} onChange={(event) => setDraft({ ...draft, allowedIdsText: event.target.value })} className={area} /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="grid gap-1">输出形状（JSON 对象）<textarea rows={5} value={draft.outputShapeText} onChange={(event) => setDraft({ ...draft, outputShapeText: event.target.value })} className={area} /></label>
            <label className="grid gap-1">嵌套配方元数据（JSON 对象）<textarea rows={5} value={draft.metadataText} onChange={(event) => setDraft({ ...draft, metadataText: event.target.value })} className={area} /></label>
          </div>
          <div className="flex gap-2"><Button type="submit" variant="primary" disabled={busy}><Save />{busy ? '保存中…' : '保存配方'}</Button>{!isNew && <Button variant="danger" disabled={busy} onClick={() => void remove()}><Trash2 />{deleteArmed ? '再次点击确认删除' : '删除'}</Button>}</div>
        </form>

        {currentSaved && <section className="grid gap-3 rounded-xl border border-line p-3" aria-label="启动配方">
          <div><h3 className="text-[13px] font-semibold text-fg">{currentSaved.activity_button_label}</h3><p className="mt-1 text-[12px] text-fg-3">填入参数后启动已保存的版本。</p></div>
          {currentSaved.parameters.map((parameter) => <label key={parameter.name} className="grid gap-1 text-[12px] text-fg-2">{parameter.label}{parameter.description && <small className="text-fg-3">{parameter.description}</small>}{parameter.type === 'boolean' ? <input type="checkbox" checked={Boolean(values[parameter.name])} onChange={(event) => setValues({ ...values, [parameter.name]: event.target.checked })} className="size-4 accent-[var(--brand)]" /> : <input required={parameter.required} type={parameter.type === 'number' ? 'number' : 'text'} value={String(values[parameter.name] ?? '')} onChange={(event) => setValues({ ...values, [parameter.name]: parameter.type === 'number' && event.target.value !== '' ? Number(event.target.value) : event.target.value })} className={field} />}</label>)}
          <Button variant="primary" onClick={() => launchRecipe(currentSaved)}><Play />{currentSaved.activity_button_label}</Button>
          <details className="text-[11px] text-fg-3"><summary className="cursor-pointer">启动预览</summary><pre className="mt-2 whitespace-pre-wrap rounded-lg bg-sunken p-2">{renderPrompt(currentSaved.prompt, values)}</pre></details>
        </section>}
      </div> : <div className="grid min-h-48 place-items-center rounded-xl border border-dashed border-line text-[13px] text-fg-3">选择一个配方，或新建配方。</div>}
    </div>
    {message && <p role="status" className={cn('whitespace-pre-wrap text-[12px]', message.ok ? 'text-brand' : 'text-danger')}>{message.text}</p>}
  </section>;
}
