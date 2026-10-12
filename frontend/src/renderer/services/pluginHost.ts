import { api } from './api';

export type PluginHostItem = { id: string; title: string; label?: string; description?: string; route?: string; command?: string; shortcut?: string; widgets?: unknown[]; plugin: string; plugin_title: string };
export type PluginHostContributions = { settingsPages: PluginHostItem[]; menuItems: PluginHostItem[]; commands: PluginHostItem[]; keybinds: PluginHostItem[]; views: PluginHostItem[] };

export const emptyPluginHost: PluginHostContributions = { settingsPages: [], menuItems: [], commands: [], keybinds: [], views: [] };
export const loadPluginHost = (baseUrl: string) => api<PluginHostContributions>(baseUrl, '/api/plugins/host');
export const callPluginHostMcpAction = (baseUrl: string, plugin: string, page_id: string, widget_id: string) =>
  api<{ is_error: boolean; follow_up: string }>(baseUrl, `/api/plugins/host/${encodeURIComponent(plugin)}/actions/mcp`, {
    method: 'POST', json: { page_id, widget_id, confirmed: true },
  });
