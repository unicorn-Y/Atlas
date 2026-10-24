// 后端全文搜索（/api/search）返回 FTS snippet，命中词用 >>> <<< 包住，且会命中工具输出里的 JSON。
// 这里统一做展示清洗：去标记、以命中处为中心截取摘录，对话消息排在工具输出前面。

export interface SearchHitLike { role?: string; content: string; snippet?: string }

const MARK_OPEN = '>>>';
const MARK_CLOSE = '<<<';

export function cleanSearchSnippet(hit: SearchHitLike, query: string, width = 80): string {
  const raw = (hit.snippet || hit.content || '').replace(/\s+/g, ' ');
  const marked = raw.indexOf(MARK_OPEN);
  const text = raw.split(MARK_OPEN).join('').split(MARK_CLOSE).join('').replace(/\\"/g, '"');
  const fromQuery = query ? text.toLowerCase().indexOf(query.toLowerCase()) : -1;
  const at = marked >= 0 ? marked : fromQuery;
  if (at < 0 || text.length <= width) return text.slice(0, width);
  const start = Math.max(0, at - Math.floor(width / 3));
  return `${start > 0 ? '…' : ''}${text.slice(start, start + width)}${start + width < text.length ? '…' : ''}`;
}

export function rankSearchHits<T extends SearchHitLike>(hits: T[]): T[] {
  const weight = (hit: T) => hit.role === 'user' ? 0 : hit.role === 'assistant' ? 1 : 2;
  return hits.map((hit, index) => ({ hit, index })).sort((a, b) => weight(a.hit) - weight(b.hit) || a.index - b.index).map((item) => item.hit);
}

export function searchHitRoleLabel(role?: string): string {
  return role === 'user' ? '你' : role === 'assistant' ? 'Atlas' : role === 'tool' ? '工具输出' : '';
}
