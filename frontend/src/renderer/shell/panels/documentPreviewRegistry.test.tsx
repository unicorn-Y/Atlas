import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { WorkspaceFile } from '@atlas/backend-adapter';
import { canPreviewDocument, DocumentPreview, documentPreviewRenderer, registerDocumentPreview } from './documentPreviewRegistry';

describe('document preview renderer registry', () => {
  it('resolves all built-in preview families with case-insensitive extensions', () => {
    for (const [path, id] of [['notes.MD', 'markdown'], ['image.png', 'image'], ['report.PDF', 'pdf'], ['index.html', 'html'], ['workbook.xlsx', 'office'], ['slides.pptx', 'office']]) {
      expect(documentPreviewRenderer(path)?.id).toBe(id);
    }
    expect(canPreviewDocument('plain.txt')).toBe(false);
  });

  it('renders registered document components and restores the built-in renderer on dispose', () => {
    const dispose = registerDocumentPreview({ id: 'rich-markdown', extensions: ['.MD'], renderer: ({ file }) => <article aria-label="extension document">{file.content}</article> });
    const file = { path: 'notes.md', content: 'rendered through registry' } as WorkspaceFile;
    try {
      expect(renderToStaticMarkup(<DocumentPreview file={file} workspace="C:/ws" fallback={<p>built-in</p>} />)).toContain('extension document');
      expect(documentPreviewRenderer(file.path)?.id).toBe('rich-markdown');
    } finally { dispose(); }
    expect(renderToStaticMarkup(<DocumentPreview file={file} workspace="C:/ws" fallback={<p>built-in</p>} />)).toBe('<p>built-in</p>');
  });

  it('makes new preview formats available and rejects duplicate renderer identities', () => {
    const definition = { id: 'custom-diagram', extensions: ['atlasdiagram'], renderer: () => <div>diagram</div> };
    const dispose = registerDocumentPreview(definition);
    try {
      expect(canPreviewDocument('architecture.atlasdiagram')).toBe(true);
      expect(() => registerDocumentPreview(definition)).toThrow('Duplicate');
    } finally { dispose(); }
    expect(canPreviewDocument('architecture.atlasdiagram')).toBe(false);
  });
});
