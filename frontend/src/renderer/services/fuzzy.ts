/**
 * 模糊匹配打分：前缀最优，其次是子串，再次是无序子序列；不匹配返回 -1。
 * `/` 菜单和 Ctrl+K 命令面板共用这一套手感，两处搜索结果排序一致。
 */
export function fuzzyScore(query: string, text: string): number {
  if (!query) return 0;
  const haystack = text.toLowerCase();
  const needle = query.toLowerCase();
  if (haystack.startsWith(needle)) return 100 - haystack.length;
  const at = haystack.indexOf(needle);
  if (at >= 0) return 70 - at;
  let cursor = 0;
  for (const char of needle) { cursor = haystack.indexOf(char, cursor); if (cursor < 0) return -1; cursor += 1; }
  return 30 - (cursor - needle.length);
}
