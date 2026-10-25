import { useState, type FormEvent } from 'react';
import type { CustomModelRequest, CustomModelUpdateRequest, ModelCapabilities, ModelInfo, ProviderState } from '@atlas/backend-adapter';
import { Button } from '../../ui/Button';

/** Everything one model entry needs; empty strings mean "not set". */
export interface ModelFormValues {
  /** Provider-level API base URL (provider form only; saved via PUT /api/providers/{id}/config). */
  providerBaseUrl: string;
  /** Native model id, e.g. deepseek-v4.1-flash. */
  modelId: string;
  displayName: string;
  litellmModel: string;
  /** Per-model base URL override (edit dialog only; empty = follow the provider). */
  baseUrl: string;
  maxOutput: string;
  price: { input: string; output: string; cached_input: string };
  capabilities: { context_window: string; max_output_tokens: string; supports_vision: boolean; supports_tools: boolean; supports_reasoning: boolean; supports_priority_tier: boolean };
}

const numberOrNull = (value: string): number | undefined => {
  const trimmed = value.trim();
  return trimmed === '' || Number.isNaN(Number(trimmed)) ? undefined : Number(trimmed);
};

/** `auto`: only send the flags that are on (new model); `always`: also send false, so checks can be turned off. */
function buildCapabilities(input: ModelFormValues['capabilities'], booleans: 'auto' | 'always'): ModelCapabilities | undefined {
  const context = numberOrNull(input.context_window);
  const max = numberOrNull(input.max_output_tokens);
  const caps: ModelCapabilities = {
    ...(context !== undefined ? { context_window: context } : {}),
    ...(max !== undefined ? { max_output_tokens: max } : {}),
    ...(booleans === 'always' || input.supports_vision ? { supports_vision: input.supports_vision } : {}),
    ...(booleans === 'always' || input.supports_tools ? { supports_tools: input.supports_tools } : {}),
    ...(booleans === 'always' || input.supports_reasoning ? { supports_reasoning: input.supports_reasoning } : {}),
    ...(input.supports_priority_tier ? { service_tiers: ['default', 'priority'] } : {}),
  };
  return Object.keys(caps).length ? caps : undefined;
}

function buildPrice(price: ModelFormValues['price']): CustomModelRequest['price'] | undefined {
  const input = numberOrNull(price.input);
  const output = numberOrNull(price.output);
  const cachedInput = numberOrNull(price.cached_input);
  const entry = {
    ...(input !== undefined ? { input } : {}),
    ...(output !== undefined ? { output } : {}),
    ...(cachedInput !== undefined ? { cached_input: cachedInput } : {}),
  };
  return Object.keys(entry).length ? entry : undefined;
}

/** POST /api/models/custom payload for a model set up through its provider. */
export function buildCreateRequest(provider: ProviderState, values: ModelFormValues): CustomModelRequest {
  const litellm = values.litellmModel.trim() || `${provider.id}/${values.modelId.trim()}`;
  const max = numberOrNull(values.maxOutput);
  const price = buildPrice(values.price);
  const capabilities = buildCapabilities(values.capabilities, 'auto');
  return {
    id: litellm,
    name: values.displayName.trim() || values.modelId.trim(),
    provider: provider.id,
    litellm_model: litellm,
    hermes_provider: provider.hermes_provider,
    native_model: values.modelId.trim(),
    ...(max !== undefined ? { max_output_tokens: max } : {}),
    ...(price ? { price } : {}),
    ...(capabilities ? { capabilities } : {}),
  };
}

/** PUT /api/models/custom/{id} patch; `withBaseUrl` only when the per-model field is on screen. */
export function buildUpdatePatch(model: ModelInfo, values: ModelFormValues, withBaseUrl = true): CustomModelUpdateRequest {
  const max = numberOrNull(values.maxOutput);
  const price = buildPrice(values.price);
  return {
    name: values.displayName.trim() || model.name || model.id,
    ...(withBaseUrl ? { base_url: values.baseUrl.trim() || null } : {}),
    litellm_model: values.litellmModel.trim() || model.litellm_model || model.id,
    native_model: values.modelId.trim() || null,
    hermes_provider: model.hermes_provider ?? null,
    ...(max !== undefined ? { max_output_tokens: max } : {}),
    ...(price ? { price } : {}),
    capabilities: buildCapabilities(values.capabilities, 'always') ?? {},
  };
}

function initialValues(provider?: ProviderState | null, model?: ModelInfo | null): ModelFormValues {
  if (model) {
    const caps = model.capabilities ?? {};
    const price = model.price ?? {};
    const token = (value: number | undefined) => value === undefined || value === null ? '' : String(value);
    return {
      providerBaseUrl: '',
      modelId: model.native_model ?? '',
      displayName: model.name ?? '',
      litellmModel: model.litellm_model ?? model.id,
      baseUrl: model.base_url ?? '',
      maxOutput: token(model.max_output_tokens),
      price: { input: token(price.input), output: token(price.output), cached_input: token(price.cached_input) },
      capabilities: {
        context_window: token(caps.context_window),
        max_output_tokens: token(caps.max_output_tokens),
        supports_vision: Boolean(caps.supports_vision),
        supports_tools: caps.supports_tools ?? true,
        supports_reasoning: caps.supports_reasoning ?? true,
        supports_priority_tier: Array.isArray(caps.service_tiers) && caps.service_tiers.includes('priority'),
      },
    };
  }
  return {
    providerBaseUrl: provider ? (provider.base_url || provider.default_base_url) : '',
    modelId: '', displayName: '', litellmModel: '', baseUrl: '', maxOutput: '',
    price: { input: '', output: '', cached_input: '' },
    capabilities: { context_window: '', max_output_tokens: '', supports_vision: false, supports_tools: true, supports_reasoning: true, supports_priority_tier: false },
  };
}

interface ModelFormProps {
  /** Set in the provider form: shows the provider base URL and suggests `<provider>/<model>`. */
  provider?: ProviderState | null;
  /** Existing model to prefill from; absent = create a new model. */
  model?: ModelInfo | null;
  busy?: boolean;
  disabled?: boolean;
  submitLabel: string;
  /** Resolve true after the values were saved. */
  onSubmit: (values: ModelFormValues) => Promise<boolean>;
}

/** The fields of one model entry: ids, endpoint, price and capabilities. */
export default function ModelForm({ provider, model, busy, disabled, submitLabel, onSubmit }: ModelFormProps) {
  const [values, setValues] = useState<ModelFormValues>(() => initialValues(provider, model));
  const [litellmTouched, setLitellmTouched] = useState(Boolean(model));
  const [saved, setSaved] = useState(false);
  const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const patch = (next: Partial<ModelFormValues>) => setValues((current) => ({ ...current, ...next }));
  const patchCaps = (next: Partial<ModelFormValues['capabilities']>) => setValues((current) => ({ ...current, capabilities: { ...current.capabilities, ...next } }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaved(false);
    if (await onSubmit(values)) setSaved(true);
  };

  return <form className="grid gap-3 text-[13px] text-fg-2" onSubmit={(event) => void submit(event)}>
    {provider && <label className="grid gap-1">API 地址
      <input type="url" value={values.providerBaseUrl} disabled={disabled || busy} className={field}
        onChange={(event) => patch({ providerBaseUrl: event.target.value })}
        placeholder={provider.default_base_url} />
      <small className="text-[12px] text-fg-3">默认 {provider.default_base_url}；改回默认再保存即可去掉覆盖。</small>
    </label>}
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1">模型 ID{provider ? '（服务商原生模型名）' : '（原生模型名，可不填）'}
        <input required={!model} value={values.modelId} disabled={disabled || busy} className={field}
          onChange={(event) => {
            const id = event.target.value;
            patch(provider && !litellmTouched ? { modelId: id, litellmModel: id ? `${provider.id}/${id}` : '' } : { modelId: id });
          }}
          placeholder="deepseek-v4.1-flash" /></label>
      <label className="grid gap-1">LiteLLM 模型名
        <input required value={values.litellmModel} disabled={disabled || busy} className={field}
          onChange={(event) => { setLitellmTouched(true); patch({ litellmModel: event.target.value }); }}
          placeholder={provider ? `${provider.id}/模型ID` : 'provider/model'} /></label>
    </div>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1">显示名称（可不填）
        <input value={values.displayName} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ displayName: event.target.value })} placeholder="界面里显示的名字" /></label>
      {!provider && <label className="grid gap-1">接口地址（每模型覆盖，可不填）
        <input type="url" value={values.baseUrl} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ baseUrl: event.target.value })} placeholder="留空则跟随服务商设置" /></label>}
      <label className="grid gap-1">最长输出（token，可不填，默认 16384）
        <input inputMode="numeric" value={values.maxOutput} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ maxOutput: event.target.value })} placeholder="16384" /></label>
    </div>
    <div className="grid gap-3 sm:grid-cols-3">
      <label className="grid gap-1">输入价格（每百万 token）
        <input inputMode="decimal" value={values.price.input} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ price: { ...values.price, input: event.target.value } })} placeholder="可不填" /></label>
      <label className="grid gap-1">输出价格
        <input inputMode="decimal" value={values.price.output} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ price: { ...values.price, output: event.target.value } })} placeholder="可不填" /></label>
      <label className="grid gap-1">缓存命中价格
        <input inputMode="decimal" value={values.price.cached_input} disabled={disabled || busy} className={field}
          onChange={(event) => patch({ price: { ...values.price, cached_input: event.target.value } })} placeholder="可不填" /></label>
    </div>
    <fieldset className="grid gap-2">
      <legend className="mb-1">能力（告诉 Atlas 这个模型能做什么）</legend>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5">
        <label className="flex items-center gap-2"><input type="checkbox" checked={values.capabilities.supports_vision} disabled={disabled || busy}
          onChange={(event) => patchCaps({ supports_vision: event.target.checked })} />视觉（能看图）</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={values.capabilities.supports_tools} disabled={disabled || busy}
          onChange={(event) => patchCaps({ supports_tools: event.target.checked })} />工具调用</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={values.capabilities.supports_reasoning} disabled={disabled || busy}
          onChange={(event) => patchCaps({ supports_reasoning: event.target.checked })} />推理（思考档位）</label>
        <label className="flex items-center gap-2"><input type="checkbox" checked={values.capabilities.supports_priority_tier} disabled={disabled || busy}
          onChange={(event) => patchCaps({ supports_priority_tier: event.target.checked })} />服务商确认支持 priority 快速服务档</label>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="grid gap-1">上下文窗口（token，可不填）
          <input inputMode="numeric" value={values.capabilities.context_window} disabled={disabled || busy} className={field}
            onChange={(event) => patchCaps({ context_window: event.target.value })} placeholder="128000" /></label>
        <label className="grid gap-1">最大输出（token，可不填）
          <input inputMode="numeric" value={values.capabilities.max_output_tokens} disabled={disabled || busy} className={field}
            onChange={(event) => patchCaps({ max_output_tokens: event.target.value })} placeholder="8192" /></label>
      </div>
    </fieldset>
    <div className="flex items-center gap-3">
      <Button type="submit" variant="primary" size="md" disabled={disabled || busy}>{submitLabel}</Button>
      {saved && <span role="status" className="text-[12.5px] text-ok">已保存</span>}
    </div>
  </form>;
}
