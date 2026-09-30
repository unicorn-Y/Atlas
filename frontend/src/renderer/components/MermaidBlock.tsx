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
  useEffect(() => {
    let stale = false;
    setFailed(false);
    loadMermaid()
      .then((mermaid) => mermaid.render(id, source))
      .then((result) => { if (!stale) setSvg(result.svg); })
      .catch(() => { if (!stale) setFailed(true); });
    return () => { stale = true; };
  }, [id, source]);

  if (failed || showSource) return <div>
    <pre><code>{source}</code></pre>
    {!failed && <button className="text-[12px] text-fg-3 hover:text-fg" onClick={() => setShowSource(false)}>显示图表</button>}
  </div>;
  return <figure className="my-3">
    {/* securityLevel 'strict' makes Mermaid sanitise labels and drop scripts from the SVG. */}
    <div className="overflow-auto rounded-xl bg-sunken p-3 [&_svg]:mx-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} aria-label="图表" />
    {svg && <button className="mt-1 text-[12px] text-fg-3 hover:text-fg" onClick={() => setShowSource(true)}>查看源码</button>}
    {!svg && <p className="m-0 text-[12px] text-fg-3">正在绘制图表…</p>}
  </figure>;
}
