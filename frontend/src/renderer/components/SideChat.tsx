import { useEffect, useRef, useState, type FormEvent } from 'react';
import { MessagesSquare, Send, Square } from 'lucide-react';
import { backend, useAtlasStore } from '../store/useAtlasStore';
import { Dialog } from '../ui/Dialog';
import { Button } from '../ui/Button';
import ConversationMessage from './ConversationMessage';

interface Turn { question: string; answer: string; state: 'running' | 'done' | 'failed' }

/**
 * Ask something about the conversation without steering it: the backend runs these read-only and
 * never saves them, so the main task and its history stay untouched.
 */
export default function SideChat({ open, onClose, conversationId, model, initialQuestion }: {
  open: boolean; onClose: () => void; conversationId: string; model: string; initialQuestion?: string;
}) {
  const [question, setQuestion] = useState('');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [commandError, setCommandError] = useState('');
  const runRef = useRef<string | null>(null);
  const askedInitial = useRef('');

  const ask = (text: string) => {
    const content = text.trim();
    if (!content || runRef.current) return;
    const runId = crypto.randomUUID();
    runRef.current = runId;
    setQuestion('');
    setTurns((current) => [...current, { question: content, answer: '', state: 'running' }]);
    const update = (patch: Partial<Turn> | ((turn: Turn) => Partial<Turn>)) => setTurns((current) => current.map((turn, index) =>
      index === current.length - 1 ? { ...turn, ...(typeof patch === 'function' ? patch(turn) : patch) } : turn));
    void backend.startRun({ type: 'run.start', run_id: runId, content, conversation_id: conversationId, model, ephemeral: true }, (envelope) => {
      if (envelope.event === 'message.delta') update((turn) => ({ answer: turn.answer + String(envelope.data?.content ?? '') }));
      else if (envelope.event === 'message.completed' && envelope.data?.content) update({ answer: String(envelope.data.content) });
      else if (envelope.event === 'run.completed') update({ state: 'done' });
      else if (envelope.event === 'run.failed') update((turn) => ({ state: 'failed', answer: turn.answer || String(envelope.data?.detail ?? '没能回答') }));
      else if (envelope.event === 'run.cancelled') update({ state: 'done' });
    }).catch((error) => update({ state: 'failed', answer: error instanceof Error ? error.message : '没能回答' }))
      .finally(() => { if (runRef.current === runId) runRef.current = null; });
  };

  useEffect(() => {
    if (open && initialQuestion && askedInitial.current !== initialQuestion) { askedInitial.current = initialQuestion; ask(initialQuestion); }
    if (!open) { askedInitial.current = ''; }
  }, [open, initialQuestion]);
  const stop = () => {
    try { if (runRef.current) backend.cancelRun(runRef.current); }
    catch (error) { useAtlasStore.setState({ error: error instanceof Error ? error.message : '停止请求失败' }); }
  };
  const SIDE_COMMANDS = ['/copy', '/diff', '/status'] as const;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = question.trim();
    setCommandError('');
    if (trimmed.startsWith('/')) {
      const [command, ...rest] = trimmed.split(/\s+/);
      const argument = rest.join(' ');
      if (!SIDE_COMMANDS.includes(command as typeof SIDE_COMMANDS[number])) { setCommandError('旁聊只支持 /copy、/diff、/status。'); return; }
      if (command === '/copy') {
        const answer = turns.at(-1)?.answer;
        if (!answer) { setCommandError('还没有可复制的旁聊回复。'); return; }
        void navigator.clipboard.writeText(answer).then(() => setCommandError('已复制最近一条旁聊回复。')).catch(() => setCommandError('复制失败，请检查剪贴板权限。'));
        setQuestion(''); return;
      }
      if (command === '/status') {
        setTurns((current) => [...current, { question: trimmed, answer: `模型：${model}\n会话：${conversationId}\n模式：临时旁聊（不写入主对话）`, state: 'done' }]);
        setQuestion(''); return;
      }
      ask(`请只读检查当前工作区的 Git diff${argument ? `（范围：${argument}）` : ''}，归纳改动与需要注意的问题；不要修改文件或调用有副作用的操作。`);
      return;
    }
    ask(trimmed);
  };
  const running = turns.at(-1)?.state === 'running';

  return <Dialog open={open} onOpenChange={(next) => { if (!next) { stop(); setTurns([]); onClose(); } }} label="旁问" className="flex h-[min(620px,calc(100vh-48px))] w-[min(680px,calc(100vw-32px))] flex-col">
    <header className="flex items-center gap-2 px-5 pt-4 pb-3 shadow-[inset_0_-1px_0_var(--line)]">
      <MessagesSquare size={17} className="text-brand" />
      <b className="text-[15px] font-semibold text-heading">旁问</b>
      <span className="text-[12.5px] text-fg-3">借用这个对话的上下文，不打断正在做的事，也不会存进对话</span>
    </header>
    <div className="min-h-0 flex-1 overflow-auto px-5">
      {turns.map((turn, index) => <div key={index}>
        <ConversationMessage role="user" content={turn.question} username="你" />
        <ConversationMessage role="assistant" content={turn.answer || (turn.state === 'running' ? '…' : '')} username="你" status={turn.state === 'running' ? '正在回答' : undefined} working={turn.state === 'running'} />
      </div>)}
      {!turns.length && <p className="pt-16 text-center text-[13px] text-fg-3">比如「刚才那个报错是什么意思？」「这个方案还有别的做法吗？」</p>}
    </div>
    <form onSubmit={submit} className="flex gap-2 p-4 shadow-[inset_0_1px_0_var(--line)]">
      <input autoFocus value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="问一个旁支问题" aria-label="旁问内容"
        className="h-10 min-w-0 flex-1 rounded-[11px] bg-sunken px-3.5 text-[14px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      {running ? <Button size="lg" onClick={stop}><Square />停止</Button> : <Button size="lg" type="submit" variant="primary" disabled={!question.trim()}><Send />问</Button>}
    </form>
    {commandError && <p role="status" className="m-0 px-5 pb-3 text-[12px] text-fg-3">{commandError}</p>}
    {question.startsWith('/') && <div className="flex gap-1.5 px-5 pb-3" aria-label="旁聊可用命令">{SIDE_COMMANDS.filter((command) => command.startsWith(question.split(/\s/)[0])).map((command) => <button key={command} type="button" onClick={() => setQuestion(`${command} `)} className="rounded-md bg-brand-soft px-2 py-1 font-mono text-[11px] text-brand">{command}</button>)}</div>}
  </Dialog>;
}
