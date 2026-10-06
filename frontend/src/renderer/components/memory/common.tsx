/**
 * 统一记忆页面（T12.1）各组件共享的小工具：HTTP 状态识别、分页归一化、
 * 时间与文本展示。数据请求都经 services/api 的薄封装（单一 fetch 通道），
 * 不引入第二套数据层；测试经 vi.stubGlobal 换全局 fetch（x2 测试同法）。
 */

/** 从 api() 抛出的错误信息里取回 HTTP 状态码（api() 统一格式 "HTTP 409：…"）。
 *  组件里错误通常存成字符串，所以 Error 与字符串都要认。 */
export function statusOf(exc: unknown): number | null {
  const message = exc instanceof Error ? exc.message : typeof exc === 'string' ? exc : '';
  const match = /^HTTP (\d{3})/.exec(message);
  return match ? Number(match[1]) : null;
}

/** 服务端 501 FEATURE_NOT_READY → 功能未启用（degraded，不是错误）。 */
export function isFeatureDisabled(exc: unknown): boolean {
  return statusOf(exc) === 501;
}

/** 404：代理面未挂载（memory.unified.enabled=false）→ 统一记忆未启用。 */
export function isNotEnabled(exc: unknown): boolean {
  return statusOf(exc) === 404;
}

/** 已删除的原始内容（410，契约 §6：删除后 410 或屏障状态，不回落旧缓存）。 */
export function isDeleted(exc: unknown): boolean {
  return statusOf(exc) === 410;
}

/** 取 payload 里的列表与游标：兼容 {items,next_cursor} / {records,...} / 裸数组。 */
export function pageOf(payload: unknown): { items: unknown[]; nextCursor: string | null } {
  if (Array.isArray(payload)) return { items: payload, nextCursor: null };
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const raw = record.items ?? record.records ?? record.episodes ?? record.intents;
    const cursor = record.next_cursor ?? record.nextCursor ?? null;
    return { items: Array.isArray(raw) ? raw : [], nextCursor: typeof cursor === 'string' && cursor ? cursor : null };
  }
  return { items: [], nextCursor: null };
}

export function str(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

/** content.topic 形如 "raw:原文…" —— 展示时去掉机器前缀，但不改服务端数据。 */
export function stripPrefix(value: string): string {
  return value.startsWith('raw:') ? value.slice(4) : value;
}

const TZ_RE = /[zZ]|[+-]\d\d:?\d\d$/;

/** ISO 时间 → 本地可读（后端存 UTC，无时区后缀的按 UTC 解释，与 services/api.relativeTime 同判据）。 */
export function formatMoment(value?: string | null): string {
  if (!value) return '';
  const date = new Date(TZ_RE.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
}

/** 说话人角色 → 中文（未知值原样显示，不猜）。 */
const ROLES: Record<string, string> = { USER: '用户', ASSISTANT: 'Atlas', TOOL: '工具', SYSTEM: '系统' };
export function roleLabel(value?: string | null): string {
  const key = (value ?? '').toUpperCase();
  return ROLES[key] ?? (value ?? '');
}

/** 认识论标志 → 中文徽标文案（INFERRED/DERIVED 显示「推断」—— 推断标志如实可见）。 */
export function epistemicLabel(value?: string | null): string {
  const key = (value ?? '').toUpperCase();
  if (!key) return '';
  if (key.includes('INFERRED') || key.includes('DERIVED')) return '推断';
  if (key.includes('OBSERVED')) return '实际观察';
  if (key.includes('ASSERTED')) return '用户亲述';
  return value ?? '';
}

export function locatorLabel(kind?: string | null): string {
  const key = (kind ?? '').toUpperCase();
  if (!key) return '来源';
  const KNOWN: Record<string, string> = {
    MESSAGE: '消息原文', FILE: '文件', TEXT: '文本片段',
    AUDIO_RANGE: '音频片段', IMAGE_REGION: '图片区域', VIDEO_RANGE: '视频片段',
    SCREEN: '屏幕截图', URL: '链接', WINDOW: '窗口',
  };
  return KNOWN[key] ?? kind ?? '来源';
}

/** 实体/意图/学习方法等枚举的兜底中文映射（缺的键原样显示）。 */
export function enumLabel(value?: string | null, table?: Record<string, string>): string {
  const raw = str(value);
  if (!raw) return '';
  const key = raw.toUpperCase();
  return table?.[key] ?? raw;
}

export function RevisionBadge({ revision }: { revision?: number | string | null }) {
  if (revision === null || revision === undefined || revision === '') return null;
  return <span className="tag" style={{ marginTop: 0 }}>版本 {String(revision)}</span>;
}
