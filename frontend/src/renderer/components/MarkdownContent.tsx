import type { ReactNode } from 'react';
import styles from '../App.module.css';

function inline(text: string): ReactNode[] {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  const nodes: ReactNode[] = [];
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > cursor) nodes.push(text.slice(cursor, start));
    if (token.startsWith('`')) nodes.push(<code key={start}>{token.slice(1, -1)}</code>);
    else if (token.startsWith('**')) nodes.push(<strong key={start}>{token.slice(2, -2)}</strong>);
    else if (token.startsWith('*')) nodes.push(<em key={start}>{token.slice(1, -1)}</em>);
    else {
      const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (link && /^(https?:|mailto:)/i.test(link[2])) {
        nodes.push(<a key={start} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>);
      } else nodes.push(token);
    }
    cursor = start + token.length;
  }
  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

export function renderMarkdown(source: string): ReactNode[] {
  const lines = source.replace(/\r\n?/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let list: string[] = [];
  let ordered = false;
  let code: string[] | null = null;
  const flushParagraph = () => {
    if (paragraph.length) blocks.push(<p key={`p-${blocks.length}`}>{inline(paragraph.join(' '))}</p>);
    paragraph = [];
  };
  const flushList = () => {
    if (!list.length) return;
    const Items = list.map((item, index) => <li key={index}>{inline(item)}</li>);
    blocks.push(ordered ? <ol key={`l-${blocks.length}`}>{Items}</ol> : <ul key={`l-${blocks.length}`}>{Items}</ul>);
    list = [];
  };

  for (const line of lines) {
    if (line.startsWith('```')) {
      flushParagraph(); flushList();
      if (code) {
        blocks.push(<pre key={`c-${blocks.length}`}><code>{code.join('\n')}</code></pre>);
        code = null;
      } else code = [];
      continue;
    }
    if (code) { code.push(line); continue; }
    if (!line.trim()) { flushParagraph(); flushList(); continue; }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      flushParagraph(); flushList();
      const level = heading[1].length;
      const Heading = `h${level}` as keyof JSX.IntrinsicElements;
      blocks.push(<Heading key={`h-${blocks.length}`}>{inline(heading[2])}</Heading>);
      continue;
    }
    const item = /^(\s*)([-*+]\s+|\d+[.)]\s+)(.+)$/.exec(line);
    if (item) {
      flushParagraph();
      const isOrdered = /^\d/.test(item[2]);
      if (list.length && ordered !== isOrdered) flushList();
      ordered = isOrdered;
      list.push(item[3]);
      continue;
    }
    flushList(); paragraph.push(line.trim());
  }
  if (code) blocks.push(<pre key={`c-${blocks.length}`}><code>{code.join('\n')}</code></pre>);
  flushParagraph(); flushList();
  return blocks;
}

export default function MarkdownContent({ content }: { content: string }) {
  return <div className={styles.markdownContent}>{renderMarkdown(content)}</div>;
}
