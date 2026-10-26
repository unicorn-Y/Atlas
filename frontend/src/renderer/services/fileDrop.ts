export type DroppedFolder = { name: string; path: string; count: number };

export function hasFileDropPayload(dataTransfer: Pick<DataTransfer, 'types'>): boolean {
  return Array.from(dataTransfer.types).includes('Files');
}

/** Keep native file drops from taking over controls and widgets with their own drag behavior. */
export function isBlockedFileDropTarget(target: EventTarget | null): boolean {
  const element = target as (EventTarget & { closest?: (selector: string) => Element | null }) | null;
  return Boolean(element?.closest?.(
    'form,button,a,input,textarea,select,[contenteditable="true"],[role="dialog"],[role="menu"],[data-atlas-drop-ignore],.drag',
  ));
}

export async function readDroppedItems(dataTransfer: DataTransfer): Promise<{
  files: File[];
  folders: DroppedFolder[];
}> {
  const files: File[] = [];
  const folders: DroppedFolder[] = [];
  for (const item of Array.from(dataTransfer.items)) {
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FileSystemEntry | null })
      .webkitGetAsEntry?.();
    if (entry?.isDirectory) {
      const droppedFile = item.getAsFile() as (File & { path?: string }) | null;
      folders.push({
        name: entry.name,
        path: droppedFile?.path || entry.fullPath || entry.name,
        count: await countDroppedFiles(entry as FileSystemDirectoryEntry),
      });
      continue;
    }
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  if (!files.length && !folders.length) files.push(...Array.from(dataTransfer.files));
  return { files, folders };
}

function countDroppedFiles(directory: FileSystemDirectoryEntry): Promise<number> {
  return new Promise((resolve) => {
    let count = 0;
    const reader = directory.createReader();
    const read = () => reader.readEntries(async (entries) => {
      if (!entries.length) { resolve(count); return; }
      const nestedCounts = await Promise.all(entries.map((entry) => entry.isFile ? Promise.resolve(1)
        : entry.isDirectory ? countDroppedFiles(entry as FileSystemDirectoryEntry) : Promise.resolve(0)));
      count += nestedCounts.reduce((sum, value) => sum + value, 0);
      // DirectoryReader returns entries in batches; keep reading until it is exhausted.
      window.setTimeout(read, 0);
    }, () => resolve(count));
    read();
  });
}
