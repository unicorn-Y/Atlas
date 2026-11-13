import { describe, expect, it, vi } from 'vitest';
import { createPluginSlashCommand } from './pluginSlashCommands';

describe('plugin slash commands', () => {
  it('maps a direct plugin handler to a slash command with JSON input', async () => {
    const invoke = vi.fn();
    const command = createPluginSlashCommand({
      id: 'plugin-handler:format', name: 'format', description: 'Format a file',
      input: { type: 'object', properties: { path: { type: 'string' } }, required: ['path'] },
    }, invoke);
    expect(command.label).toBe('/format');
    expect(command.source).toBe('插件');
    command.run('{"path":"a.ts"}');
    expect(invoke).toHaveBeenCalledWith('plugin-handler:format', { path: 'a.ts' });
  });

  it('invokes no-argument commands with an empty object and rejects non-object JSON', async () => {
    const invoke = vi.fn();
    const command = createPluginSlashCommand({ id: 'plugin-handler:ping', name: 'ping', description: 'Ping' }, invoke);
    const reportError = vi.fn();
    const invalid = createPluginSlashCommand({ id: 'plugin-handler:other', name: 'other' }, invoke, reportError);
    command.run('');
    expect(invoke).toHaveBeenCalledWith('plugin-handler:ping', {});
    invalid.run('[]');
    expect(reportError).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('JSON object') }));
  });
});
