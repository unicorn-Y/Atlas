export type InspectorLayout = {
  version: 1;
  tab: string;
  splitTab: string | null;
  floating: boolean;
};

const STORAGE_PREFIX = 'atlas.inspector.layout.';
const DEFAULT_LAYOUT: InspectorLayout = { version: 1, tab: 'artifacts', splitTab: null, floating: false };

export function inspectorLayoutKey(conversationId: string): string {
  return `${STORAGE_PREFIX}${encodeURIComponent(conversationId)}`;
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
    };
  } catch { return { ...DEFAULT_LAYOUT }; }
}

export function writeInspectorLayout(conversationId: string, layout: InspectorLayout): void {
  try { localStorage.setItem(inspectorLayoutKey(conversationId), JSON.stringify(layout)); } catch { /* layout storage unavailable */ }
}
