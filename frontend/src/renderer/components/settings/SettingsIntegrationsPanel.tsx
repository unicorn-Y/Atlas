import { ExternalLink, GitPullRequest, MessageCircle, Timer, XCircle } from 'lucide-react';
import RemoteAccessPanel from './RemoteAccessPanel';

function Entry({ icon: Icon, title, description, action, onClick, disabled = false }: {
  icon: typeof GitPullRequest;
  title: string;
  description: string;
  action: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return <article className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
    <div className="flex min-w-[240px] flex-1 items-start gap-3">
      <Icon size={17} className="mt-0.5 shrink-0 text-fg-3" />
      <div className="grid gap-1">
        <h3 className="m-0 text-[13.5px] font-medium text-heading">{title}</h3>
        <p className="m-0 text-[12px] leading-relaxed text-fg-3">{description}</p>
      </div>
    </div>
    <button type="button" disabled={disabled} onClick={onClick}
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-fg-2 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50">
      {disabled ? <XCircle size={14} /> : <ExternalLink size={14} />}{action}
    </button>
  </article>;
}

export default function SettingsIntegrationsPanel({ onOpenCode, onOpenChannels, onOpenAutomation, apiBaseUrl, onToast }: {
  apiBaseUrl: string;
  onToast: (text: string) => void;
  onOpenCode: () => void;
  onOpenChannels: () => void;
  onOpenAutomation: () => void;
}) {
  return <section className="grid max-w-[820px] gap-3 text-fg-2" aria-label="任务与外部集成入口">
    <p className="m-0 mb-1 text-[12.5px] leading-relaxed text-fg-3">
      这里汇总 Atlas 当前可用的入口。GitHub PR 使用本机工作区和已安装的 gh CLI；Slack 作为本机 Gateway 渠道运行；自动化由本机调度器执行。
    </p>
    <RemoteAccessPanel apiBaseUrl={apiBaseUrl} onToast={onToast} />
    <Entry icon={GitPullRequest} title="GitHub Pull Request" description="查看工作区变更、创建 PR 并在 Atlas Code 页面跟进。需要本机 git/gh 登录状态。" action="打开 Code" onClick={onOpenCode} />
    <Entry icon={MessageCircle} title="Slack Gateway" description="配置 Slack Socket Mode 机器人凭据，连接本机 Atlas Gateway。可用性取决于可选依赖和凭据。" action="配置渠道" onClick={onOpenChannels} />
    <Entry icon={Timer} title="本机计划任务" description="创建定时、间隔、Webhook 或事件触发自动化；任务在这台机器的 Atlas 实例运行。" action="打开自动化" onClick={onOpenAutomation} />
    <Entry icon={XCircle} title="云端托管任务" description="当前版本没有 Atlas 云执行服务；请使用本机 Automations。Linear issue 集成可在本页下方配置。" action="当前不可用" disabled />
  </section>;
}
