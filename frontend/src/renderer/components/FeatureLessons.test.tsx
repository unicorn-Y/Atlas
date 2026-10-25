import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import FeatureLessons from './FeatureLessons';

describe('FeatureLessons', () => {
  it('exposes the first replayable lesson, guided demo, practice and accessible controls', () => {
    const html = renderToStaticMarkup(<FeatureLessons open onClose={() => undefined} />);
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('让 Atlas 了解你的工作区');
    expect(html).toContain('动手练习');
    expect(html).toContain('跳过');
    expect(html).toContain('重置');
    expect(html).toContain('prefers-reduced-motion');
  });

  it('does not render while closed', () => {
    expect(renderToStaticMarkup(<FeatureLessons open={false} onClose={() => undefined} />)).toBe('');
  });
});
