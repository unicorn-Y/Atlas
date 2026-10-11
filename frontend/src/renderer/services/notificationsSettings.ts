export type NotificationKind = 'completion' | 'failure' | 'approval' | 'question' | 'background';
export type CompletionNotificationMode = 'never' | 'background' | 'always';

export interface NotificationPreferences {
  enabled: boolean;
  categories: Record<NotificationKind, boolean>;
  completionMode: CompletionNotificationMode;
  sound: boolean;
  focusMode: boolean;
  quietHours: { enabled: boolean; start: string; end: string };
}

const KEY = 'atlas.preference.notifications';
export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  enabled: true,
  categories: { completion: true, failure: true, approval: true, question: true, background: false },
  completionMode: 'background',
  sound: true,
  focusMode: false,
  quietHours: { enabled: false, start: '22:00', end: '08:00' },
};

function readRaw(): unknown {
  try {
    const saved = localStorage.getItem(KEY);
    return saved ? JSON.parse(saved) as unknown : null;
  } catch { return null; }
}

export function readNotificationPreferences(): NotificationPreferences {
  const saved = readRaw();
  if (!saved || typeof saved !== 'object') return { ...DEFAULT_NOTIFICATION_PREFERENCES, categories: { ...DEFAULT_NOTIFICATION_PREFERENCES.categories }, quietHours: { ...DEFAULT_NOTIFICATION_PREFERENCES.quietHours } };
  const value = saved as Partial<NotificationPreferences>;
  const categories = value.categories && typeof value.categories === 'object' ? value.categories : {};
  const quietHours = value.quietHours && typeof value.quietHours === 'object' ? value.quietHours : {};
  return {
    enabled: typeof value.enabled === 'boolean' ? value.enabled : DEFAULT_NOTIFICATION_PREFERENCES.enabled,
    categories: Object.fromEntries(Object.keys(DEFAULT_NOTIFICATION_PREFERENCES.categories).map((kind) => [
      kind,
      typeof (categories as Record<string, unknown>)[kind] === 'boolean'
        ? (categories as Record<string, boolean>)[kind]
        : DEFAULT_NOTIFICATION_PREFERENCES.categories[kind as NotificationKind],
    ])) as Record<NotificationKind, boolean>,
    completionMode: value.completionMode === 'never' || value.completionMode === 'always' ? value.completionMode : 'background',
    sound: typeof value.sound === 'boolean' ? value.sound : DEFAULT_NOTIFICATION_PREFERENCES.sound,
    focusMode: typeof value.focusMode === 'boolean' ? value.focusMode : false,
    quietHours: {
      enabled: typeof (quietHours as Record<string, unknown>).enabled === 'boolean' ? (quietHours as NotificationPreferences['quietHours']).enabled : false,
      start: isTime((quietHours as Record<string, unknown>).start) ? (quietHours as NotificationPreferences['quietHours']).start : '22:00',
      end: isTime((quietHours as Record<string, unknown>).end) ? (quietHours as NotificationPreferences['quietHours']).end : '08:00',
    },
  };
}

export function saveNotificationPreferences(value: NotificationPreferences): void {
  try { localStorage.setItem(KEY, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function isTime(value: unknown): value is string { return typeof value === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value); }

function isQuietTime(now: Date, start: string, end: string): boolean {
  const current = now.getHours() * 60 + now.getMinutes();
  const [startHour, startMinute] = start.split(':').map(Number);
  const [endHour, endMinute] = end.split(':').map(Number);
  const from = startHour * 60 + startMinute;
  const to = endHour * 60 + endMinute;
  if (from === to) return true;
  return from < to ? current >= from && current < to : current >= from || current < to;
}

/** Used by Atlas's existing native notification hook before constructing a desktop alert. */
export function shouldNotify(kind: NotificationKind, now = new Date(), focused = typeof document !== 'undefined' && document.hasFocus()): boolean {
  const preferences = readNotificationPreferences();
  if (!preferences.enabled || !preferences.categories[kind] || preferences.focusMode) return false;
  if (preferences.quietHours.enabled && isQuietTime(now, preferences.quietHours.start, preferences.quietHours.end)) return false;
  if (kind === 'completion') {
    if (preferences.completionMode === 'never') return false;
    return preferences.completionMode === 'always' || !focused;
  }
  return !focused;
}

export const notificationIsSilent = () => !readNotificationPreferences().sound;
