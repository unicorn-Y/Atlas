// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/mentions/mentionMarkdown.ts (Apache-2.0)
/** Keep explicit $skill references separate from conversation-wide active Skills. */
export function resolveMessageSkillReferences(content: string, availableSkills: readonly string[]): string[] {
  const byName = new Map(availableSkills.map((name) => [name.toLocaleLowerCase(), name]));
  const selected = new Set<string>();
  for (const match of content.matchAll(/(?:^|\s)\$([\w.-]+)/g)) {
    const name = byName.get(match[1].toLocaleLowerCase());
    if (name) selected.add(name);
  }
  return [...selected];
}
