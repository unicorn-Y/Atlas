import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Button } from '../ui/Button';

const css = readFileSync(new URL('./app.css', import.meta.url), 'utf8');

describe('shared style and accessibility contracts', () => {
  it('defines a monotonically increasing radius scale and binds Tailwind radius utilities to it', () => {
    const values = [...css.matchAll(/--atlas-radius-([\w-]+): (\d+)px;/g)];
    expect(values.map((match) => Number(match[2]))).toEqual([2, 4, 6, 8, 12, 16, 24]);
    for (const match of values) expect(css).toContain(`--radius-${match[1]}: var(--atlas-radius-${match[1]})`);
  });

  it('renders shared button sizes using radius tokens and semantic color utilities', () => {
    for (const size of ['sm', 'md', 'lg', 'icon', 'icon-sm'] as const) {
      const html = renderToStaticMarkup(<Button size={size}>Action</Button>);
      expect(html).toMatch(/rounded-(lg|xl)/);
      expect(html).not.toContain('rounded-[');
      expect(html).toContain('text-fg');
    }
  });

  it('keeps keyboard focus visible and disables CSS animation, transitions and smooth scrolling for reduced motion', () => {
    expect(css).toMatch(/:focus-visible\s*\{[^}]*outline: 2px solid var\(--brand\)/);
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{\s*\*, \*::before, \*::after\s*\{[^}]*animation: none !important;[^}]*transition: none !important;[^}]*scroll-behavior: auto !important;/);
  });

  it('suppresses pointer-owned focus outlines without removing editable feedback or other paint', () => {
    const suppression = css.match(/html\[data-input-modality='pointer'\]\s+body\s+:focus-visible:not\(:read-write\)\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(suppression).toMatch(/outline-color:\s*transparent/);
    expect(suppression).not.toMatch(/outline\s*:\s*none|box-shadow\s*:/);
    expect(css).not.toMatch(/html\[data-input-modality='pointer'\][^{]*:read-write\s*\{/);
  });
});
