import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import HomeView, { SUGGESTIONS, stepHomeTip } from './HomeView';

describe('home example carousel', () => {
  it('renders the whole example and a fill action with carousel controls', () => {
    const html = renderToStaticMarkup(<HomeView username="User" composer={<textarea />} recent={[]}
      onOpen={() => undefined} onSuggest={() => undefined} />);
    expect(html).toContain('固定提示示例');
    expect(html).toContain(SUGGESTIONS[0].text);
    expect(html).toContain('填入完整示例');
    expect(html).toContain('下一条首页示例');
  });

  it('wraps previous and next movement around all fixed tips', () => {
    expect(stepHomeTip(0, -1)).toBe(SUGGESTIONS.length - 1);
    expect(stepHomeTip(SUGGESTIONS.length - 1, 1)).toBe(0);
  });
});
