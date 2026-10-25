import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { ModelInfo, ProviderState } from '@atlas/backend-adapter';
import KeyManager, { cooldownText } from './KeyManager';
import ModelForm, { buildCreateRequest, buildUpdatePatch, type ModelFormValues } from './ModelForm';
import ProviderGrid from './ProviderGrid';
import ReasoningStages from './ReasoningStages';

const provider: ProviderState = {
  id: 'deepseek', label: '深度求索', hermes_provider: 'deepseek', api_mode: 'openai',
  default_base_url: 'https://api.deepseek.com/v1', docs_url: null, notes: null,
  configured: true, base_url: null, key_count: 1,
  keys: [{ id: 'k_ab12cd', label: '主密钥', cooldown_until: Math.floor(Date.now() / 1000) + 3600, last_error: '429 too many requests', request_count: 7 }],
};

const values: ModelFormValues = {
  providerBaseUrl: 'https://api.deepseek.com/v1',
  modelId: 'deepseek-v4.1-flash',
  displayName: '深度求索',
  litellmModel: 'deepseek/deepseek-v4.1-flash',
  baseUrl: '',
  maxOutput: '8192',
  price: { input: '0.1', output: '0.2', cached_input: '0.01' },
  capabilities: { context_window: '128000', max_output_tokens: '8192', supports_vision: false, supports_tools: true, supports_reasoning: true, supports_priority_tier: false },
};

describe('model settings components', () => {
  it('builds a create request from the provider form, suggesting the litellm id', () => {
    const request = buildCreateRequest(provider, { ...values, litellmModel: '' });
    expect(request).toMatchObject({
      id: 'deepseek/deepseek-v4.1-flash',
      litellm_model: 'deepseek/deepseek-v4.1-flash',
      provider: 'deepseek',
      hermes_provider: 'deepseek',
      native_model: 'deepseek-v4.1-flash',
      max_output_tokens: 8192,
      price: { input: 0.1, output: 0.2, cached_input: 0.01 },
    });
    expect(request.capabilities).toEqual({ context_window: 128000, max_output_tokens: 8192, supports_tools: true, supports_reasoning: true });
  });

  it('builds an update patch that can switch capability flags off', () => {
    const model: ModelInfo = { id: 'deepseek/deepseek-v4.1-flash', name: '深度求索', litellm_model: 'deepseek/deepseek-v4.1-flash', hermes_provider: 'deepseek' };
    const patch = buildUpdatePatch(model, { ...values, capabilities: { ...values.capabilities, supports_tools: false } });
    expect(patch.litellm_model).toBe('deepseek/deepseek-v4.1-flash');
    expect(patch.base_url).toBeNull();
    expect(patch.capabilities).toEqual({
      context_window: 128000, max_output_tokens: 8192,
      supports_vision: false, supports_tools: false, supports_reasoning: true,
    });
  });

  it('renders the provider form with the catalog default and the key pool, without echoing secrets', () => {
    const html = renderToStaticMarkup(<div>
      <ModelForm provider={provider} submitLabel="添加这家服务商的模型" onSubmit={async () => true} />
      <KeyManager keys={provider.keys} onAdd={async () => true} onRemove={() => undefined} />
    </div>);
    expect(html).toContain('添加这家服务商的模型');
    expect(html).toContain('https://api.deepseek.com/v1');
    expect(html).toContain('主密钥');
    expect(html).toContain('上次错误：429 too many requests');
    expect(html).toContain('冷却中');
    expect(html).not.toContain('value="sk');
  });

  it('shows the three reasoning stages only when the switch is on', () => {
    const config = { enabled: false, planning: 'high', execution: 'medium', verification: 'high' } as const;
    const off = renderToStaticMarkup(<ReasoningStages config={{ ...config }} onChange={() => undefined} />);
    expect(off).not.toContain('规划档');
    const on = renderToStaticMarkup(<ReasoningStages config={{ ...config, enabled: true }} onChange={() => undefined} />);
    expect(on).toContain('规划档');
    expect(on).toContain('执行档');
    expect(on).toContain('验收档');
  });

  it('lists providers with a configured badge and key count', () => {
    const html = renderToStaticMarkup(<ProviderGrid providers={[provider]} selectedId="deepseek" onSelect={() => undefined} />);
    expect(html).toContain('深度求索');
    expect(html).toContain('已配置');
    expect(html).toContain('1 把密钥');
  });

  it('formats the remaining cooldown of a key', () => {
    expect(cooldownText(null)).toBeNull();
    expect(cooldownText(Math.floor(Date.now() / 1000) - 10)).toBeNull();
    expect(cooldownText(Math.floor(Date.now() / 1000) + 5 * 60)).toContain('约剩 5 分钟');
  });
});
