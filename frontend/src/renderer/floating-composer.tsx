import React, { useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { api } from './services/api';

type Action = 'write' | 'rewrite' | 'polish';
type Context = { selectedText: string; conversationId?: string };

function FloatingComposer() {
  const [text, setText] = useState('');
  const [context, setContext] = useState<Context>({ selectedText: '' });
  const [action, setAction] = useState<Action>('rewrite');
  const [instruction, setInstruction] = useState('');
  const [result, setResult] = useState('');
  const [resultModel, setResultModel] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    void window.atlasDesktop?.getFloatingComposerContext?.().then(setContext);
    return window.atlasDesktop?.onFloatingComposerContext?.((next) => {
      setContext(next); setResult(''); setError('');
    });
  }, []);

  const submit = () => {
    const value = text.trim();
    if (!value) return;
    window.atlasDesktop?.submitFloatingComposer?.(value);
    setText('');
  };

  const generate = async () => {
    setBusy(true); setError(''); setResult('');
    try {
      const response = await api<{ text: string; model: string }>(
        window.atlasDesktop?.apiBaseUrl ?? 'http://127.0.0.1:8765', '/api/quick-write', {
          method: 'POST', json: {
            action, selected_text: context.selectedText, instruction,
            conversation_id: context.conversationId,
          },
        },
      );
      setResult(response.text); setResultModel(response.model);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };

  const copyResult = async () => {
    try { await navigator.clipboard.writeText(result); setError('已复制到剪贴板'); }
    catch (exc) { setError(`复制失败：${exc instanceof Error ? exc.message : String(exc)}`); }
  };

  const returnDraft = () => {
    if (!result.trim()) return;
    window.atlasDesktop?.returnFloatingDraft?.(result, context.conversationId);
  };

  return <main className="shell">
    <header><strong>Atlas 快速输入与写作</strong><span>Ctrl + Alt + Space</span><button type="button" aria-label="关闭" onClick={() => window.atlasDesktop?.hideFloatingComposer?.()}>×</button></header>
    <section className="quick">
      <textarea ref={inputRef} aria-label="快速输入" placeholder="写下问题或任务，Ctrl/⌘ + Enter 直接发送…" value={text}
        onChange={(event) => setText(event.target.value)} onKeyDown={(event) => {
          if (event.key === 'Escape') window.atlasDesktop?.hideFloatingComposer?.();
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); submit(); }
        }} />
      <button type="button" disabled={!text.trim()} onClick={submit}>发送提问</button>
    </section>
    <details open={Boolean(context.selectedText)}>
      <summary>{context.selectedText ? `选中文字写作${context.conversationId ? ' · 已关联来源会话' : ''}` : '选中文字快速写作 / 改写'}</summary>
      <div className="writer">
        <label>选中文字<textarea aria-label="选中文字" value={context.selectedText} maxLength={12000}
          placeholder="在 Atlas 中选中文字后右键选择“随手写 / 改写选中文字”；也可以直接输入素材。"
          onChange={(event) => setContext((current) => ({ ...current, selectedText: event.target.value }))} /></label>
        <div className="actions" role="group" aria-label="写作操作">
          {([['write', '起草'], ['rewrite', '改写'], ['polish', '润色']] as const).map(([key, label]) =>
            <button key={key} type="button" aria-pressed={action === key} className={action === key ? 'selected' : ''} onClick={() => setAction(key)}>{label}</button>)}
        </div>
        <label>补充要求<input aria-label="写作补充要求" value={instruction} maxLength={2000} onChange={(event) => setInstruction(event.target.value)} placeholder="语气、长度、格式或目标读者（可选）" /></label>
        <button type="button" disabled={busy || (!context.selectedText.trim() && !instruction.trim())} onClick={() => void generate()}>{busy ? '正在生成预览…' : '生成预览'}</button>
        {error && <p role="status" className="notice">{error}</p>}
        {result && <>
          <label>预览{resultModel && <small> · {resultModel}</small>}<textarea aria-label="写作结果预览" className="result" value={result} onChange={(event) => setResult(event.target.value)} /></label>
          <div className="actions"><button type="button" onClick={() => void copyResult()}>复制</button>
            <button type="button" className="primary" onClick={returnDraft}>回填来源会话草稿</button></div>
        </>}
      </div>
    </details>
    <footer><span>快速提问：Ctrl/⌘ + Enter　·　写作结果可预览、复制或回填原会话草稿</span></footer>
    <style>{`
      * { box-sizing: border-box; }
      body { margin: 0; color: #242321; background: #faf9f6; font: 13px/1.45 system-ui, sans-serif; }
      .shell { height: 100vh; overflow: auto; display: flex; flex-direction: column; padding: 12px 15px 13px; border: 1px solid #d8d4cc; border-radius: 12px; }
      header, footer { display: flex; align-items: center; gap: 10px; }
      header { position: sticky; top: 0; -webkit-app-region: drag; background: #faf9f6; z-index: 1; }
      header strong { font-size: 13px; font-weight: 650; }
      header span, footer span, small { color: #77736d; font-size: 11px; }
      header button { -webkit-app-region: no-drag; margin-left: auto; border: 0; background: transparent; color: #77736d; font-size: 22px; line-height: 1; cursor: pointer; }
      .quick { display: flex; gap: 10px; align-items: stretch; min-height: 74px; margin: 8px 0; }
      textarea, input { width: 100%; padding: 8px; resize: vertical; border: 1px solid #e0ddd6; border-radius: 7px; outline: 0; background: white; color: inherit; font: inherit; }
      .quick textarea { flex: 1; min-height: 70px; border: 0; background: transparent; }
      details { border-top: 1px solid #e2ded6; padding-top: 7px; }
      summary { cursor: pointer; color: #47443f; font-weight: 600; }
      .writer { display: grid; gap: 8px; padding: 8px 0; }
      label { display: grid; gap: 3px; color: #57534d; font-size: 11.5px; }
      .writer label:first-child textarea { min-height: 70px; max-height: 150px; }
      .writer .result { min-height: 100px; max-height: 220px; }
      button { border: 1px solid #dedad2; border-radius: 7px; padding: 6px 10px; background: white; color: #34312c; cursor: pointer; font: inherit; white-space: nowrap; }
      button:disabled { opacity: .45; cursor: default; }
      button.selected, button.primary, .quick > button { background: #273349; color: white; border-color: #273349; }
      .actions { display: flex; gap: 6px; }
      .notice { margin: 0; color: #5c594f; font-size: 11.5px; }
      footer { margin-top: auto; padding-top: 8px; }
    `}</style>
  </main>;
}

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><FloatingComposer /></React.StrictMode>);
