import { useSyncExternalStore, type ComponentType, type ReactNode } from 'react';
import type { WorkspaceFile } from '@atlas/backend-adapter';

export interface DocumentPreviewProps {
  file: WorkspaceFile;
  workspace: string;
  fallback: ReactNode;
}

export interface DocumentPreviewDefinition {
  id: string;
  extensions: readonly string[];
  renderer: ComponentType<DocumentPreviewProps>;
}

const renderers = new Map<string, DocumentPreviewDefinition>();
const listeners = new Set<() => void>();
let version = 0;
function notifyChanged() { version += 1; for (const listener of listeners) listener(); }

export function useDocumentPreviewRegistryVersion(): number {
  return useSyncExternalStore((listener) => {
    listeners.add(listener);
    return () => { listeners.delete(listener); };
  }, () => version, () => version);
}
const normalizeExtension = (value: string) => value.replace(/^\./, '').toLowerCase();
const BuiltinPreview = ({ fallback }: DocumentPreviewProps) => <>{fallback}</>;

for (const [id, extensions] of Object.entries({
  markdown: ['md', 'markdown'], image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'],
  pdf: ['pdf'], html: ['html', 'htm'], office: ['docx', 'xlsx', 'pptx'],
})) renderers.set(id, { id, extensions, renderer: BuiltinPreview });

/** Later registrations take precedence over built-in file formats until disposed. */
export function registerDocumentPreview(definition: DocumentPreviewDefinition): () => void {
  if (!definition.id.trim() || renderers.has(definition.id)) throw new Error(`Duplicate or empty document preview renderer: ${definition.id}`);
  if (!definition.extensions.length || definition.extensions.some((extension) => !normalizeExtension(extension))) {
    throw new Error('Document preview renderer needs file extensions');
  }
  const registered = { ...definition, extensions: definition.extensions.map(normalizeExtension) };
  renderers.set(definition.id, registered);
  notifyChanged();
  return () => {
    if (renderers.get(definition.id) !== registered) return;
    renderers.delete(definition.id); notifyChanged();
  };
}

export function documentPreviewRenderer(path: string): DocumentPreviewDefinition | undefined {
  const extension = path.split(/[\\/]/).at(-1)?.split('.').slice(1).at(-1)?.toLowerCase();
  return [...renderers.values()].reverse().find((definition) => extension && definition.extensions.includes(extension));
}

export function canPreviewDocument(path: string): boolean {
  return documentPreviewRenderer(path) !== undefined;
}

export function DocumentPreview(props: DocumentPreviewProps) {
  useDocumentPreviewRegistryVersion();
  const Renderer = documentPreviewRenderer(props.file.path)?.renderer;
  return Renderer ? <Renderer {...props} /> : <>{props.fallback}</>;
}
