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
  /** Usage text shown in help and while completing the command name. */
  argumentHint?: string;
  /** Dynamic command state. Unavailable commands remain visible with this reason. */
  disabledReason?: string;
  requiresConversation?: boolean;
  requiresIdle?: boolean;
  run: (argument: string) => void;
}

export function resolveSlashAvailability(command: SlashCommand, state: { hasConversation: boolean; busy: boolean }): SlashCommand {
  if (command.disabledReason) return command;
  if (command.requiresConversation && !state.hasConversation) return { ...command, disabledReason: '先打开一个会话' };
  if (command.requiresIdle && state.busy) return { ...command, disabledReason: '任务运行时不可用' };
  return command;
}

/** Register a command set with stable IDs and explicit display origins. */
export function registerSlashCommands(commands: readonly SlashCommand[]): SlashCommand[] {
  const ids = new Set<string>();
  return commands.map((command) => {
    if (!command.id.trim() || ids.has(command.id)) throw new Error(`Duplicate or empty slash command ID: ${command.id}`);
    ids.add(command.id);
    const source = command.source ?? (command.id.startsWith('skill-') ? '技能' : command.id.startsWith('command-') ? '自定义命令' : 'Atlas');
    return { ...command, source, argumentHint: command.takesArgument ? command.argumentHint || inferArgumentHint(command.id) : undefined };
  });
}

function inferArgumentHint(id: string): string {
  const hints: Record<string, string> = {
    tag: '颜色或 clear', rename: '新名称', resume: '名称或会话 ID', fork: '检查点 ID', rewind: '检查点 ID',
    side: '问题', btw: '问题', compact: '摘要保留说明', share: 'tools 或 thinking', busy: '时长或 off',
    pr: 'new 或 PR 编号', cd: '目录路径或 --none', review: 'branch <名称> 或 commit <SHA>',
    ultrareview: '审查范围', 'security-review': 'branch <名称> 或 commit <SHA>', simplify: '简化范围',
    workflow: '目标', open: '文件或网址', chapter: '章节名称', model: '模型名', fast: 'on、off 或 status',
    suggestions: 'on 或 off', summary: 'on 或 off', insights: '天数（7 或 30），可选模型 ID', advisor: '模型名',
    wake: 'on 或 off', stop: '进程编号（可省略）', goal: '目标操作',
  };
  return hints[id] || '参数';
}

/** Match a `/query` draft against command names, descriptions, groups, origins, and use frequency. */
export function matchSlashCommands(value: string, commands: readonly SlashCommand[], frequency: Readonly<Record<string, number>> = {}): SlashCommand[] {
  const match = /^\/(\S*)(\s[\s\S]*)?$/.exec(value);
  if (!match) return [];
  const [, word, rest] = match;
  if (rest !== undefined) return commands.filter((command) => command.takesArgument && command.label === `/${word}`);
  return commands.map((command, index) => {
    const nameRank = fuzzyScore(word, command.label.slice(1));
    const metadataRank = fuzzyScore(word, `${command.hint ?? ''} ${command.group ?? ''} ${command.source ?? ''}`);
    const rank = Math.max(nameRank, metadataRank < 0 ? -1 : metadataRank * 0.85);
    return { command, index, rank, frequency: frequency[command.id] ?? 0 };
  }).filter((item) => item.rank >= 0).sort((a, b) => b.rank - a.rank || b.frequency - a.frequency || a.index - b.index).slice(0, 12).map((item) => item.command);
}

export function slashCommandUsage(command: SlashCommand): string {
  return `${command.label}${command.takesArgument ? ` <${command.argumentHint || inferArgumentHint(command.id)}>` : ''}`;
}
