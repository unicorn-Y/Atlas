export function camelCase(input: string): string {
  return input
    .split(/[-_\s]+/g)
    .map((word, index) =>
      index === 0
        ? word.toLowerCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
    )
    .join("");
}
