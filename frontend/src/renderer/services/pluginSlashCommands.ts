import type { SlashCommand } from './slashCommands';

export interface PluginSlashCommandDescriptor {
  id: string;
  name: string;
  description?: string;
  input?: Record<string, unknown>;
}

export function createPluginSlashCommand(
  descriptor: PluginSlashCommandDescriptor,
  invoke: (id: string, arguments_: Record<string, unknown>) => void | Promise<void>,
  reportError: (error: Error) => void = () => undefined,
): SlashCommand {
  return {
    id: descriptor.id,
    label: `/${descriptor.name}`,
    hint: descriptor.description || '插件命令（直接执行）',
    group: '插件',
    source: '插件',
    takesArgument: true,
    argumentHint: 'JSON 参数对象',
    run: (raw) => {
      let arguments_: unknown = {};
      if (raw.trim()) {
        try { arguments_ = JSON.parse(raw); }
        catch { reportError(new Error('参数必须是有效的 JSON object')); return; }
      }
      if (!arguments_ || typeof arguments_ !== 'object' || Array.isArray(arguments_)) {
        reportError(new Error('参数必须是 JSON object'));
        return;
      }
      void Promise.resolve(invoke(descriptor.id, arguments_ as Record<string, unknown>)).catch((error) =>
        reportError(error instanceof Error ? error : new Error(String(error))));
    },
  };
}
