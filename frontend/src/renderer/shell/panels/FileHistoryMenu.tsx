import { useState } from 'react';
import { GitCommitHorizontal, History, Save } from 'lucide-react';
import type { WorkspaceFile, WorkspaceVersion } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '../../ui/Menu';

export type ViewedVersion = { id: string; label: string; file: WorkspaceFile };

const when = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
};
const size = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`;

/** Earlier versions of a file: Atlas's snapshots before each change, plus recent git commits. */
export default function FileHistoryMenu({ workspace, path, onView, onError }: {
  workspace: string; path: string; onView: (version: ViewedVersion) => void; onError: (text: string) => void;
}) {
  const [versions, setVersions] = useState<WorkspaceVersion[] | null>(null);
  const load = () => {
    setVersions(null);
    backend.getFileHistory(workspace, path).then(setVersions).catch((exc) => { setVersions([]); onError(exc instanceof Error ? exc.message : String(exc)); });
  };
  const open = async (version: WorkspaceVersion) => {
    try {
      const file = await backend.getVersionContent(workspace, path, version.id);
      onView({ id: version.id, label: `${when(version.created_at)} ${version.source === 'git' ? '的提交' : '改动前'}`, file });
    } catch (exc) { onError(exc instanceof Error ? exc.message : String(exc)); }
  };
  return <Menu onOpenChange={(value) => { if (value) load(); }}>
    <MenuTrigger asChild>
      <button title="历史版本" aria-label="历史版本" className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><History size={13} /></button>
    </MenuTrigger>
    <MenuContent align="end" className="w-[280px]">
      <MenuLabel>历史版本</MenuLabel>
      {versions === null && <p className="m-0 px-2.5 py-1.5 text-[12px] text-fg-3">正在读取…</p>}
      {versions?.length === 0 && <p className="m-0 px-2.5 py-1.5 text-[12px] text-fg-3">还没有历史版本。Atlas 改这个文件前会自动存一份。</p>}
      {versions?.map((version) => <MenuItem key={version.id} onSelect={() => void open(version)} hint={version.bytes ? size(version.bytes) : '不存在'}>
        {version.source === 'git' ? <GitCommitHorizontal /> : <Save />}
        <span className="min-w-0"><span className="block">{when(version.created_at)}</span>
          <small className="block text-[11.5px] text-fg-3">{version.source === 'git' ? `提交 ${version.id.slice(4, 11)}` : 'Atlas 改动前的快照'}</small></span>
      </MenuItem>)}
    </MenuContent>
  </Menu>;
}
