import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MarkdownContent from './MarkdownContent';

describe('MarkdownContent', () => {
  it('renders fenced code blocks and basic formatting', () => {
    const html = renderToStaticMarkup(<MarkdownContent content={'## Summary\n\nUse **bold** and `inline`.\n\n- one\n- two\n\n```ts\nconst answer = 42;\n```'} />);

    expect(html).toContain('<h2>Summary</h2>');
    expect(html).toContain('<strong>bold</strong>');
    expect(html).toContain('<code>inline</code>');
    expect(html).toContain('<ul><li>one</li><li>two</li></ul>');
    expect(html).toContain('<pre><code>const answer = 42;</code></pre>');
  });

  it('renders raw HTML as text and rejects unsafe link protocols', () => {
    const html = renderToStaticMarkup(<MarkdownContent content={'<script>alert(1)</script> [bad](javascript:alert(1))'} />);

    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
    expect(html).not.toContain('href="javascript:');
  });
});
