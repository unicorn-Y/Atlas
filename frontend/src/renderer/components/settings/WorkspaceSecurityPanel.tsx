import { useEffect, useRef, useState } from 'react';
import { Box, FileCheck2, FolderPlus, Globe, LoaderCircle, RefreshCw, ShieldCheck, X } from 'lucide-react';
import type { ConversationSummary, ConversationUpdate, PermissionMode, SandboxStatus } from '@atlas/backend-adapter';
import styles from '../../App.module.css';
import { Button } from '../../ui/Button';
import { backend } from '../../store/useAtlasStore';

type Patch = Omit<ConversationUpdate, 'title' | 'pinned' | 'archived'>;

const permissionOptions: Array<{ value: PermissionMode; label: string; hint: string }> = [
  { value: 'full_access', label: '完全访问', hint: 'Atlas 直接读写文件、运行命令（默认）。' },
  { value: 'ask_each', label: '每步确认', hint: '每次调用工具前都先问你。' },
  { value: 'ask_writes', label: '改前问我', hint: '改文件、运行命令前先问你。' },
  { value: 'auto_file', label: '自动改文件', hint: '文件编辑自动进行，命令和 MCP 写操作前先问你。' },
  { value: 'plan', label: '计划模式', hint: '只读探索并先提交计划，批准后再执行。' },
  { value: 'read_only', label: '只读', hint: '只能查看，不能修改。' },
];

/** A standing grant: one "always allow" the user handed the agent. */
interface StandingGrant {
  request_fingerprint?: string;
  tool?: string;
  workspace?: string;
  scope?: string;
  granted_at?: string;
}

interface PermissionsSnapshot {
  count: number;
  by_tool: Record<string, number>;
  grants: StandingGrant[];
}

async function permissionsRequest(apiBaseUrl: string, path: string, method: 'GET' | 'POST', body?: unknown): Promise<PermissionsSnapshot> {
  const baseUrl = apiBaseUrl.replace(/\/+$/, '');
  const response = await fetch(`${baseUrl}/api/permissions${path}`, {
    method,
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  });
  const text = await response.text();
  let parsed: unknown;
  try { parsed = text ? JSON.parse(text) as unknown : null; } catch { parsed = text; }
  if (!response.ok) {
    const detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? String(parsed.detail) : '';
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return parsed as PermissionsSnapshot;
}


const fieldClass = 'w-full rounded-[9px] bg-sunken px-3 py-2 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
const pathInputClass = 'min-w-0 flex-1 rounded-[9px] bg-sunken px-3 py-2 text-[12px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

function isAbsoluteLocalPath(value: string): boolean {
  return value.startsWith('/') || /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('\\\\');
}

interface WorkspaceTrustState {
  root: string;
  trusted: boolean;
  revoked?: boolean;
}

async function requestWorkspaceTrust(apiBaseUrl: string, root: string, method: 'GET' | 'DELETE'): Promise<WorkspaceTrustState> {
  const baseUrl = apiBaseUrl.replace(/\/+$/, '');
  const response = await fetch(`${baseUrl}/api/workspace/security/trust?root=${encodeURIComponent(root)}`, { method });
  const text = await response.text();
  let body: unknown;
  try { body = text ? JSON.parse(text) as unknown : null; } catch { body = text; }
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? String(body.detail) : '';
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return body as WorkspaceTrustState;
}

/**
 * Conversation-scoped workspace security controls backed by the existing
 * conversation update API. Workspace rule trust remains a run-time approval.
 */
export default function WorkspaceSecurityPanel({ apiBaseUrl, conversation, onChange }: {
  apiBaseUrl: string;
  conversation: ConversationSummary;
  onChange: (patch: Patch) => void;
}) {
  const [sandboxStatus, setSandboxStatus] = useState<SandboxStatus | null>(null);
  const [checkingDocker, setCheckingDocker] = useState(true);
  const [dockerError, setDockerError] = useState('');
  const [trustState, setTrustState] = useState<WorkspaceTrustState | null>(null);
  const [trustLoading, setTrustLoading] = useState(false);
  const [trustBusy, setTrustBusy] = useState(false);
  const [trustError, setTrustError] = useState('');
  const [trustNotice, setTrustNotice] = useState('');
  const [trustRefresh, setTrustRefresh] = useState(0);
  const [allowedPathDraft, setAllowedPathDraft] = useState('');
  const [extraRootDraft, setExtraRootDraft] = useState('');
  const [pathError, setPathError] = useState('');
  const [grants, setGrants] = useState<PermissionsSnapshot | null>(null);
  const [grantsError, setGrantsError] = useState('');
  const [grantsBusy, setGrantsBusy] = useState(false);
  const [grantsNotice, setGrantsNotice] = useState('');

  useEffect(() => {
    let current = true;
    setCheckingDocker(true);
    setDockerError('');
    void backend.getSandboxStatus().then((status) => {
      if (current) setSandboxStatus(status);
    }).catch((error: unknown) => {
      if (current) {
        setSandboxStatus(null);
        setDockerError(error instanceof Error ? error.message : String(error));
      }
    }).finally(() => {
      if (current) setCheckingDocker(false);
    });
    return () => { current = false; };
  }, []);

  const permission = conversation.permission_mode ?? 'full_access';
  const docker = conversation.sandbox?.type === 'docker' ? conversation.sandbox : null;
  const workspace = conversation.workspace ?? '';
  const remoteWorkspace = workspace.startsWith('ssh://');
  const allowedPaths = conversation.allowed_paths ?? [];
  const extraRoots = conversation.extra_roots ?? [];
  const restrictedPaths = allowedPaths.length > 0;
  const additionalAllowedPaths = allowedPaths.filter((path) => path !== workspace);
  const workspaceRef = useRef(workspace);
  workspaceRef.current = workspace;

  useEffect(() => {
    setAllowedPathDraft('');
    setExtraRootDraft('');
    setPathError('');
  }, [conversation.id]);

  useEffect(() => {
    let current = true;
    setTrustState(null);
    setTrustError('');
    setTrustNotice('');
    if (!workspace || remoteWorkspace) {
      setTrustLoading(false);
      return () => { current = false; };
    }
    setTrustLoading(true);
    void requestWorkspaceTrust(apiBaseUrl, workspace, 'GET').then((state) => {
      if (current) setTrustState(state);
    }).catch((error: unknown) => {
      if (current) setTrustError(error instanceof Error ? error.message : String(error));
    }).finally(() => {
      if (current) setTrustLoading(false);
    });
    return () => { current = false; };
  }, [apiBaseUrl, remoteWorkspace, trustRefresh, workspace]);

  // Standing grants are global, not per conversation: the "always allow" a user
  // clicked yesterday still applies today, and nothing in the product could list
  // or revoke it. Fetched once per panel open.
  useEffect(() => {
    let current = true;
    setGrantsError('');
    void permissionsRequest(apiBaseUrl, '', 'GET').then((snapshot) => {
      if (current) setGrants(snapshot);
    }).catch((error: unknown) => {
      if (current) setGrantsError(error instanceof Error ? error.message : String(error));
    });
    return () => { current = false; };
  }, [apiBaseUrl]);

  const revokeGrant = async (grant: StandingGrant) => {
    setGrantsBusy(true);
    setGrantsError('');
    setGrantsNotice('');
    try {
      // The API refuses an unfiltered revoke on purpose, so send the narrowest
      // identity the grant actually carries.
      const filter = grant.request_fingerprint
        ? { request_fingerprint: grant.request_fingerprint }
        : grant.tool
          ? { tool: grant.tool }
          : { workspace: grant.workspace };
      const snapshot = await permissionsRequest(apiBaseUrl, '/revoke', 'POST', filter);
      setGrants(snapshot);
      setGrantsNotice(`已撤销 ${grant.tool || grant.workspace || '这条授权'} 的长期许可。`);
    } catch (error) {
      setGrantsError(error instanceof Error ? error.message : String(error));
    } finally {
      setGrantsBusy(false);
    }
  };

  const revokeAllGrants = async () => {
    setGrantsBusy(true);
    setGrantsError('');
    setGrantsNotice('');
    try {
      const snapshot = await permissionsRequest(apiBaseUrl, '/clear', 'POST');
      setGrants(snapshot);
      setGrantsNotice('已清空所有长期授权；之后每一步都会重新询问。');
    } catch (error) {
      setGrantsError(error instanceof Error ? error.message : String(error));
    } finally {
      setGrantsBusy(false);
    }
  };

  const externalExecutor = Boolean(conversation.executor && conversation.executor !== 'atlas');
  const dockerBlock = remoteWorkspace
    ? '远程工作区暂不支持 Docker 沙箱。'
    : externalExecutor
      ? 'Docker 沙箱只支持 Atlas Agent；先在运行方式设置中切回 Atlas。'
      : sandboxStatus && !sandboxStatus.docker.available
        ? sandboxStatus.docker.detail
        : '';

  const selectPermission = (mode: PermissionMode) => {
    const patch: Patch = { permission_mode: mode };
    if (externalExecutor && mode !== 'full_access') patch.executor = 'atlas';
    onChange(patch);
  };

  const enableDocker = () => onChange({ sandbox: { type: 'docker', network: false } });
  const disableDocker = () => onChange({ sandbox: null });
  const toggleNetwork = () => {
    if (docker) onChange({ sandbox: { ...docker, network: !docker.network } });
  };
  const addAllowedPath = () => {
    const path = allowedPathDraft.trim();
    if (!path) return;
    if (remoteWorkspace || !isAbsoluteLocalPath(path)) {
      setPathError('允许目录必须是本机绝对路径；远程 SSH 工作区不能在这里添加本机允许目录。');
      return;
    }
    const next = restrictedPaths ? [...allowedPaths] : (workspace ? [workspace] : []);
    if (!next.includes(path)) next.push(path);
    onChange({ allowed_paths: next });
    setAllowedPathDraft('');
    setPathError('');
  };
  const removeAllowedPath = (path: string) => {
    let next = allowedPaths.filter((item) => item !== path);
    if (!next.length && workspace && !remoteWorkspace) next = [workspace];
    onChange({ allowed_paths: next });
  };
  const addExtraRoot = () => {
    const path = extraRootDraft.trim();
    if (!path) return;
    if (!(path.startsWith('ssh://') || isAbsoluteLocalPath(path))) {
      setPathError('附加目录必须是本机绝对路径或 ssh:// 地址。');
      return;
    }
    if (path === workspace || extraRoots.includes(path)) {
      setPathError('这个目录已是主工作区或已在附加目录列表中。');
      return;
    }
    if (extraRoots.length >= 5) {
      setPathError('每个对话最多添加 5 个附加目录。');
      return;
    }
    onChange({ extra_roots: [...extraRoots, path] });
    setExtraRootDraft('');
    setPathError('');
  };
  const revokeTrust = async () => {
    if (!workspace || remoteWorkspace) return;
    setTrustBusy(true);
    setTrustError('');
    setTrustNotice('');
    try {
      const state = await requestWorkspaceTrust(apiBaseUrl, workspace, 'DELETE');
      if (workspaceRef.current === workspace) {
        setTrustState(state);
        setTrustNotice(state.revoked
          ? '已撤销此工作区的规则信任；正在运行的任务不受影响，下次运行会再次询问。'
          : '此工作区当前没有已保存的信任。');
      }
    } catch (error) {
      if (workspaceRef.current === workspace) setTrustError(error instanceof Error ? error.message : String(error));
    } finally {
      setTrustBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="工作区安全设置">
    <div className={styles.settingsCardHeading}>
      <div>
        <h2>工作区安全</h2>
        <p>规则信任、会话权限和命令隔离。</p>
      </div>
      <ShieldCheck size={18} className="text-fg-3" />
    </div>

    <div className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="flex items-start gap-2.5">
        <FileCheck2 size={16} className="mt-0.5 shrink-0 text-fg-3" />
        <div className="grid gap-1">
          <strong className="text-[13px] font-medium text-fg">AGENTS.md / CLAUDE.md 规则信任</strong>
          <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
            运行前会检查工作区的 AGENTS.md、CLAUDE.md、.atlas/rules.md、.atlas/NOTES.md 和支持的 Agent 规则文件。检测到未信任规则时，对话中会出现“信任并加载”或“不加载，继续”的确认卡。接受后，该工作区的信任会保存在本机；拒绝只会跳过这次运行的规则文件。
          </p>
          <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
            工作区规则可以给 Atlas 任意指令；只信任你了解的项目。状态按本机工作区信任表读取，撤销后只影响之后的运行。当前工作区：{workspace || '尚未设置'}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className={`break-all text-[12px] ${trustState?.trusted ? 'text-ok' : 'text-fg-3'}`}>
              {!workspace ? '先为此对话选择工作区。'
                : remoteWorkspace ? '远程 SSH 工作区的信任仍由运行时确认卡管理。'
                  : trustLoading ? '正在读取本机信任状态…'
                    : trustError ? '无法读取工作区信任状态。'
                      : trustState?.trusted ? `已信任：${trustState.root}`
                        : `尚未信任：${trustState?.root ?? workspace}`}
            </span>
            {workspace && !remoteWorkspace && <div className="flex gap-2">
              <Button variant="ghost" size="sm" disabled={trustLoading || trustBusy} onClick={() => setTrustRefresh((value) => value + 1)}>
                {trustLoading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新
              </Button>
              {trustState?.trusted && <Button variant="danger" size="sm" disabled={trustBusy} onClick={() => void revokeTrust()}>
                {trustBusy ? <LoaderCircle className="spin" /> : null}撤销信任
              </Button>}
            </div>}
          </div>
          {trustError && <p className={`${styles.settingsError} m-0`} role="alert">读取或撤销信任失败：{trustError}</p>}
          {trustNotice && <p className={`${styles.settingsStatus} m-0`} role="status">{trustNotice}</p>}
        </div>
      </div>
    </div>

    <div className="grid gap-3 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="grid gap-1">
        <strong className="text-[13px] font-medium text-fg">文件工具允许目录</strong>
        <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
          {restrictedPaths
            ? `当前限制已开启。主工作区${workspace ? `（${workspace}）` : ''}始终允许，下面列出的本机目录也允许文件工具访问。`
            : '当前未设置目录 allowlist；文件工具不受额外路径列表限制。设置后，文件工具只能访问主工作区和列出的目录。'}
          {' '}此列表只检查工具调用中明确提供的路径参数，不是操作系统沙箱；命令本身的文件访问需用 Docker 隔离。
        </p>
      </div>
      {restrictedPaths && <div className="grid gap-1.5">
        <p className="m-0 text-[11.5px] text-fg-3">主工作区：{workspace || '未设置；当前没有隐含的主工作区根目录'}</p>
        {additionalAllowedPaths.length ? additionalAllowedPaths.map((path) => <div key={path} className="flex min-w-0 items-center gap-2 rounded-lg bg-card px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--line)]">
          <span className="min-w-0 flex-1 break-all text-[12px] text-fg" title={path}>{path}</span>
          <Button type="button" variant="ghost" size="icon-sm" aria-label={`移除允许目录 ${path}`} title="移除允许目录" onClick={() => removeAllowedPath(path)}><X /></Button>
        </div>) : <p className="m-0 text-[12px] text-fg-3">目前只允许主工作区。</p>}
      </div>}
      <div className="flex flex-wrap gap-2">
        <input
          aria-label="本机绝对路径"
          className={pathInputClass}
          value={allowedPathDraft}
          onChange={(event) => { setAllowedPathDraft(event.target.value); setPathError(''); }}
          onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addAllowedPath(); } }}
          placeholder={remoteWorkspace ? '远程工作区不支持添加本机允许目录' : '本机绝对路径，例如 D:\\Projects\\Atlas'}
          disabled={remoteWorkspace}
        />
        <Button type="button" variant="secondary" size="sm" disabled={remoteWorkspace || !allowedPathDraft.trim()} onClick={addAllowedPath}><FolderPlus />允许目录</Button>
        {!restrictedPaths && <Button type="button" variant="ghost" size="sm" disabled={!workspace || remoteWorkspace} onClick={() => { onChange({ allowed_paths: [workspace] }); setPathError(''); }}>仅限主工作区</Button>}
        {restrictedPaths && <Button type="button" variant="ghost" size="sm" onClick={() => { onChange({ allowed_paths: [] }); setPathError(''); }}>恢复不限目录</Button>}
      </div>
      <div className="grid gap-1 border-t border-line pt-3">
        <strong className="text-[13px] font-medium text-fg">附加工作区目录 <span className="font-normal text-fg-3">{extraRoots.length}/5</span></strong>
        <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
          附加目录会加入新运行的工作区上下文，并检查其中的支持规则文件；未信任的规则仍会由运行时确认卡询问。开启上方 allowlist 时，本机附加目录也会并入允许路径。
        </p>
        {extraRoots.length > 0 && <div className="grid gap-1.5">
          {extraRoots.map((path) => <div key={path} className="flex min-w-0 items-center gap-2 rounded-lg bg-card px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--line)]">
            <span className="min-w-0 flex-1 break-all text-[12px] text-fg" title={path}>{path}</span>
            <Button type="button" variant="ghost" size="icon-sm" aria-label={`移除附加目录 ${path}`} title="移除附加目录" onClick={() => onChange({ extra_roots: extraRoots.filter((item) => item !== path) })}><X /></Button>
          </div>)}
        </div>}
        <div className="flex flex-wrap gap-2">
          <input
            aria-label="附加目录路径"
            className={pathInputClass}
            value={extraRootDraft}
            onChange={(event) => { setExtraRootDraft(event.target.value); setPathError(''); }}
            onKeyDown={(event) => { if (event.key === 'Enter') { event.preventDefault(); addExtraRoot(); } }}
            placeholder="本机绝对路径或 ssh://user@host/path"
            disabled={extraRoots.length >= 5}
          />
          <Button type="button" variant="secondary" size="sm" disabled={extraRoots.length >= 5 || !extraRootDraft.trim()} onClick={addExtraRoot}><FolderPlus />添加目录</Button>
        </div>
      </div>
      {pathError && <p className={`${styles.settingsError} m-0`} role="alert">{pathError}</p>}
      <p className="m-0 text-[11.5px] text-fg-3">目录修改会自动保存到当前对话，只影响后续启动的运行；清空 allowed_paths 会恢复默认的不限制路径列表。服务端检查绝对路径和 SSH 地址格式，但不验证本机目录是否存在。</p>
    </div>

    <div className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <label className="grid gap-1.5 text-[12px] text-fg-2" htmlFor="workspace-permission-mode">
        <span className="font-medium text-fg">后续运行的工具权限</span>
        <select id="workspace-permission-mode" className={fieldClass} value={permission}
          onChange={(event) => selectPermission(event.target.value as PermissionMode)}>
          {permissionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
        {permissionOptions.find((option) => option.value === permission)?.hint} 设置保存在当前对话，只影响之后启动的运行。
      </p>
      {externalExecutor && <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
        当前使用外部 Agent。外部 Agent 不经过 Atlas 的工具确认；选择任何非“完全访问”模式会按现有行为自动切回 Atlas。
      </p>}
    </div>

    <div className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="flex items-start gap-2.5">
        <ShieldCheck size={16} className="mt-0.5 shrink-0 text-fg-3" />
        <div className="grid min-w-0 flex-1 gap-1">
          <strong className="text-[13px] font-medium text-fg">
            长期授权 <span className="font-normal text-fg-3">{grants ? `${grants.count} 条` : '读取中…'}</span>
          </strong>
          <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
            在确认卡上点“始终允许”会写入一条长期授权，对所有之后的工作区生效。这里能看到它们，也能单条撤销或全部清空；此前只能添加，无法查看和撤销。
          </p>
        </div>
      </div>
      {grantsError && <p className={styles.settingsError} role="alert">{grantsError}</p>}
      {grants && grants.count > 0 && <>
        <div className="grid gap-1.5">
          {grants.grants.slice(0, 12).map((grant, index) => <div
            key={`${grant.request_fingerprint || grant.tool || grant.workspace || index}`}
            className="flex min-w-0 items-center gap-2 rounded-lg bg-card px-2.5 py-2 shadow-[inset_0_0_0_1px_var(--line)]">
            <div className="grid min-w-0 flex-1 gap-0.5">
              <span className="truncate text-[12px] text-fg" title={grant.scope || grant.tool}>{grant.tool || '未标注工具'}</span>
              <span className="truncate text-[11px] text-fg-3" title={grant.workspace}>{grant.workspace || '所有工作区'}</span>
            </div>
            <Button type="button" variant="ghost" size="icon-sm" disabled={grantsBusy}
              aria-label={`撤销 ${grant.tool || '这条授权'}`} title="撤销这条授权"
              onClick={() => void revokeGrant(grant)}><X /></Button>
          </div>)}
          {grants.count > 12 && <p className="m-0 text-[11.5px] text-fg-3">还有 {grants.count - 12} 条未列出；清空会一并处理。</p>}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-[11.5px] text-fg-3">
            {Object.entries(grants.by_tool).slice(0, 4).map(([tool, count]) => `${tool} × ${count}`).join('、')}
          </span>
          <Button type="button" variant="ghost" size="sm" disabled={grantsBusy} onClick={() => void revokeAllGrants()}>全部撤销</Button>
        </div>
      </>}
      {grants && grants.count === 0 && <p className="m-0 text-[12px] text-fg-3">当前没有长期授权；每一步都会按上面的权限模式询问。</p>}
      {grantsNotice && <p className="m-0 text-[12px] text-ok" role="status">{grantsNotice}</p>}
    </div>

    <div className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="flex items-start gap-2.5">
        <Box size={16} className="mt-0.5 shrink-0 text-fg-3" />
        <div className="grid min-w-0 flex-1 gap-1">
          <strong className="text-[13px] font-medium text-fg">Docker 命令隔离</strong>
          <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
            容器设置保存在当前对话，只对之后的运行生效；容器联网默认关闭。
          </p>
        </div>
      </div>

      {docker ? <>
        {dockerBlock && <p className={styles.settingsError} role="alert">{dockerBlock}</p>}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="flex items-center gap-2 text-[12.5px] text-fg">
            <input type="checkbox" checked={Boolean(docker.network)} onChange={toggleNetwork} />
            <Globe size={15} />允许容器联网
          </label>
          <Button variant="ghost" size="sm" onClick={disableDocker}>关闭 Docker 隔离</Button>
        </div>
        {docker.network && <p className="m-0 text-[12px] leading-[1.55] text-fg-3">
          联网权限会开放给容器内运行的命令；只在安装依赖或访问网络资源时开启。
        </p>}
      </> : <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-[12px] text-fg-3">
          {dockerBlock || (checkingDocker ? '正在检查 Docker…' : '当前命令在本机运行。')}
        </span>
        <Button variant="secondary" size="sm" disabled={checkingDocker || !sandboxStatus || Boolean(dockerBlock)} onClick={enableDocker}>
          启用 Docker 隔离
        </Button>
      </div>}
      {dockerError && <p className={styles.settingsError} role="alert">Docker 状态检查失败：{dockerError}</p>}
    </div>
  </section>;
}
