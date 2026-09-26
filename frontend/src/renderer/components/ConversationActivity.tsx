import { useState, type ReactNode } from 'react';
import { Activity, Check, FileText, Shield } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { useAtlasStore } from '../store/useAtlasStore';
import styles from '../App.module.css';
import ConversationMessage from './ConversationMessage';

type InspectorTab = 'context' | 'artifacts' | 'activity';

interface ConversationActivityProps {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
}

export default function ConversationActivity({ events, store, username, setTab }: ConversationActivityProps) {
  const [approvalDetails, setApprovalDetails] = useState(false);
  const result: ReactNode[] = [];
  for (let index = 0; index < events.length; index += 1) {
    const event = events[index];
    if (event.type === 'message.delta') {
      let content = '';
      const firstId = event.id;
      while (index < events.length && events[index].type === 'message.delta') {
        content += String(events[index].data.content ?? '');
        index += 1;
      }
      const finalEvent = events[index]?.type === 'message.completed' ? events[index] : undefined;
      if (!finalEvent) index -= 1;
      result.push(<ConversationMessage key={finalEvent?.id ?? firstId} role="assistant" content={String(finalEvent?.data.content ?? content)} username={username} status={finalEvent ? '回复完成' : '实时输出'} />);
      continue;
    }
    if (event.type === 'message.completed') {
      result.push(<ConversationMessage key={event.id} role="assistant" content={String(event.data.content ?? '')} username={username} status="回复完成" />);
      continue;
    }
    result.push(renderRuntimeEvent(event, store, username, setTab, approvalDetails, setApprovalDetails));
  }
  return <>{result}</>;
}

function renderRuntimeEvent(
  event: AgentEvent,
  store: ReturnType<typeof useAtlasStore.getState>,
  username: string,
  setTab: (tab: InspectorTab) => void,
  approvalDetails: boolean,
  setApprovalDetails: (update: (open: boolean) => boolean) => void,
) {
  const data = event.data;
  if (event.type === 'run.started' && typeof data.content === 'string') return <ConversationMessage key={event.id} role="user" content={data.content} username={username} />;
  if (event.type === 'tool.started' || event.type === 'tool.completed') {
    const result = data.result;
    const input = data.arguments;
    const value = result ?? input;
    const detail = typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value, null, 2);
    return <details className={styles.activityCard} key={event.id} open={event.type === 'tool.started'}><summary><span className={styles.activityIcon}><Activity /></span><span>{String(data.name ?? 'Tool')} · {event.type === 'tool.started' ? '执行中' : '已完成'}</span><span className={styles.activityMeta}>{event.type === 'tool.started' ? '运行中' : 'Runtime'}</span></summary>{detail && <div className={styles.activityDetail}><span>{result !== undefined ? '结果' : '输入'}</span><pre>{detail}</pre></div>}</details>;
  }
  if (event.type === 'artifact.updated') return <div className={styles.fileChange} key={event.id}><div className={styles.fileHead}><FileText /><div><strong>{String(data.name ?? data.path ?? 'Artifact')}</strong><small>{String(data.artifact_type ?? 'file')} · Runtime 更新</small></div></div><p>{String(data.summary ?? data.change ?? '')}</p><button className={styles.quietButton} onClick={() => setTab('artifacts')}>在产物中查看</button></div>;
  if (event.type === 'approval.required') {
    const response = store.getRun(event.runId)?.events.find((item) => item.type === 'approval.responded' && (item.data.event_id === event.id || item.data.approval_id === data.approval_id));
    const choice = response?.data.choice;
    const toolName = String(data.tool ?? data.name ?? '未知工具');
    return <div className={styles.approvalCard} key={event.id}><div className={styles.approvalTitle}><Shield size={16} />需要你的确认 <span>{toolName}</span></div><div className={styles.approvalCopy}>{String(data.description ?? `Agent Runtime 请求执行 ${toolName}。`)}<br />{data.input ? <code>{JSON.stringify(data.input)}</code> : data.arguments ? <code>{JSON.stringify(data.arguments)}</code> : null}</div>{choice ? <div className={styles.approvalResolved}>{choice === 'allow' ? '已允许' : '已拒绝'} · Runtime 已收到处理结果。</div> : <><div className={styles.approvalActions}><button onClick={() => store.approve(event.id)}>允许</button><button onClick={() => store.reject(event.id)}>拒绝</button><button onClick={() => setApprovalDetails((open) => !open)}>查看详情</button></div>{approvalDetails && <p className={styles.approvalDetail}>选择将以 approval.response 发送到对应的 Agent Run。</p>}</>}</div>;
  }
  if (event.type === 'run.completed') return <div className={styles.resultCard} key={event.id}><div className={styles.resultTitle}><Check />任务完成</div><p>{String(data.result ?? 'Agent Run 已完成。')}</p><div className={styles.resultActions}><button onClick={() => setTab('artifacts')}>查看产物</button><button onClick={() => setTab('activity')}>查看事件</button></div></div>;
  if (event.type === 'run.failed') return <div className={styles.failureCard} key={event.id}>运行失败：{String(data.detail ?? data.code ?? '未知错误')}</div>;
  return <div className={styles.timeline} key={event.id}><div><i />{event.type}<span>{String(data.phase ?? data.status ?? data.detail ?? '')}</span></div></div>;
}
