import { useState } from 'react';
import { Bot, Box, FolderLock, FolderPlus, FolderTree, Globe, HardDrive, Laptop, MessagesSquare, Shield, X } from 'lucide-react';
import type { ConversationSummary, ConversationUpdate, ExternalAgentInfo, SandboxStatus } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuSub, MenuTrigger } from '../ui/Menu';
import { Tip } from '../ui/Tooltip';
import { cn } from '../ui/cn';

type Patch = Omit<ConversationUpdate, 'title' | 'pinned' | 'archived'>;

/**
 * How the conversation's next runs execute: who does the work (Atlas or an external Agent),
 * where commands run (this machine or a Docker container), and which folders file tools may touch.
 */
export default function RunSetupMenu({ conversation, workspace, onChange, onPickFolder, moa, onToggleMoa }: {
  conversation: ConversationSummary; workspace: string; onChange: (patch: Patch) => void; onPickFolder: () => Promise<string | null>;
  /** The next message asks reference models first. */
  moa: boolean; onToggleMoa: () => void;
}) {
  const [agents, setAgents] = useState<ExternalAgentInfo[] | null>(null);
  const [sandbox, setSandbox] = useState<SandboxStatus | null>(null);
  const [references, setReferences] = useState<string[] | null>(null);
  const remote = workspace.startsWith('ssh://');
  const executor = conversation.executor || 'atlas';
  const container = conversation.sandbox?.type === 'docker' ? conversation.sandbox : null;
  const allowed = conversation.allowed_paths ?? [];
  const restricted = allowed.length > 0;
  const fullAccess = (conversation.permission_mode ?? 'full_access') === 'full_access';
  const agentName = agents?.find((agent) => agent.id === executor)?.name ?? EXECUTOR_NAME[executor] ?? executor;

  const load = () => {
    void backend.getExternalAgents().then(setAgents).catch(() => setAgents([]));
    void backend.getSandboxStatus().then(setSandbox).catch(() => setSandbox(null));
    void backend.getAgentSettings().then((settings) => setReferences(settings.moa_reference_models)).catch(() => setReferences([]));
  };
  const extraRoots = conversation.extra_roots ?? [];
  const addRoot = async () => {
    const picked = await onPickFolder();
    if (picked && picked !== workspace && !extraRoots.includes(picked)) onChange({ extra_roots: [...extraRoots, picked] });
  };
  const addFolder = async () => {
    const picked = await onPickFolder();
    if (picked && !allowed.includes(picked)) onChange({ allowed_paths: [...(allowed.length ? allowed : [workspace]), picked] });
  };

  const label = [moa ? '会诊' : '', executor !== 'atlas' ? agentName : '', container ? '容器' : '', extraRoots.length ? `+${extraRoots.length} 目录` : '', restricted ? '限目录' : ''].filter(Boolean).join(' · ');
  const agentBlocked = remote ? '远程目录暂不支持外部 Agent' : !fullAccess ? '外部 Agent 的操作不经过 Atlas 确认，只能在「完全访问」下用' : '';
  const dockerBlocked = remote ? '远程目录不能用容器' : executor !== 'atlas' ? '容器只支持 Atlas 自己执行' : sandbox && !sandbox.docker.available ? sandbox.docker.detail : '';

  return <Menu onOpenChange={(open) => { if (open) load(); }}>
    <Tip label="运行方式：会诊、谁来做、命令在哪跑、能碰哪些目录"><MenuTrigger asChild>
      <button type="button" className={cn('inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2 text-[12.5px] hover:bg-hover', label ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:text-fg')}>
        {moa ? <MessagesSquare size={15} /> : container ? <Box size={15} /> : executor !== 'atlas' ? <Bot size={15} /> : restricted ? <FolderLock size={15} /> : <Laptop size={15} />}{label && <span className="max-w-[140px] truncate">{label}</span>}
      </button>
    </MenuTrigger></Tip>
    <MenuContent side="top" className="w-[300px]">
      <MenuLabel>下一条</MenuLabel>
      <MenuItem checked={moa} disabled={!moa && references !== null && !references.length} onSelect={(event) => { event.preventDefault(); onToggleMoa(); }}>
        <MessagesSquare /><Option title="多模型会诊" hint={references === null ? '先听几个参考模型的意见再回答'
          : references.length ? `参考 ${references.length} 个模型：${references.slice(0, 2).join('、')}${references.length > 2 ? '…' : ''}` : '先在 设置 → 子 Agent 里选参考模型'} />
      </MenuItem>
      <MenuSeparator />
      <MenuLabel>这个对话</MenuLabel>
      <MenuSub icon={<Bot />} label="由谁来做" value={executor === 'atlas' ? 'Atlas' : agentName}>
        <MenuItem checked={executor === 'atlas'} onSelect={() => onChange({ executor: 'atlas' })}>
          <Option title="Atlas" hint="用这里选的模型和角色（默认）" />
        </MenuItem>
        {agents === null && <p className="m-0 px-2.5 py-1.5 text-[12px] text-fg-3">正在查找已安装的 Agent…</p>}
        {agents?.filter((agent) => agent.available || agent.id === executor).map((agent) => <MenuItem key={agent.id} checked={executor === agent.id}
          disabled={!agent.available || Boolean(agentBlocked)} onSelect={() => onChange({ executor: agent.id, sandbox: null })}>
          <Option title={agent.name} hint={agentBlocked || (agent.available ? agent.version ?? '已安装' : agent.detail)} />
        </MenuItem>)}
        {agents && agents.some((agent) => !agent.available && agent.id !== executor) && <p className="m-0 px-2.5 pt-0.5 pb-1.5 text-[11.5px] leading-[1.5] text-fg-3">
          装好命令行后也可以交给：{agents.filter((agent) => !agent.available && agent.id !== executor).map((agent) => agent.name).join('、')}
        </p>}
      </MenuSub>
      <MenuSub icon={<HardDrive />} label="命令在哪里跑" value={container ? `容器${container.network ? '（联网）' : ''}` : '这台电脑'}>
        <MenuItem checked={!container} onSelect={() => onChange({ sandbox: null })}><Option title="这台电脑" hint="直接在工作目录里运行（默认）" /></MenuItem>
        <MenuItem checked={Boolean(container)} disabled={Boolean(dockerBlocked) || !sandbox} onSelect={() => onChange({ sandbox: { type: 'docker', network: false } })}>
          <Option title="Docker 容器" hint={dockerBlocked || (sandbox ? `工作目录挂进容器，命令的副作用关在里面；默认不联网${sandbox.docker.version ? ` · Docker ${sandbox.docker.version}` : ''}` : '正在检查 Docker…')} />
        </MenuItem>
        {container && <MenuItem checked={Boolean(container.network)} onSelect={(event) => { event.preventDefault(); onChange({ sandbox: { ...container, network: !container.network } }); }}>
          <Globe /><Option title="容器可以联网" hint="装依赖、拉代码时需要" />
        </MenuItem>}
      </MenuSub>
      <MenuSub icon={<FolderTree />} label="附加目录" value={extraRoots.length ? `${extraRoots.length} 个` : '无'}>
        <MenuLabel>同时处理几个文件夹</MenuLabel>
        {extraRoots.map((path) => <MenuItem key={path} onSelect={(event) => { event.preventDefault(); onChange({ extra_roots: extraRoots.filter((item) => item !== path) }); }}>
          <X /><span className="min-w-0 truncate text-[12.5px]" title={`${path}（点击移除）`}>{path}</span>
        </MenuItem>)}
        <MenuItem disabled={!workspace || extraRoots.length >= 5} onSelect={() => void addRoot()}>
          <FolderPlus /><Option title={extraRoots.length ? '再加一个目录…' : '添加目录…'} hint={!workspace ? '先选主工作目录' : extraRoots.length >= 5 ? '最多 5 个' : 'Atlas 可以用绝对路径读写这些目录，规则文件同样要你确认'} />
        </MenuItem>
      </MenuSub>
      <MenuSub icon={<Shield />} label="文件访问范围" value={restricted ? '只限工作目录' : '不限制'}>
        <MenuItem checked={!restricted} onSelect={() => onChange({ allowed_paths: [] })}><Option title="不限制" hint="默认" /></MenuItem>
        <MenuItem checked={restricted} disabled={!workspace || remote} onSelect={() => { if (!restricted) onChange({ allowed_paths: [workspace] }); }}>
          <Option title="只限工作目录" hint={!workspace ? '先选一个工作目录' : remote ? '远程目录已限定在该目录内' : '文件工具碰不到别处；命令行只限定起始目录，要完全隔离请用容器'} />
        </MenuItem>
        {restricted && allowed.filter((path) => path !== workspace).map((path) => <MenuItem key={path} onSelect={(event) => { event.preventDefault(); onChange({ allowed_paths: allowed.filter((item) => item !== path) }); }}>
          <X /><span className="min-w-0 truncate text-[12.5px]" title={`${path}（点击移除）`}>{path}</span>
        </MenuItem>)}
        {restricted && <MenuItem onSelect={() => void addFolder()}><FolderPlus /><span>再允许一个目录…</span></MenuItem>}
      </MenuSub>
    </MenuContent>
  </Menu>;
}

const EXECUTOR_NAME: Record<string, string> = { codex: 'Codex', claude: 'Claude Code', hermes: 'Hermes', pi: 'Pi', zcode: 'ZCode' };

function Option({ title, hint }: { title: string; hint?: string }) {
  return <span className="min-w-0"><span className="block">{title}</span>{hint && <small className="block text-[11.5px] leading-[1.45] text-fg-3">{hint}</small>}</span>;
}
