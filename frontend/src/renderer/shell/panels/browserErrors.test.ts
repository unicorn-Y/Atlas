import { describe, expect, it } from 'vitest';
import { BROWSER_FAILURE_GUIDE, classifyBrowserFailure } from './browserErrors';

describe('browser loading error guidance', () => {
  it.each([
    [-105, 'dns'], [-102, 'refused'], [-130, 'proxy'], [-200, 'tls'], [-138, 'firewall'], [-7, 'timeout'],
  ] as const)('classifies Chromium error %i', (code, expected) => {
    expect(classifyBrowserFailure(code)).toBe(expected);
    expect(BROWSER_FAILURE_GUIDE[expected].checks.length).toBeGreaterThan(0);
  });
  it('preserves unknown failures for the error card', () => {
    expect(classifyBrowserFailure(-999, 'net::ERR_VENDOR_SPECIFIC')).toBe('unknown');
  });
});
