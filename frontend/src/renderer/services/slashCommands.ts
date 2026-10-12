import { fuzzyScore } from './fuzzy';

/** Runtime contract shared by built-in, skill, and workspace slash commands. */
export interface SlashCommand {
  id: string;
  label: string;
  hint?: string;
  group?: string;
  /** Human-readable origin shown in the suggestion list. */
  source?: string;
  takesArgument?: boolean;
  run: (argument: string) => void;
}

/** Register a command set with stable IDs and explicit display origins. */
export function registerSlashCommands(commands: readonly SlashCommand[]): SlashCommand[] {
  const ids = new Set<string>();
  return commands.map((command) => {
    if (!command.id.trim() || ids.has(command.id)) throw new Error(`Duplicate or empty slash command ID: ${command.id}`);
    ids.add(command.id);
    const source = command.source ?? (command.id.startsWith('skill-') ? '技能' : command.id.startsWith('command-') ? '自定义命令' : 'Atlas');
    return { ...command, source };
  });
}

/** Match a `/query` draft against command names, descriptions, groups, and origins. */
export function matchSlashCommands(value: string, commands: readonly SlashCommand[]): SlashCommand[] {
  const match = /^\/(\S*)(\s[\s\S]*)?$/.exec(value);
  if (!match) return [];
  const [, word, rest] = match;
  if (rest !== undefined) return commands.filter((command) => command.takesArgument && command.label === `/${word}`);
  return commands.map((command, index) => {
    const nameRank = fuzzyScore(word, command.label.slice(1));
    const metadataRank = fuzzyScore(word, `${command.hint ?? ''} ${command.group ?? ''} ${command.source ?? ''}`);
    return { command, index, rank: Math.max(nameRank, metadataRank < 0 ? -1 : metadataRank * 0.85) };
  }).filter((item) => item.rank >= 0).sort((a, b) => b.rank - a.rank || a.index - b.index).slice(0, 12).map((item) => item.command);
}
