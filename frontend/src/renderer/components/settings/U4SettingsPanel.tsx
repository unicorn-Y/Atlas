import { useEffect, useState, type ChangeEvent } from 'react';
import { api } from '../../services/api';
import type { Theme } from '../../shell/themes';

interface Preset { id: string; label: string; workspace?: string; model?: string; reasoning_effort?: string; env?: Record<string, string>; skills?: string[] }
interface Props {
  apiBaseUrl: string; models: Array<{ id: string; name?: string }>; currentModel: string; theme: Theme;
  onThemeChange: (theme: Theme) => void; onApplyPreset: (preset: Preset) => void; onToast: (text: string) => void; onImported: () => void;
}
const channels = ['telegram', 'discord', 'slack', 'feishu', 'wecom'];
const settingKey = 'atlas.preference.u4-appearance';

export default function U4SettingsPanel({ apiBaseUrl, models, currentModel, theme, onThemeChange, onApplyPreset, onToast, onImported }: Props) {
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [presets, setPresets] = useState<Preset[]>([]);
  const [preset, setPreset] = useState<Preset>({ id: '', label: '', workspace: '', model: currentModel, reasoning_effort: '', env: {}, skills: [] });
  const [envText, setEnvText] = useState('{}');
  const [skillText, setSkillText] = useState('');
  const [push, setPush] = useState({ enabled: false, channel: 'telegram', chat_id: '', events: { completion: true, approval: true, failure: true } });
  const [appearance, setAppearance] = useState(() => {
    try { return JSON.parse(localStorage.getItem(settingKey) ?? '{}') as { fontSize?: number; monoFont?: string; fontFamily?: string; language?: string; system?: boolean }; }
    catch { return {}; }
  });
  const [notice, setNotice] = useState('');
  const refresh = () => {
    void api<{ presets: Preset[] }>(apiBaseUrl, '/api/u4/presets').then((value) => setPresets(value.presets)).catch(() => setPresets([]));
  };
  useEffect(() => {
    refresh();
    void api<Record<string, any>>(apiBaseUrl, '/api/u4/settings').then((value) => {
      setSettings(value); if (value.mobile_push) setPush(value.mobile_push);
    }).catch(() => undefined);
  }, [apiBaseUrl]);
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--atlas-font-size', `${appearance.fontSize ?? 16}px`);
    root.style.setProperty('--atlas-mono-font', appearance.monoFont?.trim() ? `${appearance.monoFont}, Consolas, monospace` : 'Consolas, monospace');
    root.style.setProperty('--atlas-font', appearance.fontFamily?.trim() || 'inherit');
    root.lang = appearance.language === 'en' ? 'en' : 'zh-CN';
    document.body.dataset.language = root.lang;
  }, [appearance]);
  useEffect(() => {
    if (!appearance.system) return;
    const query = matchMedia('(prefers-color-scheme: dark)');
    const update = () => onThemeChange(query.matches ? 'dark' : 'light');
    query.addEventListener('change', update); update();
    return () => query.removeEventListener('change', update);
  }, [appearance.system, onThemeChange]);
  const saveAppearance = (patch: Record<string, unknown>) => {
    const next = { ...appearance, ...patch };
    setAppearance(next); localStorage.setItem(settingKey, JSON.stringify(next));
    if (patch.system === true) {
      const update = () => onThemeChange(matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
      update();
    } else if (patch.system === false) localStorage.setItem('atlas.preference.theme-mode', 'manual');
  };
  const saveAdvisor = async (value: string) => {
    const next = { ...settings, advisor_model: value };
    try { const saved = await api<Record<string, any>>(apiBaseUrl, '/api/u4/settings', { method: 'PUT', json: { advisor_model: value } }); setSettings({ ...next, ...saved }); onToast(value ? '顾问模型已保存' : '已清除顾问模型'); }
    catch (error) { onToast(`保存顾问模型失败：${String(error)}`); }
  };
  const savePreset = async () => {
    try {
      const env = JSON.parse(envText) as unknown;
      if (!env || Array.isArray(env) || typeof env !== 'object' || Object.values(env).some((value) => typeof value !== 'string')) throw new Error('环境变量必须是字符串键值对象');
      const saved = await api<Preset>(apiBaseUrl, '/api/u4/presets', { method: 'POST', json: { ...preset, env, skills: skillText.split(',').map((name) => name.trim()).filter(Boolean) } });
      setPresets((current) => [...current.filter((item) => item.id !== saved.id), saved]); setPreset({ id: '', label: '', workspace: '', model: currentModel, reasoning_effort: '', env: {}, skills: [] }); setEnvText('{}'); setSkillText(''); onToast('会话预设已保存');
    } catch (error) { onToast(`无法保存预设：${error instanceof Error ? error.message : String(error)}`); }
  };
  const importChatGPT = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; event.target.value = ''; if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const result = await api<{ imported: number; skipped?: number; conversations: Array<{ title: string; messages: number }> }>(apiBaseUrl, '/api/u4/import/chatgpt', { method: 'POST', json: { conversations: parsed } });
      setNotice(`导入 ${result.imported} 个 ChatGPT 会话；共 ${result.conversations.reduce((sum, item) => sum + item.messages, 0)} 条消息${result.skipped ? `；跳过 ${result.skipped} 个已导入过的会话` : ''}。`); onToast('ChatGPT 历史已导入'); onImported();
    } catch (error) { setNotice(error instanceof Error ? error.message : '无法导入文件'); }
  };
  const savePush = async () => {
    try { await api(apiBaseUrl, '/api/u4/settings', { method: 'PUT', json: { mobile_push: push } }); onToast('手机推送设置已保存'); }
    catch (error) { onToast(`保存推送设置失败：${String(error)}`); }
  };

  return <div className="grid max-w-[760px] gap-6 text-[13px] text-fg-2">
    <section className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[14px] font-medium text-heading">顾问模型</h4>
      <p className="my-2 text-[12px] text-fg-3">Agent 可用「请教顾问」工具获取第二意见。</p>
      <select aria-label="顾问模型" value={settings.advisor_model ?? ''} onChange={(event) => void saveAdvisor(event.target.value)} className="h-9 w-full max-w-[420px] rounded-lg border border-line bg-surface px-2 text-fg">
        <option value="">不使用顾问</option>{models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
      </select>
    </section>
    <section className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[14px] font-medium text-heading">会话预设</h4>
      {presets.map((item) => <div key={item.id} className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-line p-2.5"><b className="mr-auto">{item.label}</b><span className="text-[11px] text-fg-3">{item.workspace || '默认工作区'} · {item.model || '当前模型'}</span><button onClick={() => onApplyPreset(item)} className="rounded-md bg-brand px-2.5 py-1.5 text-[11.5px] text-on-primary">应用</button><button onClick={() => void api(apiBaseUrl, `/api/u4/presets/${item.id}`, { method: 'DELETE' }).then(refresh)} className="rounded-md border border-line px-2.5 py-1.5 text-[11.5px]">删除</button></div>)}
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <input aria-label="预设名称" value={preset.label} onChange={(event) => setPreset({ ...preset, label: event.target.value })} placeholder="预设名称" className="h-9 rounded-lg border border-line bg-surface px-2.5 text-fg" />
        <input aria-label="预设工作目录" value={preset.workspace ?? ''} onChange={(event) => setPreset({ ...preset, workspace: event.target.value })} placeholder="工作目录" className="h-9 rounded-lg border border-line bg-surface px-2.5 text-fg" />
        <select aria-label="预设模型" value={preset.model ?? currentModel} onChange={(event) => setPreset({ ...preset, model: event.target.value })} className="h-9 rounded-lg border border-line bg-surface px-2.5 text-fg">{models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}</select>
        <select aria-label="预设推理强度" value={preset.reasoning_effort ?? ''} onChange={(event) => setPreset({ ...preset, reasoning_effort: event.target.value })} className="h-9 rounded-lg border border-line bg-surface px-2.5 text-fg"><option value="">默认推理强度</option>{['low','medium','high','xhigh'].map((value) => <option key={value}>{value}</option>)}</select>
        <input aria-label="预设环境变量 JSON" value={envText} onChange={(event) => setEnvText(event.target.value)} placeholder='环境变量 JSON，如 {"NODE_ENV":"test"}' className="h-9 rounded-lg border border-line bg-surface px-2.5 font-mono text-fg sm:col-span-2" />
        <input aria-label="预设默认技能" value={skillText} onChange={(event) => setSkillText(event.target.value)} placeholder="默认技能，逗号分隔" className="h-9 rounded-lg border border-line bg-surface px-2.5 text-fg sm:col-span-2" />
      </div>
      <button onClick={() => void savePreset()} className="mt-3 h-8 rounded-lg bg-brand px-3 text-[12px] text-on-primary">保存会话预设</button>
    </section>
    <section className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[14px] font-medium text-heading">导入 ChatGPT 历史</h4><p className="my-2 text-[12px] text-fg-3">选择官方数据导出包内的 conversations.json。</p>
      <label className="inline-flex h-8 cursor-pointer items-center rounded-lg border border-line px-3 text-[12px]">选择 conversations.json<input type="file" accept="application/json,.json" className="sr-only" onChange={(event) => void importChatGPT(event)} /></label>
      {notice && <p role="status" className="mt-2 mb-0 text-[12px]">{notice}</p>}
    </section>
    <section className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[14px] font-medium text-heading">手机推送</h4><p className="my-2 text-[12px] text-fg-3">复用已配置的 Atlas 渠道和 chat ID。</p>
      <label className="flex items-center gap-2"><input type="checkbox" checked={push.enabled} onChange={(event) => setPush({ ...push, enabled: event.target.checked })} />启用推送</label>
      <div className="mt-2 flex flex-wrap gap-2"><select aria-label="推送渠道" value={push.channel} onChange={(event) => setPush({ ...push, channel: event.target.value })} className="h-9 rounded-lg border border-line bg-surface px-2 text-fg">{channels.map((name) => <option key={name}>{name}</option>)}</select><input aria-label="推送 chat ID" value={push.chat_id} onChange={(event) => setPush({ ...push, chat_id: event.target.value })} placeholder="渠道 chat ID" className="h-9 min-w-[220px] flex-1 rounded-lg border border-line bg-surface px-2.5 text-fg" /></div>
      <div className="mt-3 flex flex-wrap gap-4">{([["completion","任务完成"],["approval","需要确认"],["failure","出错"]] as const).map(([key, label]) => <label key={key} className="flex items-center gap-1.5"><input type="checkbox" checked={push.events[key]} onChange={(event) => setPush({ ...push, events: { ...push.events, [key]: event.target.checked } })} />{label}</label>)}</div>
      <button onClick={() => void savePush()} className="mt-3 h-8 rounded-lg bg-brand px-3 text-[12px] text-on-primary">保存手机推送</button>
    </section>
    <section className="rounded-xl card-surface p-4">
      <h4 className="m-0 text-[14px] font-medium text-heading">外观与语言</h4>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label>主题<select value={appearance.system ? 'system' : theme} onChange={(event) => {
          const system = event.target.value === 'system'; saveAppearance({ system });
          localStorage.setItem('atlas.preference.theme-mode', system ? 'system' : 'manual');
          if (!system) onThemeChange(event.target.value as Theme);
        }} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2 text-fg"><option value="system">跟随系统</option><option value="light">明亮</option><option value="dark">暗色</option><option value="aurora">晨光</option></select></label>
        <label>界面字号<select value={appearance.fontSize ?? 16} onChange={(event) => saveAppearance({ fontSize: Number(event.target.value) })} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2 text-fg">{[14,15,16,17,18].map((size) => <option key={size} value={size}>{size}px</option>)}</select></label>
        <label>等宽字体<input value={appearance.monoFont ?? ''} onChange={(event) => saveAppearance({ monoFont: event.target.value })} placeholder="Consolas" className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-fg" /></label>
        <label>界面字体<input value={appearance.fontFamily ?? ''} onChange={(event) => saveAppearance({ fontFamily: event.target.value })} placeholder="系统默认" className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-fg" /></label>
        <label>界面语言<select value={appearance.language ?? 'zh'} onChange={(event) => saveAppearance({ language: event.target.value })} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2 text-fg"><option value="zh">简体中文</option><option value="en">English</option></select></label>
      </div>
      {appearance.language === 'en' && <p className="mb-0 mt-2 text-[11px] text-fg-3">English locale is saved and applied to supported views; some Atlas legacy copy remains Chinese.</p>}
    </section>
  </div>;
}
