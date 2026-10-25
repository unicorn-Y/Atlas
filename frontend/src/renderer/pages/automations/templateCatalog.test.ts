import { describe, expect, it } from 'vitest';
import { AUTOMATION_TEMPLATE_CATALOG_VERSION, AUTOMATION_TEMPLATES, materializeAutomationTemplate } from './templateCatalog';

describe('automation template catalog', () => {
  it('ships versioned, usable schedule and file-event defaults', () => {
    expect(AUTOMATION_TEMPLATE_CATALOG_VERSION).toBeGreaterThan(0);
    expect(AUTOMATION_TEMPLATES.map((item) => item.id)).toEqual(['weekday-brief', 'repo-health', 'docs-watch']);
    expect(AUTOMATION_TEMPLATES[0].trigger).toMatchObject({ kind: 'cron', cron: '0 9 * * 1-5' });
    expect(AUTOMATION_TEMPLATES[2].trigger).toMatchObject({ kind: 'event', glob: '*.md' });
  });

  it('replaces supplied parameters and leaves the result as ordinary prompt text', () => {
    const template = AUTOMATION_TEMPLATES.find((item) => item.id === 'repo-health')!;
    const content = materializeAutomationTemplate(template, { scope: 'C:/repo', checks: 'lint' });
    expect(content).toContain('巡检 C:/repo');
    expect(content).toContain('检查 lint');
    expect(content).not.toContain('{{');
  });

  it('uses defaults when parameters are omitted and does not mutate the catalog', () => {
    const template = AUTOMATION_TEMPLATES[0];
    const originalPrompt = template.prompt;
    expect(materializeAutomationTemplate(template, {})).toContain('最近一天的项目活动');
    expect(template.prompt).toBe(originalPrompt);
  });
});
