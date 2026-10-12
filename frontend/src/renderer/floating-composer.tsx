import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';

function FloatingComposer() {
  const [text, setText] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    window.atlasDesktop?.submitFloatingComposer?.(value);
    setText('');
  };

  return <main className="shell">
    <header><strong>Atlas 快速输入</strong><span>Ctrl + Alt + Space</span><button type="button" aria-label="关闭" onClick={() => window.atlasDesktop?.hideFloatingComposer?.()}>×</button></header>
    <textarea ref={inputRef} aria-label="快速输入" placeholder="写下任务，提交后会送到 Atlas 主窗口…" value={text}
      onChange={(event) => setText(event.target.value)} onKeyDown={(event) => {
        if (event.key === 'Escape') window.atlasDesktop?.hideFloatingComposer?.();
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(); }
      }} />
    <footer><span>Ctrl/⌘ + Enter 交给 Atlas</span><button type="button" disabled={!text.trim()} onClick={submit}>交给 Atlas</button></footer>
    <style>{`
      * { box-sizing: border-box; }
      body { margin: 0; color: #242321; background: #faf9f6; font: 14px/1.45 system-ui, sans-serif; }
      .shell { height: 100vh; display: flex; flex-direction: column; padding: 12px 15px 13px; border: 1px solid #d8d4cc; border-radius: 12px; }
      header, footer { display: flex; align-items: center; gap: 10px; }
      header { -webkit-app-region: drag; }
      header strong { font-size: 13px; font-weight: 650; }
      header span, footer span { color: #77736d; font-size: 11px; }
      header button { -webkit-app-region: no-drag; margin-left: auto; border: 0; background: transparent; color: #77736d; font-size: 22px; line-height: 1; cursor: pointer; }
      textarea { flex: 1; min-height: 70px; margin: 8px 0; padding: 8px 0; resize: none; border: 0; outline: 0; background: transparent; color: inherit; font: inherit; }
      footer button { margin-left: auto; border: 0; border-radius: 7px; padding: 7px 12px; background: #273349; color: white; cursor: pointer; }
      footer button:disabled { opacity: .45; cursor: default; }
    `}</style>
  </main>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><FloatingComposer /></React.StrictMode>);
