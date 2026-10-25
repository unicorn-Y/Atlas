import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Bell, Check, Moon, Palette, RotateCcw, Volume2 } from 'lucide-react';
import { THEMES, activateCustomTheme, applyCustomTheme, applyStoredTheme, clearCustomTheme, createCustomTheme, parseCustomTheme, parseThemeDirectoryFiles, readCustomTheme, type CustomTheme, type Theme } from '../../shell/themes';
import { readNotificationPreferences, saveNotificationPreferences, type NotificationKind, type NotificationPreferences } from '../../services/notificationsSettings';
import { cn } from '../../ui/cn';
import { readLocale, saveLocale, t } from '../../services/i18n';

export interface AppearanceNotificationsPanelProps {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  username: string;
  onSaveUsername: (username: string) => void;
  onToast?: (message: string) => void;
  section?: 'appearance' | 'notifications' | 'all';
  speechVoice?: string; speechVoices?: SpeechSynthesisVoice[]; speechRate?: number;
  onSpeechVoiceChange?: (value: string) => void; onSpeechRateChange?: (value: number) => void; onSpeechPreview?: () => void;
}

const CATEGORY_LABELS: Array<[NotificationKind, string, string]> = [
  ['completion', '任务完成', '一轮工作结束时提醒'],
  ['failure', '任务失败', '运行报错或失败时提醒'],
  ['approval', '需要批准', '有需要你确认的操作时提醒'],
  ['question', '需要回复', 'Atlas 正在等你补充信息时提醒'],
  ['background', '后台活动', '后台运行状态变化时提醒'],
];

const COLOR_LABELS: Array<[keyof CustomTheme['colors'], string]> = [
  ['background', '背景'], ['foreground', '文字'], ['accent', '强调色'], ['surface', '面板'], ['codeBackground', '代码区'], ['promptBackground', 'Session prompt 背景'], ['promptForeground', 'Session prompt 文字'],
];

export default function AppearanceNotificationsPanel({ theme, onThemeChange, onToast, section = 'appearance', speechVoice = '', speechVoices = [], speechRate = 1, onSpeechVoiceChange, onSpeechRateChange, onSpeechPreview }: AppearanceNotificationsPanelProps) {
  const [custom, setCustom] = useState<CustomTheme>(() => readCustomTheme() ?? createCustomTheme(theme));
  const [customActive, setCustomActive] = useState(() => {
    try { return localStorage.getItem('atlas.preference.appearance') === 'custom' && readCustomTheme() !== null; } catch { return false; }
  });
  const [previewActive, setPreviewActive] = useState(false);
  const [themeError, setThemeError] = useState<string | null>(null);
  const [themeMessage, setThemeMessage] = useState<string | null>(null);
  const [directoryThemes, setDirectoryThemes] = useState<CustomTheme[]>([]);
  const [directorySelection, setDirectorySelection] = useState(0);
  const [notifications, setNotifications] = useState<NotificationPreferences>(readNotificationPreferences);
  const [locale, setLocale] = useState(readLocale);
  const [vimEnabled, setVimEnabled] = useState(() => { try { return localStorage.getItem('atlas.preference.vim-mode') === 'true'; } catch { return false; } });
  const [typography, setTypography] = useState(() => {
    try { return JSON.parse(localStorage.getItem('atlas.preference.u4-appearance') ?? '{}') as { fontSize?: number; monoFont?: string; fontFamily?: string }; }
    catch { return {}; }
  });
  const tx = (source: string) => t(source, locale);
  const [permission, setPermission] = useState(() => typeof Notification === 'undefined' ? 'unsupported' : Notification.permission);
  const [codeTheme, setCodeTheme] = useState(() => { try { return localStorage.getItem('atlas.code-theme') || 'auto'; } catch { return 'auto'; } });
  const previewState = useRef({ previewActive, customActive, theme });

  useEffect(() => {
    setCustom((current) => currentActiveBase(current, theme));
  }, [theme]);

  useEffect(() => {
    if (previewActive) applyCustomTheme(custom);
  }, [custom, previewActive]);

  useEffect(() => { previewState.current = { previewActive, customActive, theme }; }, [customActive, previewActive, theme]);
  useEffect(() => {
    const resolved = codeTheme === 'auto' ? (theme === 'dark' ? 'dark-vivid' : 'light-soft') : codeTheme;
    document.documentElement.dataset.codeTheme = resolved;
    try { localStorage.setItem('atlas.code-theme', codeTheme); } catch { /* storage unavailable */ }
  }, [codeTheme, theme]);
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty('--atlas-font-size', `${typography.fontSize ?? 16}px`);
    root.style.setProperty('--atlas-mono-font', typography.monoFont?.trim() ? `${typography.monoFont}, Consolas, monospace` : 'Consolas, monospace');
    root.style.setProperty('--atlas-font', typography.fontFamily?.trim() || 'inherit');
  }, []);
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
  const updateTypography = (patch: Partial<typeof typography>) => {
    const next = { ...typography, ...patch }; setTypography(next);
    try { localStorage.setItem('atlas.preference.u4-appearance', JSON.stringify({ ...JSON.parse(localStorage.getItem('atlas.preference.u4-appearance') ?? '{}'), ...next })); } catch { /* local-only preference */ }
    const root = document.documentElement;
    root.style.setProperty('--atlas-font-size', `${next.fontSize ?? 16}px`);
    root.style.setProperty('--atlas-mono-font', next.monoFont?.trim() ? `${next.monoFont}, Consolas, monospace` : 'Consolas, monospace');
    root.style.setProperty('--atlas-font', next.fontFamily?.trim() || 'inherit');
  };
  const changeLocale = (value: 'zh-CN' | 'en-US') => {
    setLocale(value); saveLocale(value);
  };
  const setNotificationLevel = (level: NotificationPreferences['level']) => {
    updateNotifications({ level, enabled: level !== 'off',
      completionMode: level === 'all' ? 'always' : level === 'off' ? 'never' : 'background',
      categories: level === 'all'
        ? { completion: true, failure: true, approval: true, question: true, background: true }
        : { completion: level === 'attention', failure: level === 'attention', approval: level === 'attention', question: level === 'attention', background: false } });
  };
  const sendTestNotification = async () => {
    if (typeof Notification === 'undefined') { onToast?.('当前环境不支持系统通知'); return; }
    let currentPermission = Notification.permission;
    if (currentPermission === 'default') currentPermission = await Notification.requestPermission();
    setPermission(currentPermission);
    if (currentPermission !== 'granted') { onToast?.('系统通知权限未开启'); return; }
    new Notification('Atlas 测试通知', { body: '系统通知可以正常显示。' });
    onToast?.('已发送测试通知');
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

  const scanThemeDirectory = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []).filter((file) => file.name.toLowerCase().endsWith('.json'));
    event.target.value = '';
    const parsed = parseThemeDirectoryFiles(await Promise.all(files.map(async (file) => ({ name: file.webkitRelativePath || file.name, text: await file.text() }))));
    const scanned = parsed.themes;
    setDirectoryThemes(scanned);
    setDirectorySelection(0);
    if (scanned.length) {
      setCustom(scanned[0]); applyCustomTheme(scanned[0]); setPreviewActive(true); setThemeError(null);
      setThemeMessage(`扫描到 ${scanned.length} 个主题；当前预览「${scanned[0].name}」${parsed.rejected.length ? `，${parsed.rejected.length} 个 JSON 未通过校验` : ''}`);
    } else {
      setThemeError(files.length ? `未发现有效主题 JSON：${parsed.rejected.slice(0, 3).join('、')}` : '所选目录中没有 JSON 主题文件');
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
        <h3 id="appearance-title" className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><Palette size={17} /> {tx('外观与语音')}</h3>
        <p className="mt-1 mb-0 text-[12.5px] text-fg-3">{tx('只保存在这台设备的本地偏好里。')}</p>
      </div>

      <div className="rounded-xl card-surface px-4">
        <SettingRow label={tx('界面语言')} hint={locale === 'en-US' ? 'UI language; preference is stored locally.' : '切换 Atlas 界面语言；仅影响这台设备。'}><select aria-label={tx('界面语言')} value={locale} onChange={(event) => changeLocale(event.target.value as 'zh-CN' | 'en-US')} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg"><option value="zh-CN">简体中文</option><option value="en-US">English</option></select></SettingRow>
        <SettingRow label={tx('界面字号')} hint={locale === 'en-US' ? 'Scale the interface text.' : '调整应用界面文字大小。'}><select aria-label={tx('界面字号')} value={typography.fontSize ?? 16} onChange={(event) => updateTypography({ fontSize: Number(event.target.value) })} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg">{[14, 15, 16, 17, 18].map((size) => <option key={size} value={size}>{size}px</option>)}</select></SettingRow>
        <SettingRow label={tx('界面字体')} hint={locale === 'en-US' ? 'Blank uses the system default.' : '留空时使用系统默认字体。'}><input aria-label={tx('界面字体')} value={typography.fontFamily ?? ''} onChange={(event) => updateTypography({ fontFamily: event.target.value })} placeholder={tx('系统默认')} className="h-8 max-w-[230px] rounded-lg border border-line bg-surface px-2 text-[12px] text-fg" /></SettingRow>
        <SettingRow label={tx('等宽字体')} hint={locale === 'en-US' ? 'Used for code and terminal text.' : '用于代码和终端文字。'}><input aria-label={tx('等宽字体')} value={typography.monoFont ?? ''} onChange={(event) => updateTypography({ monoFont: event.target.value })} placeholder="Consolas" className="h-8 max-w-[230px] rounded-lg border border-line bg-surface px-2 text-[12px] text-fg" /></SettingRow>
      </div>

      <div className="rounded-xl card-surface px-4">
        <SettingRow label={tx('Vim 模式')} hint={locale === 'en-US' ? 'Use Normal, Insert and Visual modes in the message editor.' : '在消息输入框启用普通、插入和可视模式。'}><input type="checkbox" aria-label={tx('Vim 模式')} checked={vimEnabled} onChange={(event) => {
          const enabled = event.target.checked; setVimEnabled(enabled);
          try { localStorage.setItem('atlas.preference.vim-mode', String(enabled)); } catch { /* local preference */ }
          window.dispatchEvent(new Event('atlas:vim-toggle'));
        }} /></SettingRow>
        {vimEnabled && <p className="mb-3 mt-0 text-[11.5px] leading-5 text-fg-3">{locale === 'en-US' ? 'NORMAL: h/j/k/l, w/b/e, 0/$; i/a/A/I/o/O enters INSERT; v selects; d/y/c with a motion or doubled (dd/yy/cc); x deletes, p/P pastes, u undoes. Enter still sends.' : '普通模式：h/j/k/l 移动，w/b/e 按词移动，0/$ 到行首尾；i/a/A/I/o/O 进入插入模式；v 选择；d/y/c 配合移动或连按两次（dd/yy/cc）；x 删除，p/P 粘贴，u 撤销。Enter 仍发送消息。'}</p>}
      </div>

      <div className="rounded-xl card-surface px-4">
        <SettingRow label={tx('主题')} hint={locale === 'en-US' ? 'System mode follows Windows; other modes stay locked until changed.' : '跟随系统会同步 Windows 明暗；选择其他主题后会锁定当前主题。'}><select aria-label={tx('主题')} value={readThemeMode() === 'system' ? 'system' : theme} onChange={(event) => {
          const value = event.target.value;
          if (value === 'system') {
            try { localStorage.setItem('atlas.preference.theme-mode', 'system'); } catch { /* local preference */ }
            const query = matchMedia('(prefers-color-scheme: dark)'); onThemeChange(query.matches ? 'dark' : 'light');
          } else {
            try { localStorage.setItem('atlas.preference.theme-mode', 'manual'); } catch { /* local preference */ }
            setCustomActive(false); setPreviewActive(false); onThemeChange(value as Theme); applyStoredTheme(value as Theme); setCustom(createCustomTheme(value as Theme));
          }
        }} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg"><option value="system">{tx('跟随系统')}</option><option value="light">{tx('明亮')}</option><option value="dark">{tx('暗色')}</option><option value="aurora">{tx('晨光')}</option></select></SettingRow>
      </div>

      <div className="rounded-xl card-surface px-4">
        <SettingRow label="代码语法高亮" hint="自动会跟随明暗主题；也可以固定选择配色。">
          <select aria-label="代码语法高亮主题" value={codeTheme} onChange={(event) => setCodeTheme(event.target.value)} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg">
            <option value="auto">自动跟随外观</option><option value="light-soft">浅色 · 柔和</option><option value="light-vivid">浅色 · 鲜明</option><option value="dark-soft">深色 · 柔和</option><option value="dark-vivid">深色 · 鲜明</option>
          </select>
        </SettingRow>
        <pre className="mb-3 overflow-auto rounded-lg bg-code p-3"><code className="hljs language-typescript"><span className="hljs-keyword">const</span> label = <span className="hljs-string">'Atlas'</span>;</code></pre>
      </div>
      <div className="rounded-xl card-surface px-4">
        <SettingRow label="朗读音色" hint="选择系统提供的中文语音。"><select aria-label="设置朗读音色" value={speechVoice} onChange={(event) => onSpeechVoiceChange?.(event.target.value)} className="max-w-[230px] h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg"><option value="">系统默认</option>{speechVoices.filter((voice) => voice.lang.toLowerCase().startsWith('zh')).map((voice) => <option key={voice.name} value={voice.name}>{voice.name}</option>)}</select></SettingRow>
        <SettingRow label="朗读语速" hint="速度范围 0.8× 至 1.5×。"><select aria-label="设置朗读语速" value={speechRate} onChange={(event) => onSpeechRateChange?.(Number(event.target.value))} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg">{[0.8, 1, 1.2, 1.5].map((rate) => <option key={rate} value={rate}>{rate}×</option>)}</select></SettingRow>
        <div className="flex justify-end border-t border-line py-2"><button type="button" onClick={onSpeechPreview} className="rounded-md px-2.5 py-1.5 text-[12px] text-brand hover:bg-hover">试听当前音色</button></div>
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
          <label className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-fg-2 hover:bg-hover">
            <input type="file" multiple className="sr-only" {...({ webkitdirectory: '', directory: '' } as Record<string, string>)} onChange={(event) => void scanThemeDirectory(event)} />扫描主题目录
          </label>
        </div>
        {directoryThemes.length > 0 && <label className="mt-3 block max-w-[380px] text-[12px] text-fg-3">目录主题预览<select aria-label="目录主题预览" value={directorySelection} onChange={(event) => {
          const index = Number(event.target.value); const next = directoryThemes[index]; if (!next) return;
          setDirectorySelection(index);
          setCustom(next); applyCustomTheme(next); setPreviewActive(true); setThemeError(null); setThemeMessage(`正在预览目录主题「${next.name}」；应用并保存后生效`);
        }} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2 text-fg">{directoryThemes.map((item, index) => <option key={`${item.name}-${index}`} value={index}>{item.name}</option>)}</select></label>}
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="text-[12px] text-fg-3">主题名称<input value={custom.name} maxLength={48} onChange={(event) => setCustom((current) => ({ ...current, name: event.target.value }))} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg" /></label>
          <label className="text-[12px] text-fg-3">基础配色<select value={custom.base} onChange={(event) => changeBase(event.target.value as Theme)} className="mt-1 block h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-[13px] text-fg">{THEMES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
          {COLOR_LABELS.map(([key, label]) => <label key={key} className="flex h-10 items-center justify-between rounded-lg border border-line px-2.5 text-[12px] text-fg-2">{label}<span className="flex items-center gap-2"><code className="font-mono text-[11px] text-fg-3">{custom.colors[key]}</code><input aria-label={`主题颜色：${label}`} type="color" value={custom.colors[key].slice(0, 7)} onChange={(event) => setColor(key, event.target.value)} className="size-6 cursor-pointer rounded border-0 bg-transparent p-0" /></span></label>)}
        </div>
        <div aria-label="Session prompt 颜色预览" className="mt-3 max-w-[520px] rounded-xl px-4 py-3 text-[13px]" style={{ backgroundColor: custom.colors.promptBackground, color: custom.colors.promptForeground }}>
          <small className="mb-1 block opacity-65">Session prompt preview</small>这是会话 prompt 气泡文字的颜色预览。
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
        <SettingRow label="通知级别" hint="需要关注的事件、全部事件或关闭通知"><select aria-label="通知级别" value={notifications.level} onChange={(event) => setNotificationLevel(event.target.value as NotificationPreferences['level'])} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg"><option value="attention">只在需要我时</option><option value="all">全部</option><option value="off">关闭</option></select></SettingRow>
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
      <div className="flex items-center justify-between gap-3 rounded-xl card-surface px-4 py-3"><span className="text-[12.5px] text-fg-2">确认系统是否允许 Atlas 显示通知</span><button type="button" onClick={() => void sendTestNotification()} className="h-8 rounded-lg border border-line px-3 text-[12px] text-fg-2 hover:bg-hover">发送测试通知</button></div>
    </section>}
  </div>;
}

function currentActiveBase(custom: CustomTheme, theme: Theme): CustomTheme {
  return custom.base === theme ? custom : { ...custom, ...(!readCustomTheme() ? createCustomTheme(theme) : {}) };
}

function permissionLabel(value: string): string {
  return value === 'granted' ? '已允许' : value === 'denied' ? '已拒绝' : value === 'unsupported' ? '此环境不支持' : '尚未允许';
}

function readThemeMode(): string {
  try { return localStorage.getItem('atlas.preference.theme-mode') === 'system' ? 'system' : 'manual'; }
  catch { return 'manual'; }
}

function SettingRow({ label, hint, children }: { label: string; hint: string; children: React.ReactNode }) {
  return <div data-setting-row data-setting-label={label} data-setting-terms={hint} className="flex min-h-[58px] items-center justify-between gap-4 border-b border-line py-2.5 last:border-0">
    <div><div className="text-[12.5px] text-fg">{label}</div><small className="mt-0.5 block text-[11.5px] text-fg-3">{hint}</small></div>
    {children}
  </div>;
}
