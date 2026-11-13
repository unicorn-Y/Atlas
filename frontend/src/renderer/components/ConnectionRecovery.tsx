export async function recoverBackendConnection(options: {
  retry: () => void | Promise<void>;
  restart?: () => void | Promise<void>;
  confirmRestart: () => boolean;
}): Promise<void> {
  if (!options.restart) {
    await options.retry();
    return;
  }
  if (options.confirmRestart()) await options.restart();
}

export function ConnectionRecovery({ onRetry, onRestart }: {
  onRetry: () => void | Promise<void>;
  onRestart?: () => void | Promise<void>;
}) {
  return <div role="status" className="inline-flex items-center gap-2 text-[12px] text-danger">
    <i className="size-1.5 rounded-full bg-danger" />
    <span>后端没有连接</span>
    <button type="button" className="rounded px-2 py-1 text-fg underline underline-offset-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
      onClick={() => void recoverBackendConnection({
        retry: onRetry,
        restart: onRestart,
        confirmRestart: () => window.confirm('重启 Atlas 后端以恢复连接？当前正在运行的任务可能会中断。'),
      })}>
      {onRestart ? '重启后端' : '重试连接'}
    </button>
  </div>;
}
