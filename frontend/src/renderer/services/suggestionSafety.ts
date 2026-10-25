const GENERIC = new Set(['继续', '请继续', '继续吧', '确认', '收到', '好的', '好', '谢谢', '明白', '没问题', 'ok']);
const UNSAFE_PATTERNS = [
  /\brm\s+-[^\s]*r[^\s]*f\b|\brm\s+-[^\s]*f[^\s]*r\b/i,
  /\b(?:remove-item|rmdir|rd|del)\b.{0,120}(?:-recurse|\/s\b|\/q\b)/i,
  /\b(?:mkfs(?:\.[\w-]+)?|diskpart|format\s+[a-z]:)\b/i,
  /\bfind\b.{0,180}\s-delete\b|\bshutil\.rmtree\b/i,
  /(?:永久|彻底|递归|强制).{0,20}(?:删除|清空|格式化|擦除)|(?:删除|清空|格式化|擦除).{0,20}(?:全部|所有|整个磁盘|根目录|系统文件|数据库)/i,
  /\bdd\s+if=.{0,120}\bof=\/dev\/(?:zero|sda|nvme)/i,
  /\bgit\s+(?:reset\s+--hard|clean\s+-[^\s]*f)/i,
  /\b(?:drop\s+(?:database|table)|truncate\s+table)\b/i,
  /\b(?:curl|wget|iwr|invoke-webrequest)\b.{0,160}(?:\||;).{0,80}(?:sh|bash|iex|invoke-expression)\b/i,
  /(?:api[_ -]?keys?|passwords?|secrets?|credentials?|access tokens?|密钥|密码|凭据|访问令牌).{0,100}(?:upload|send|print|dump|export|post|上传|外发|发送|打印|导出|泄露)/i,
  /(?:upload|send|print|dump|export|post|上传|外发|发送|打印|导出|泄露).{0,100}(?:api[_ -]?keys?|passwords?|secrets?|credentials?|access tokens?|密钥|密码|凭据|访问令牌)/i,
];

export function isSafeSuggestion(value: string): boolean {
  const text = value.trim();
  const normalized = text.normalize('NFKC').replace(/[\u200b\ufeff]/g, '');
  return text.length >= 6 && text.length <= 180 && !/[\u0000-\u001f\u007f]/.test(text)
    && !GENERIC.has(text.replace(/[。.!！?？]+$/g, '').toLocaleLowerCase())
    && !UNSAFE_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function filterSafeSuggestions(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const unique = new Set<string>();
  for (const raw of value) {
    if (typeof raw !== 'string') continue;
    const text = raw.trim();
    if (isSafeSuggestion(text)) unique.add(text);
    if (unique.size === 3) break;
  }
  return [...unique];
}
