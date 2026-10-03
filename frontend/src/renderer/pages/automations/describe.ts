/** 纯函数：automation 记录 → 人话（列表行、详情、Agent 侧 tab 共用）。 */
import type { AutomationPayload, AutomationRecord, AutomationTrigger } from '../../services/persistentApi';

export function describeTrigger(trigger?: AutomationTrigger): string {
  if (!trigger) return '未设置触发';
  if (trigger.kind === 'cron') return trigger.cron_expr ? `按计划 ${trigger.cron_expr}${trigger.tz ? `（${trigger.tz}）` : ''}` : '按计划';
  if (trigger.kind === 'interval') {
    const seconds = Number(trigger.every_seconds) || 0;
    if (seconds % 86400 === 0) return `每 ${seconds / 86400} 天`;
    if (seconds % 3600 === 0) return `每 ${seconds / 3600} 小时`;
    if (seconds % 60 === 0) return `每 ${seconds / 60} 分钟`;
    return seconds ? `每 ${seconds} 秒` : '按固定间隔';
  }
  if (trigger.kind === 'date') return trigger.at ? `${new Date(trigger.at).toLocaleString()} 执行一次` : '定时执行一次';
  if (trigger.kind === 'event') {
    const path = trigger.event_path ? `（${trigger.event_path.split(/[\\/]/).pop()}${trigger.event_glob ? ` · ${trigger.event_glob}` : ''}）` : '';
    return `文件变化时${path}`;
  }
  if (trigger.kind === 'webhook') return '收到 Webhook 时';
  return trigger.kind;
}

export function describePayload(payload?: AutomationPayload): string {
  if (!payload) return '';
  if (payload.kind === 'heartbeat') return payload.agent_id ? `心跳 · ${payload.agent_id}` : '心跳';
  if (payload.kind === 'script') return payload.script ? `跑脚本：${payload.script.split('\n')[0].slice(0, 60)}` : '跑脚本';
  const target = payload.agent_id ? `@${payload.agent_id}` : '';
  return `${target}${target && payload.message ? ' ' : ''}${(payload.message ?? '').slice(0, 60)}`.trim() || '让 Agent 行动';
}

export function describeAutomation(record: Pick<AutomationRecord, 'trigger' | 'payload' | 'delivery'>): string {
  const delivery = record.delivery?.mode === 'channel' && record.delivery.channel
    ? `，结果发到 ${record.delivery.channel}` : '';
  return `${describeTrigger(record.trigger)}：${describePayload(record.payload)}${delivery}`;
}
