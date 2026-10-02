export function truncateMiddle(text: string, maxLength: number): string {
  const chars = [...text];
  if (maxLength <= 0) return "";
  if (chars.length <= maxLength) return text;
  const left = Math.ceil((maxLength - 1) / 2);
  const right = Math.floor((maxLength - 1) / 2);
  return chars.slice(0, left).join("") + "…" + (right ? chars.slice(-right).join("") : "");
}
