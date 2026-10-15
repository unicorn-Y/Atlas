import { useEffect, useMemo, useRef, useState } from 'react';
import { useAtlasStore } from '../../store/useAtlasStore';
import MessageThread from '../../components/MessageThread';
import Composer from '../../components/Composer';
import Mark from '../../components/Mark';
import { AGENT_STATUS_META } from '../../store/persistentSlice';
import type { PersistentAgentRecord } from '../../services/persistentApi';
import type { InspectorTab } from '../../shell/Inspector';

/** 每个 Agent 固定一个聊天会话；id 记在本机，丢了对不上就再开一个。 */
const chatKey = (agentId: string) => `atlas.agent-chat.${agentId}`;
const noop = () => undefined;
const noopTab = (_tab: InspectorTab) => undefined;

/**
 * Agent 详情的「聊天」tab：直接复用主页的 MessageThread/Composer。
 * 进入时把全局会话切到该 Agent 的会话，发送走 run.start 并带 agent_id
 * （services 层的 ws 封装已透传，见 useAtlasStore.startRun）。
 */
export default function AgentChatTab({ agent, username }: { agent: PersistentAgentRecord; username: string }) {
  const conversations = useAtlasStore((state) => state.conversations);
  const conversationsLoading = useAtlasStore((state) => state.conversationsLoading);
  const conversationMessages = useAtlasStore((state) => state.conversationMessages);
  const activeConversationId = useAtlasStore((state) => state.activeConversationId);
  const runs = useAtlasStore((state) => state.runs);
  const busy = useAtlasStore((state) => state.busy);
  const sendMessage = useAtlasStore((state) => state.sendMessage);

  const [input, setInput] = useState('');
  const [preparing, setPreparing] = useState(false);
  const requestedRef = useRef('');
  const threadRef = useRef<HTMLDivElement | null>(null);
  const agentId = agent.id;

  // 打开（或创建）这个 Agent 的会话；会话列表载入完成后才动，避免重复建会话。
  useEffect(() => {
    if (conversationsLoading || requestedRef.current === agentId) return;
    requestedRef.current = agentId;
    setPreparing(true);
    void (async () => {
      const state = useAtlasStore.getState();
      let saved: string | null = null;
      try { saved = localStorage.getItem(chatKey(agentId)); } catch { /* storage unavailable */ }
      const known = saved ? state.conversations.find((item) => item.id === saved) : undefined;
      if (known) {
        if (state.activeConversationId !== known.id) await state.openConversation(known);
      } else {
        await state.createConversation(`${agent.name}`);
        const id = useAtlasStore.getState().activeConversationId;
        if (id) { try { localStorage.setItem(chatKey(agentId), id); } catch { /* storage unavailable */ } }
      }
      setPreparing(false);
    })();
  }, [agentId, agent.name, conversationsLoading, conversations]);

  const messages = conversationMessages[activeConversationId] ?? [];
  const history = useMemo(
    () => messages.filter((message) => message.role === 'user' || message.role === 'assistant'),
    [messages]);
  const mine = useMemo(
    () => [...runs].reverse().find((run) => run.conversationId === activeConversationId),
    [runs, activeConversationId]);
  const runLive = Boolean(mine && !['completed', 'failed', 'cancelled'].includes(mine.status));

  const submit = () => {
    const text = input.trim();
    if (!text) return;
    setInput('');
    void sendMessage(text, [], [], undefined, undefined, agentId);
  };

  const status = AGENT_STATUS_META[agent.status ?? 'offline'];
  if (preparing && !activeConversationId) return <div className="grid flex-1 place-items-center text-[13px] text-fg-3">正在打开 {agent.name} 的会话…</div>;

  return <div className="flex min-h-0 flex-1 flex-col">
    <div className="mb-1 flex items-center gap-2.5 px-8 pt-3 text-[12.5px] text-fg-3">
      <Mark className="size-[16px]" working={runLive && busy} />
      <span className="text-fg-2">{agent.name}</span>
      <span className={status.className}>· {status.label}</span>
      {agent.agent?.enabled === false && <span className="text-danger">· 已停用：消息会照发，但后端可能不接</span>}
      {runLive && <span className="text-brand">· 上一轮还在跑</span>}
    </div>
    <MessageThread
      history={history}
      username={username}
      historyActions={noop}
      emptyState={<div className="pt-[12vh] text-center">
        <Mark className="mx-auto mb-4 size-11" />
        <h2 className="m-0 text-[22px] font-semibold text-heading">和 {agent.name} 说什么？</h2>
        <p className="mt-2 text-[13.5px] text-fg-3">这条会话由 {agent.name} 负责：模型、技能和指令都按它的配置来。</p>
      </div>}
      footerNote={null}
      threadRef={threadRef}
      setTab={noopTab}
    />
    <div className="px-8 pb-5">
      <div className="mx-auto w-[min(720px,100%)]">
        <Composer
          value={input} onChange={setInput} onSubmit={submit}
          placeholder={`给 ${agent.name} 布置一件事…`}
          attachments={[]} onRemoveAttachment={noop} onPickImages={noop}
          listening={false} onToggleMic={noop}
          models={[]} model="" onSelectModel={noop} onManageModels={noop}
          status="" autoFocus />
      </div>
    </div>
  </div>;
}
