export function isBetween(value: number, min: number, max: number): boolean {
  return min <= max && min <= value && value <= max;
}
