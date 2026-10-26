import RemoteAccessPanel from './RemoteAccessPanel';

export default function MobileEntryPanel({ apiBaseUrl, onToast, onOpenTelegram }: {
  apiBaseUrl: string;
  onToast: (message: string) => void;
  onOpenTelegram: () => void;
}) {
  return <section className="grid max-w-[900px] gap-4" aria-label="Atlas 手机入口">
    <div className="rounded-xl border border-line p-4">
      <h3 className="m-0 text-[14px] font-medium text-heading">Atlas 手机入口</h3>
      <p className="mb-0 mt-2 text-[12.5px] leading-relaxed text-fg-3">目前没有已发布的 Atlas 原生 Android/iOS 应用，因此这里不提供 App 下载地址、签名信息或虚构的安装二维码。你可以用手机浏览器访问 Atlas 移动 Web，或通过 Telegram 给本机 Atlas 投递任务。</p>
    </div>
    <RemoteAccessPanel apiBaseUrl={apiBaseUrl} onToast={onToast} />
    <article className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
      <div><h3 className="m-0 text-[13.5px] font-medium text-heading">Telegram 手机渠道</h3><p className="m-0 mt-1 text-[12px] text-fg-3">通过你自己的 Telegram Bot 从外网远程投递任务并接收审批/完成通知。</p></div>
      <button type="button" onClick={onOpenTelegram} className="rounded-lg border border-line px-3 py-2 text-[12px] hover:bg-hover">配置 Telegram</button>
    </article>
  </section>;
}
