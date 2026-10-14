import { useState } from 'react';
import { ArrowRight, LoaderCircle, X } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';

export default function HandoffProposalCard({ event }: { event: AgentEvent }) {
  const store = useAtlasStore.getState();
  const [busy, setBusy] = useState(false);
  const [closed, setClosed] = useState(false);
  const [error, setError] = useState('');
  const goal = typeof event.data.goal === 'string' ? event.data.goal : '';
  const context = typeof event.data.context === 'string' ? event.data.context : '';
  const proposalId = typeof event.data.proposal_id === 'string' ? event.data.proposal_id : event.id;
  const run = store.runs.find((item) => item.id === event.runId);
  const conversationId = typeof event.data.from_conversation === 'string'
    ? event.data.from_conversation : run?.conversationId ?? '';

  if (closed) return <div className="my-3 ml-10 text-[12px] text-fg-3">接力提议已处理</div>;

  const accept = async () => {
    if (!conversationId || !goal.trim()) { setError('接力提议缺少会话或目标信息'); return; }
    setBusy(true); setError('');
    try {
      const result = await store.createHandoff(conversationId, {
        goal, context, source: 'model_proposed', run_id: event.runId, proposal_id: proposalId,
      });
      window.dispatchEvent(new CustomEvent('atlas:handoff-draft', {
        detail: { conversation: result.conversation, prompt_draft: result.prompt_draft },
      }));
      setClosed(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };

  const continueHere = async () => {
    if (!conversationId) { setClosed(true); return; }
    setBusy(true); setError('');
    try { await store.declineHandoff(conversationId, event.runId, proposalId); setClosed(true); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };

  return <section className="my-4 ml-10 max-w-2xl rounded-xl border border-brand/30 bg-brand-soft/30 px-4 py-3" aria-label="接力提议">
    <div className="mb-2 text-[13px] font-medium text-fg">Atlas 建议把下一阶段交给新会话</div>
    <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-fg-2"><b>Task：</b>{goal}</div>
    {context && <details className="mt-2 text-[12px] text-fg-3"><summary className="cursor-pointer">查看接力上下文</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-sans">{context}</pre></details>}
    {error && <p role="alert" className="mb-0 text-[12px] text-danger">{error}</p>}
    <div className="mt-3 flex gap-2">
      <Button size="sm" onClick={() => void accept()} disabled={busy}><ArrowRight size={14} />接力</Button>
      <Button size="sm" variant="ghost" onClick={() => void continueHere()} disabled={busy}><X size={14} />继续当前会话</Button>
      {busy && <LoaderCircle size={14} className="my-auto animate-spin text-fg-3" aria-label="正在处理" />}
    </div>
  </section>;
}
