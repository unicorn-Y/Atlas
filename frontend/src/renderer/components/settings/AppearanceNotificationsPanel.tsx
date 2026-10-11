import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Bell, Check, Moon, Palette, RotateCcw, Volume2 } from 'lucide-react';
import { THEMES, activateCustomTheme, applyCustomTheme, applyStoredTheme, clearCustomTheme, createCustomTheme, parseCustomTheme, readCustomTheme, type CustomTheme, type Theme } from '../../shell/themes';
import { readNotificationPreferences, saveNotificationPreferences, type NotificationKind, type NotificationPreferences } from '../../services/notificationsSettings';
import { cn } from '../../ui/cn';

export interface AppearanceNotificationsPanelProps {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  username: string;
  onSaveUsername: (username: string) => void;
  onToast?: (message: string) => void;
  section?: 'appearance' | 'notifications' | 'all';
}

const CATEGORY_LABELS: Array<[NotificationKind, string, string]> = [
  ['completion', '任务完成', '一轮工作结束时提醒'],
  ['failure', '任务失败', '运行报错或失败时提醒'],
  ['approval', '需要批准', '有需要你确认的操作时提醒'],
  ['question', '需要回复', 'Atlas 正在等你补充信息时提醒'],
  ['background', '后台活动', '后台运行状态变化时提醒'],
];

const COLOR_LABELS: Array<[keyof CustomTheme['colors'], string]> = [
  ['background', '背景'], ['foreground', '文字'], ['accent', '强调色'], ['surface', '面板'], ['codeBackground', '代码区'],
];

export default function AppearanceNotificationsPanel({ theme, onThemeChange, onToast, section = 'appearance' }: AppearanceNotificationsPanelProps) {
  const [custom, setCustom] = useState<CustomTheme>(() => readCustomTheme() ?? createCustomTheme(theme));
  const [customActive, setCustomActive] = useState(() => {
    try { return localStorage.getItem('atlas.preference.appearance') === 'custom' && readCustomTheme() !== null; } catch { return false; }
  });
  const [previewActive, setPreviewActive] = useState(false);
  const [themeError, setThemeError] = useState<string | null>(null);
  const [themeMessage, setThemeMessage] = useState<string | null>(null);
  const [notifications, setNotifications] = useState<NotificationPreferences>(readNotificationPreferences);
  const [permission, setPermission] = useState(() => typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);
  const previewState = useRef({ previewActive, customActive, theme });

  useEffect(() => {
    setCustom((current) => currentActiveBase(current, theme));
  }, [theme]);

  useEffect(() => {
    if (previewActive) applyCustomTheme(custom);
  }, [custom, previewActive]);

  useEffect(() => { previewState.current = { previewActive, customActive, theme }; }, [customActive, previewActive, theme]);
  useEffect(() => () => {
    const current = previewState.current;
    if (current.previewActive && !current.customActive) applyStoredTheme(current.theme);
  }, []);

  const updateNotifications = (update: Partial<Omit<NotificationPreferences, 'categories' | 'quietHours'>> & { categories?: Partial<NotificationPreferences['categories']>; quietHours?: Partial<NotificationPreferences['quietHours']> }) => {
    setNotifications((current) => {
      const next = { ...current, ...update, categories: update.categories ? { ...current.categories, ...update.categories } : current.categories,
        quietHours: update.quietHours ? { ...current.quietHours, ...update.quietHours } : current.quietHours };
      saveNotificationPreferences(next);
      return next;
    });
  };

  const setColor = (key: keyof CustomTheme['colors'], value: string) => {
    setCustom((current) => ({ ...current, colors: { ...current.colors, [key]: value } }));
    setThemeMessage(null);
  };

  const importTheme = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    try {
      const parsed = parseCustomTheme(JSON.parse(await file.text()) as unknown);
      setCustom(parsed);
      setThemeError(null);
      setThemeMessage(`已验证：${parsed.name}`);
    } catch (error) {
      setThemeError(error instanceof Error ? error.message : '无法读取这个主题文件');
      setThemeMessage(null);
    }
  };

  const preview = () => {
    try {
      const normalized = parseCustomTheme(custom);
      setCustom(normalized);
      applyCustomTheme(normalized);
      setPreviewActive(true);
      setThemeError(null);
      setThemeMessage('正在预览；关闭设置后会恢复已保存主题');
    } catch (error) {
      setThemeError(error instanceof Error ? error.message : '主题数据无效');
    }
  };

  const activate = () => {
    try {
      const normalized = parseCustomTheme(custom);
      onThemeChange(normalized.base);
      activateCustomTheme(normalized);
      setCustom(normalized);
      setCustomActive(true);
      setPreviewActive(true);
      setThemeError(null);
      setThemeMessage('自定义主题已保存在这台电脑');
      onToast?.('已应用自定义主题');
    } catch (error) {
      setThemeError(error instanceof Error ? error.message : '主题数据无效');
    }
  };

  const resetTheme = () => {
    clearCustomTheme();
    setCustomActive(false);
    setPreviewActive(false);
    setThemeError(null);
    setThemeMessage('已重置为内置主题');
    onThemeChange(theme);
    applyStoredTheme(theme);
    onToast?.('已重置为内置主题');
  };

  const changeBase = (base: Theme) => setCustom((current) => {
    const defaults = createCustomTheme(current.base).colors;
    const untouched = COLOR_LABELS.every(([key]) => current.colors[key] === defaults[key]);
    return { ...current, base, colors: untouched ? createCustomTheme(base).colors : current.colors };
  });

  const requestPermission = async () => {
    if (typeof Notification === 'undefined') { setPermission('unsupported'); return; }
    const next = await Notification.requestPermission().catch(() => Notification.permission);
    setPermission(next);
    onToast?.(next === 'granted' ? '已允许桌面通知' : next === 'denied' ? '系统已关闭桌面通知权限' : '尚未允许桌面通知');
  };

  return <div className="grid max-w-[760px] gap-7 text-[13px] text-fg-2">
    {(section === 'appearance' || section === 'all') && <section aria-labelledby="appearance-title" className="grid gap-4">
      <div>
        <h3 id="appearance-title" className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><Palette size={17} /> 外观</h3>
        <p className="mt-1 mb-0 text-[12.5px] text-fg-3">只保存在这台设备的本地偏好里。</p>
      </div>

      <div role="radiogroup" aria-label="内置主题" className="grid grid-cols-3 gap-3">
        {THEMES.map((item) => <button key={item.id} role="radio" aria-checked={!customActive && theme === item.id} onClick={() => {
          setCustomActive(false); setPreviewActive(false); onThemeChange(item.id); applyStoredTheme(item.id); setCustom(createCustomTheme(item.id));
        }} className={cn('card-surface rounded-2xl p-2.5 text-left transition-shadow', !customActive && theme === item.id && 'shadow-[0_0_0_2px_var(--brand)]')}>
          <span className="block h-16 rounded-xl shadow-[inset_0_0_0_1px_var(--line)]" style={{ background: item.swatch }} />
          <b className="mt-2 block px-1 text-[13px] font-medium text-fg">{item.label}</b>
          <small className="block px-1 pb-0.5 text-[11px] text-fg-3">{item.hint}</small>
        </button>)}
      </div>

      <div className="rounded-xl card-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h4 className="m-0 text-[13.5px] font-medium text-heading">自定义主题</h4><p className="mt-1 mb-0 text-[12px] text-fg-3">导入 Atlas 的版本化 JSON，也可以调整颜色后预览。所有颜色会先验证为十六进制值。</p></div>
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-fg-2 hover:bg-hover">
            <input type="file" accept="application/json,.json" className="sr-only" onChange={(event) => void importTheme(event)} />导入 JSON
          </label>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-[12px] text-fg-3">主题名称<input value={custom.name} maxLength={48} onChange={(event) => setCustom((current) => ({ ...current, name: event.target.value }))} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg" /></label>
          <label className="text-[12px] text-fg-3">基础配色<select value={custom.base} onChange={(event) => changeBase(event.target.value as Theme)} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg">{THEMES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          {COLOR_LABELS.map(([key, label]) => <label key={key} className="flex h-10 items-center justify-between rounded-lg border border-line px-2.5 text-[12px] text-fg-2">{label}<span className="flex items-center gap-2"><code className="font-mono text-[11px] text-fg-3">{custom.colors[key]}</code><input aria-label={`主题颜色：${label}`} type="color" value={custom.colors[key].slice(0, 7)} onChange={(event) => setColor(key, event.target.value)} className="size-6 cursor-pointer rounded border-0 bg-transparent p-0" /></span></label>)}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button onClick={preview} className="h-8 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover">预览</button>
          <button onClick={activate} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-brand px-3 text-[12px] font-medium text-on-primary"><Check size={14} />应用并保存</button>
          <button onClick={resetTheme} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover"><RotateCcw size={13} />重置</button>
          {customActive && <span className="text-[11px] text-brand">当前使用：{custom.name}</span>}
        </div>
        {themeError && <p role="alert" className="mt-3 mb-0 text-[12px] text-danger">{themeError}</p>}
        {themeMessage && !themeError && <p role="status" className="mt-3 mb-0 text-[12px] text-fg-3">{themeMessage}</p>}
      </div>
    </section>}

    {(section === 'notifications' || section === 'all') && <section aria-labelledby="notifications-title" className="grid gap-4">
      <div>
        <h3 id="notifications-title" className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><Bell size={17} /> 桌面通知</h3>
        <p className="mt-1 mb-0 text-[12.5px] text-fg-3">通知渠道使用本机系统权限；外部 Webhook 仍在通知服务面板单独配置。</p>
      </div>
      <div className="rounded-xl card-surface px-4">
        <SettingRow label="启用桌面通知" hint="关闭后不再发送系统通知"><input type="checkbox" checked={notifications.enabled} onChange={(event) => updateNotifications({ enabled: event.target.checked })} /></SettingRow>
        <SettingRow label="任务完成时" hint="选择 Atlas 在哪种情况下显示完成提醒"><select value={notifications.completionMode} onChange={(event) => updateNotifications({ completionMode: event.target.value as NotificationPreferences['completionMode'] })} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg"><option value="never">从不</option><option value="background">仅在后台</option><option value="always">始终</option></select></SettingRow>
        {CATEGORY_LABELS.map(([kind, label, hint]) => <SettingRow key={kind} label={label} hint={hint}><input type="checkbox" checked={notifications.categories[kind]} onChange={(event) => updateNotifications({ categories: { ...notifications.categories, [kind]: event.target.checked } })} /></SettingRow>)}
        <SettingRow label="播放系统提示音" hint="由桌面通知使用系统声音设置"><span className="flex items-center gap-2 text-[12px] text-fg-3"><Volume2 size={15} /><input type="checkbox" checked={notifications.sound} onChange={(event) => updateNotifications({ sound: event.target.checked })} /></span></SettingRow>
      </div>
      <div className="rounded-xl card-surface px-4">
        <SettingRow label="专注模式" hint="专注模式开启时，暂停所有 Atlas 桌面通知"><span className="flex items-center gap-2"><Moon size={15} className="text-fg-3" /><input type="checkbox" checked={notifications.focusMode} onChange={(event) => updateNotifications({ focusMode: event.target.checked })} /></span></SettingRow>
        <SettingRow label="静默时段" hint="在此本地时间段内暂停通知"><input type="checkbox" checked={notifications.quietHours.enabled} onChange={(event) => updateNotifications({ quietHours: { enabled: event.target.checked } })} /></SettingRow>
        {notifications.quietHours.enabled && <div className="flex flex-wrap items-center gap-2 border-t border-line py-3 text-[12px] text-fg-3">
          <span>从</span><input aria-label="静默开始时间" type="time" value={notifications.quietHours.start} onChange={(event) => updateNotifications({ quietHours: { start: event.target.value } })} className="h-8 rounded-lg border border-line bg-surface px-2 text-fg" />
          <span>到</span><input aria-label="静默结束时间" type="time" value={notifications.quietHours.end} onChange={(event) => updateNotifications({ quietHours: { end: event.target.value } })} className="h-8 rounded-lg border border-line bg-surface px-2 text-fg" />
        </div>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl card-surface px-4 py-3">
        <div><div className="text-[12.5px] text-fg">系统权限：{permissionLabel(permission)}</div><small className="mt-0.5 block text-[11.5px] text-fg-3">Atlas 无法覆盖操作系统或浏览器的通知权限。</small></div>
        {permission !== 'granted' && permission !== 'unsupported' && <button onClick={() => void requestPermission()} className="h-8 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover">请求权限</button>}
      </div>
    </section>}
  </div>;
}

function currentActiveBase(custom: CustomTheme, theme: Theme): CustomTheme {
  return custom.base === theme ? custom : { ...custom, ...(!readCustomTheme() ? createCustomTheme(theme) : {}) };
}

function permissionLabel(value: string): string {
  return value === 'granted' ? '已允许' : value === 'denied' ? '已拒绝' : value === 'unsupported' ? '此环境不支持' : '尚未允许';
}

function SettingRow({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return <div className="flex min-h-[58px] items-center justify-between gap-4 border-b border-line py-2.5 last:border-0">
    <div><div className="text-[12.5px] text-fg">{label}</div><small className="mt-0.5 block text-[11.5px] text-fg-3">{hint}</small></div>
    {children}
  </div>;
}
