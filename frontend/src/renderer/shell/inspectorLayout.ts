export type InspectorLayout = {
  version: 1;
  tab: string;
  splitTab: string | null;
  floating: boolean;
  floatPosition: { left: number; top: number } | null;
};

const STORAGE_PREFIX = 'atlas.inspector.layout.';
const DEFAULT_LAYOUT: InspectorLayout = { version: 1, tab: 'artifacts', splitTab: null, floating: false, floatPosition: null };

export function inspectorLayoutKey(conversationId: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(conversationId)}`;
}

export function moveInspectorFloat(origin: { left: number; top: number }, delta: { x: number; y: number }, viewport: { width: number; height: number }) {
  return {
    left: Math.max(0, Math.min(viewport.width - 120, origin.left + delta.x)),
    top: Math.max(0, Math.min(viewport.height - 48, origin.top + delta.y)),
  };
}

export function readInspectorLayout(conversationId: string): InspectorLayout {
  try {
    const value = JSON.parse(localStorage.getItem(inspectorLayoutKey(conversationId)) ?? 'null') as Partial<InspectorLayout> | null;
    if (!value || value.version !== 1 || typeof value.tab !== 'string') return { ...DEFAULT_LAYOUT };
    return {
      version: 1,
      tab: value.tab,
      splitTab: typeof value.splitTab === 'string' ? value.splitTab : null,
      floating: value.floating === true,
      floatPosition: value.floatPosition && Number.isFinite(value.floatPosition.left) && Number.isFinite(value.floatPosition.top)
        ? { left: Math.max(0, value.floatPosition.left), top: Math.max(0, value.floatPosition.top) }
        : null,
    };
  } catch { return { ...DEFAULT_LAYOUT }; }
}

export function writeInspectorLayout(conversationId: string, layout: InspectorLayout): void {
  try { localStorage.setItem(inspectorLayoutKey(conversationId), JSON.stringify(layout)); } catch { /* layout storage unavailable */ }
}
