export function truncateMiddle(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  const side = Math.floor((maxLength - 1) / 2);
  return text.slice(0, side) + "…" + text.slice(text.length - side);
}
