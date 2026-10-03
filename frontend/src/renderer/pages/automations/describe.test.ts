import { describe, expect, it } from 'vitest';
import { describeAutomation, describePayload, describeTrigger } from './describe';

describe('automation describers', () => {
  it('renders each trigger kind in plain language', () => {
    expect(describeTrigger({ kind: 'cron', cron_expr: '0 9 * * *', tz: 'Asia/Shanghai' })).toBe('按计划 0 9 * * *（Asia/Shanghai）');
    expect(describeTrigger({ kind: 'interval', every_seconds: 3600 })).toBe('每 1 小时');
    expect(describeTrigger({ kind: 'interval', every_seconds: 90 })).toBe('每 90 秒');
    expect(describeTrigger({ kind: 'date', at: '2026-10-03T09:00:00' })).toContain('执行一次');
    expect(describeTrigger({ kind: 'event', event_path: 'D:\\proj\\docs', event_glob: '*.md' })).toBe('文件变化时（docs · *.md）');
    expect(describeTrigger({ kind: 'webhook' })).toBe('收到 Webhook 时');
    expect(describeTrigger(undefined)).toBe('未设置触发');
  });

  it('marks heartbeat payloads read-only style with their agent', () => {
    expect(describePayload({ kind: 'heartbeat', agent_id: 'rabbit' })).toBe('心跳 · rabbit');
    expect(describePayload({ kind: 'script', script: 'python run.py\nsecond line' })).toBe('跑脚本：python run.py');
    expect(describePayload({ kind: 'agent_turn', agent_id: 'owl', message: '整理 issue' })).toBe('@owl 整理 issue');
  });

  it('appends the delivery channel when configured', () => {
    expect(describeAutomation({
      trigger: { kind: 'cron', cron_expr: '0 9 * * *' },
      payload: { kind: 'agent_turn', message: ' morning' },
      delivery: { mode: 'channel', channel: 'telegram', target: '1' },
    })).toBe('按计划 0 9 * * *：morning，结果发到 telegram');
  });
});
