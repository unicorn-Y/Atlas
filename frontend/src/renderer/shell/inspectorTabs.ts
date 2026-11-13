import type { ReactNode } from 'react';

export type InspectorTabContext = { conversationId: string; apiBaseUrl: string; connected: boolean; workspace?: string | null; onToast: (text: string) => void };
export type InspectorTabDefinition = { id: string; label: string; wide?: boolean; render: (context: InspectorTabContext) => ReactNode };

const BUILTIN_TABS = new Set(['tabs', 'overview', 'artifacts', 'activity', 'changes', 'rollout', 'android', 'files', 'treemap', 'preview', 'canvas', 'specs', 'terminal', 'browser', 'context', 'processes', 'dashboard']);
const extensionTabs = new Map<string, InspectorTabDefinition>();

export function registerInspectorTab(definition: InspectorTabDefinition): () => void {
  if (!definition.id.trim() || BUILTIN_TABS.has(definition.id)) throw new Error(`Inspector tab id is empty or reserved: ${definition.id}`);
  extensionTabs.set(definition.id, definition);
  return () => { if (extensionTabs.get(definition.id) === definition) extensionTabs.delete(definition.id); };
}

export const listInspectorTabs = () => [...extensionTabs.values()];
export const getInspectorTab = (id: string) => extensionTabs.get(id);
