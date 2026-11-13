export interface StagedAttachment {
  id: string;
  name: string;
  mime: string;
  size: number;
  kind: 'image' | 'file';
}

const DATABASE = 'atlas-attachments-v1';
const STORE = 'content';

export async function contentAddressedId(bytes: Uint8Array<ArrayBufferLike> | ArrayBuffer): Promise<string> {
  const source = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const copy = new Uint8Array(new ArrayBuffer(source.byteLength));
  copy.set(source);
  const digest = await crypto.subtle.digest('SHA-256', copy.buffer as ArrayBuffer);
  return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

export async function readFileBytes(file: Blob, signal: AbortSignal, onProgress: (loaded: number, total: number) => void): Promise<Uint8Array> {
  if (signal.aborted) throw new DOMException('Attachment read cancelled', 'AbortError');
  const reader = file.stream().getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  const abort = () => { void reader.cancel(); };
  signal.addEventListener('abort', abort, { once: true });
  try {
    onProgress(0, file.size);
    while (true) {
      if (signal.aborted) throw new DOMException('Attachment read cancelled', 'AbortError');
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.length;
      onProgress(loaded, file.size);
    }
    if (signal.aborted) throw new DOMException('Attachment read cancelled', 'AbortError');
    const bytes = new Uint8Array(loaded);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return bytes;
  } catch (error) {
    if (signal.aborted) throw new DOMException('Attachment read cancelled', 'AbortError');
    throw error;
  } finally {
    signal.removeEventListener('abort', abort);
    reader.releaseLock();
  }
}

export async function stageAttachment(file: File, kind: StagedAttachment['kind'], signal: AbortSignal, onProgress: (loaded: number, total: number) => void): Promise<StagedAttachment> {
  const bytes = await readFileBytes(file, signal, onProgress);
  const id = await contentAddressedId(bytes);
  if (signal.aborted) throw new DOMException('Attachment staging cancelled', 'AbortError');
  const db = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const abort = () => { try { tx.abort(); } catch { /* transaction already settled */ } };
    const cleanup = () => { signal.removeEventListener('abort', abort); db.close(); };
    tx.objectStore(STORE).put({ id, blob: new Blob([bytes.slice().buffer as ArrayBuffer], { type: file.type }), name: file.name, mime: file.type || 'application/octet-stream', size: bytes.byteLength });
    tx.oncomplete = () => { cleanup(); resolve(); };
    tx.onerror = () => { cleanup(); reject(tx.error ?? new Error('Attachment staging failed')); };
    tx.onabort = () => { cleanup(); reject(signal.aborted ? new DOMException('Attachment staging cancelled', 'AbortError') : tx.error ?? new Error('Attachment staging aborted')); };
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) abort();
  });
  return { id, name: file.name, mime: file.type || 'application/octet-stream', size: bytes.byteLength, kind };
}

export async function loadStagedAttachment(id: string): Promise<Blob | null> {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readonly').objectStore(STORE).get(id);
    request.onsuccess = () => { const blob = (request.result as { blob?: Blob } | undefined)?.blob ?? null; db.close(); resolve(blob); };
    request.onerror = () => { db.close(); reject(request.error ?? new Error('Unable to restore staged attachment')); };
  });
}

async function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Unable to open attachment store'));
  });
}
