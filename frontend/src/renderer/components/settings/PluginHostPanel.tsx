import { useEffect, useState } from 'react';
import type { PluginHostContributions, PluginHostItem } from '../../services/pluginHost';
import { Button } from '../../ui/Button';

type Widget = { id?: string; type?: string; label?: string; text?: string; value?: string | boolean; options?: string[]; action?: { type?: string; route?: string; command?: string; confirm?: boolean; server?: string; tool?: string } };
const allowedRoutes = new Set(['chat', 'code', 'agents', 'auto', 'home']);

export default function PluginHostPanel({ contributions, onRoute, onCommand, onToast, onMcpAction }: {
  contributions: PluginHostContributions;
  onRoute: (route: string) => void;
  onCommand: (name: string) => void;
  onToast: (message: string) => void;
  onMcpAction: (plugin: string, page: string, widget: string) => Promise<string>;
}) {
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  useEffect(() => {
    try { setValues(JSON.parse(localStorage.getItem('atlas-plugin-widget-state') ?? '{}')); } catch { setValues({}); }
  }, []);
  const setValue = (key: string, value: string | boolean) => setValues((current) => {
    const next = { ...current, [key]: value };
    localStorage.setItem('atlas-plugin-widget-state', JSON.stringify(next));
    return next;
  });
  const activate = (item: PluginHostItem) => {
    if (item.command) { onCommand(item.command.replace(/^\//, '')); return; }
    if (item.route && allowedRoutes.has(item.route)) { onRoute(item.route); return; }
    onToast(`“${item.title}”尚未声明可由 Atlas 执行的命令或页面`);
  };
  const pages = contributions.settingsPages;
  const items = [...contributions.menuItems, ...contributions.commands, ...contributions.views];
  return <div className="grid gap-5">
    {pages.map((page) => <section key={`${page.plugin}:${page.id}`} className="rounded-xl border border-edge bg-panel p-4">
      <h4 className="m-0 text-[13px] font-semibold text-fg">{page.title}<span className="ml-2 text-[10px] font-normal text-fg-3">{page.plugin_title}</span></h4>
      {page.description && <p className="mb-3 mt-1 text-[12px] text-fg-3">{page.description}</p>}
      <div className="grid gap-3">{(Array.isArray(page.widgets) ? page.widgets as Widget[] : []).filter((w) => w && typeof w === 'object' && typeof w.id === 'string').map((widget) => {
        const id = `${page.plugin}:${page.id}:${widget.id}`;
        const current = values[id] ?? widget.value ?? '';
        if (widget.type === 'toggle') return <label key={id} className="flex items-center gap-2 text-[12px] text-fg-2"><input type="checkbox" checked={current === true} onChange={(e) => setValue(id, e.target.checked)} />{widget.label ?? widget.id}</label>;
        if (widget.type === 'input') return <label key={id} className="grid gap-1 text-[12px] text-fg-2">{widget.label ?? widget.id}<input value={typeof current === 'string' ? current : ''} onChange={(e) => setValue(id, e.target.value)} className="rounded-md border border-edge bg-sunken px-2 py-1.5 text-fg" /></label>;
        if (widget.type === 'select' && Array.isArray(widget.options)) return <label key={id} className="grid gap-1 text-[12px] text-fg-2">{widget.label ?? widget.id}<select value={String(current)} onChange={(e) => setValue(id, e.target.value)} className="rounded-md border border-edge bg-sunken px-2 py-1.5 text-fg">{widget.options.filter((v): v is string => typeof v === 'string').map((v) => <option key={v} value={v}>{v}</option>)}</select></label>;
        if (widget.type === 'text') return <p key={id} className="m-0 text-[12px] text-fg-3">{widget.text ?? widget.label}</p>;
        if (widget.type === 'button') return <Button key={id} size="sm" variant="secondary" onClick={() => {
          if (widget.action?.type === 'mcp_tool_call') {
            if (!window.confirm(`插件“${page.plugin_title}”请求调用 MCP 工具“${widget.action.server ?? ''} / ${widget.action.tool ?? ''}”。继续？`)) return;
            void onMcpAction(page.plugin, page.id, widget.id!).then(onToast).catch((error: unknown) => onToast(error instanceof Error ? error.message : String(error)));
            return;
          }
          if (widget.action?.confirm && !window.confirm(`插件“${page.plugin_title}”请求执行“${widget.label ?? widget.id}”。继续？`)) return;
          if (widget.action?.command) onCommand(widget.action.command.replace(/^\//, ''));
          else if (widget.action?.route && allowedRoutes.has(widget.action.route)) onRoute(widget.action.route);
          else onToast('此插件按钮没有可用的 Atlas 主机操作');
        }}>{widget.label ?? widget.id}</Button>;
        return null;
      })}</div>
    </section>)}
    {items.length > 0 && <section className="rounded-xl border border-edge bg-panel p-4"><h4 className="mb-3 mt-0 text-[13px] font-semibold text-fg">插件命令与菜单</h4><div className="flex flex-wrap gap-2">{items.map((item) => <Button key={`${item.plugin}:${item.id}`} size="sm" variant="secondary" onClick={() => activate(item)}>{item.title}<span className="ml-1 text-[10px] text-fg-3">{item.plugin_title}</span></Button>)}</div></section>}
    {pages.length === 0 && items.length === 0 && <p className="m-0 text-[12px] text-fg-3">当前没有已启用插件声明 Atlas 主机设置页、菜单或命令。</p>}
  </div>;
}
