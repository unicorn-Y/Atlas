import { useEffect, useId, useState } from 'react';

let loader: Promise<typeof import('mermaid')['default']> | null = null;
/** Mermaid is large, so it loads the first time a diagram appears rather than with the app. */
const loadMermaid = () => {
  loader ??= import('mermaid').then(({ default: mermaid }) => {
    const dark = document.documentElement.dataset.theme === 'dark';
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'neutral', fontFamily: 'inherit' });
    return mermaid;
  });
  return loader;
};

/** Renders a ```mermaid block as a diagram; falls back to the source if it doesn't parse. */
export default function MermaidBlock({ source }: { source: string }) {
  const id = `mermaid-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const [svg, setSvg] = useState('');
  const [failed, setFailed] = useState(false);
  const [showSource, setShowSource] = useState(false);
  const [selectedNode, setSelectedNode] = useState('');
  useEffect(() => {
    let stale = false;
    setFailed(false);
    loadMermaid()
      .then((mermaid) => mermaid.render(id, source))
      .then((result) => { if (!stale) setSvg(result.svg); })
      .catch(() => { if (!stale) setFailed(true); });
    return () => { stale = true; };
  }, [id, source]);
  useEffect(() => {
    const host = document.getElementById(id);
    if (!host) return;
    const listeners = new AbortController();
    host.querySelectorAll<SVGGElement>('g.node').forEach((node) => {
      const label = (node.querySelector('.label, .nodeLabel')?.textContent ?? node.textContent ?? '').trim();
      if (!label) return;
      node.setAttribute('tabindex', '0'); node.setAttribute('role', 'button'); node.setAttribute('aria-label', `选择图表节点：${label}`);
      const select = () => setSelectedNode(label);
      node.addEventListener('click', select, { signal: listeners.signal });
      node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }, { signal: listeners.signal });
      node.dataset.atlasLabel = label;
    });
    return () => listeners.abort();
  }, [id, svg]);

  if (failed || showSource) return <div>
    <pre><code>{source}</code></pre>
    {!failed && <button className="text-[12px] text-fg-3 hover:text-fg" onClick={() => setShowSource(false)}>显示图表</button>}
  </div>;
  return <figure className="my-3">
    {/* securityLevel 'strict' makes Mermaid sanitise labels and drop scripts from the SVG. */}
    <div id={id} className="overflow-auto rounded-xl bg-sunken p-3 [&_svg]:mx-auto [&_svg]:max-w-full [&_g.node]:cursor-pointer [&_g.node:focus]:outline [&_g.node:focus]:outline-2 [&_g.node:focus]:outline-brand" dangerouslySetInnerHTML={{ __html: svg }} aria-label="可交互图表；选择节点后可回传给 Atlas" />
    {selectedNode && <div className="mt-1 flex items-center gap-2 text-[11.5px] text-fg-3"><span className="min-w-0 flex-1 truncate">已选节点：{selectedNode}</span><button type="button" onClick={() => { window.dispatchEvent(new CustomEvent('atlas:chart-selection', { detail: { node: selectedNode, source } })); setSelectedNode(''); }} className="rounded px-2 py-1 text-brand hover:bg-hover">回传给 Atlas</button></div>}
    {svg && <button className="mt-1 text-[12px] text-fg-3 hover:text-fg" onClick={() => setShowSource(true)}>查看源码</button>}
    {!svg && <p className="m-0 text-[12px] text-fg-3">正在绘制图表…</p>}
  </figure>;
}
