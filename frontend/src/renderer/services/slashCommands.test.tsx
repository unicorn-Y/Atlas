import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { matchSlashCommands, registerSlashCommands, registerSlashCommandSource, useSlashCommandSourcesVersion } from './slashCommands';

describe('named slash command sources', () => {
  const disposers: Array<() => void> = [];
  afterEach(() => { disposers.splice(0).reverse().forEach((dispose) => dispose()); });

  it('includes source commands in the normal composer registry and removes them on dispose', () => {
    const execute = vi.fn();
    const dispose = registerSlashCommandSource('Review extension', [{ id: 'extension-review', label: '/audit', takesArgument: true, run: execute }]);
    disposers.push(dispose);
    const commands = registerSlashCommands([{ id: 'new', label: '/new', run: vi.fn() }]);
    const match = matchSlashCommands('/aud', commands)[0];
    expect(match).toMatchObject({ id: 'extension-review', source: 'Review extension', argumentHint: '参数' });
    match.run('the branch');
    expect(execute).toHaveBeenCalledWith('the branch');
    dispose();
    expect(registerSlashCommands([])).toEqual([]);
  });

  it('rejects empty sources, duplicate sources and cross-source command IDs before mutation', () => {
    expect(() => registerSlashCommandSource(' ', [])).toThrow('empty');
    disposers.push(registerSlashCommandSource('one', [{ id: 'shared', label: '/one', run: vi.fn() }]));
    expect(() => registerSlashCommandSource('one', [])).toThrow('Duplicate');
    expect(() => registerSlashCommandSource('two', [{ id: 'shared', label: '/two', run: vi.fn() }])).toThrow('Duplicate');
    expect(registerSlashCommands([]).map((command) => command.label)).toEqual(['/one']);
  });

  it('publishes a component snapshot whenever sources register and dispose', () => {
    const Version = () => <span>{useSlashCommandSourcesVersion()}</span>;
    const before = renderToStaticMarkup(<Version />);
    const dispose = registerSlashCommandSource('version-test', []);
    disposers.push(dispose);
    expect(renderToStaticMarkup(<Version />)).not.toBe(before);
    const registered = renderToStaticMarkup(<Version />);
    dispose();
    expect(renderToStaticMarkup(<Version />)).not.toBe(registered);
  });
});
