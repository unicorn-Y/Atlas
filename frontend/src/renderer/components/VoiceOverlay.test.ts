import { describe, expect, it } from 'vitest';
import { classifyVoiceFailure } from './VoiceOverlay';

describe('classifyVoiceFailure', () => {
  it.each([
    [{ name: 'NotAllowedError', message: 'denied' }, '麦克风权限被拒绝'],
    [{ name: 'NotFoundError', message: 'missing input' }, '麦克风设备不可用'],
    ['本地语音模型未准备', '语音模型缺失'],
    ['音频帧 PCM 格式无效', '音频格式或解码失败'],
    ['WebSocket 连接中断', '语音网络或后端断连'],
  ])('maps %s to an actionable reason', (error, category) => {
    const result = classifyVoiceFailure(error);
    expect(result.category).toBe(category);
    expect(result.detail).toBeTruthy();
    expect(result.next).toBeTruthy();
  });
});
