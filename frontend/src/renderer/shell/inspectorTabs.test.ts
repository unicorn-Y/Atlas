import { describe, expect, it } from 'vitest';
import { getInspectorTab, listInspectorTabs, registerInspectorTab } from './inspectorTabs';

describe('pluggable inspector tabs', () => {
  it('registers an extension tab and removes only its own registration', () => {
    const first = { id: 'extension:metrics', label: 'Metrics', render: () => null };
    const disposeFirst = registerInspectorTab(first);
    const replacement = { ...first, label: 'Updated metrics' };
    const disposeReplacement = registerInspectorTab(replacement);

    disposeFirst();
    expect(getInspectorTab(first.id)).toBe(replacement);
    expect(listInspectorTabs().some((tab) => tab.id === first.id)).toBe(true);
    disposeReplacement();
    expect(getInspectorTab(first.id)).toBeUndefined();
  });

  it('rejects built-in IDs so extensions cannot shadow core panels', () => {
    expect(() => registerInspectorTab({ id: 'files', label: 'Shadow', render: () => null })).toThrow('reserved');
  });
});
