export type BrowserFailureKind = 'dns' | 'refused' | 'proxy' | 'tls' | 'firewall' | 'timeout' | 'unknown';

const CODES: Record<number, BrowserFailureKind> = {
  [-105]: 'dns', [-137]: 'dns', [-106]: 'dns',
  [-102]: 'refused', [-101]: 'refused',
  [-130]: 'proxy', [-111]: 'proxy', [-136]: 'proxy',
  [-200]: 'tls', [-201]: 'tls', [-202]: 'tls', [-107]: 'tls', [-108]: 'tls',
  [-138]: 'firewall', [-117]: 'firewall',
  [-7]: 'timeout', [-118]: 'timeout',
};

export function classifyBrowserFailure(code: number, description = ''): BrowserFailureKind {
  const kind = CODES[code];
  if (kind) return kind;
  const text = description.toLowerCase();
  if (/name_not_resolved|dns|host not found/.test(text)) return 'dns';
  if (/proxy|tunnel/.test(text)) return 'proxy';
  if (/cert|certificate|ssl|tls/.test(text)) return 'tls';
  if (/firewall|network_access_denied|blocked/.test(text)) return 'firewall';
  if (/timed out|timeout/.test(text)) return 'timeout';
  if (/connection refused|connection reset/.test(text)) return 'refused';
  return 'unknown';
}

export const BROWSER_FAILURE_GUIDE: Record<BrowserFailureKind, { title: string; checks: string[] }> = {
  dns: { title: 'DNS / 域名解析失败', checks: ['检查网址拼写和域名是否有效。', '尝试切换系统 DNS 或刷新 DNS 缓存。', '确认 VPN、公司网络或 hosts 规则没有拦截该域名。'] },
  refused: { title: '目标拒绝或重置了连接', checks: ['确认网站服务正在运行，地址和端口正确。', '本机开发服务请确认绑定了可访问的端口。', '检查 VPN、路由器和安全软件的连接规则。'] },
  proxy: { title: '代理连接失败', checks: ['检查 Atlas 浏览器代理地址和端口。', '确认代理程序正在运行并允许本机连接。', '不需要代理时清空 Atlas 的代理设置后重试。'] },
  tls: { title: 'TLS / 证书握手失败', checks: ['检查系统日期和时间。', '确认站点证书有效且域名匹配。', '公司网络若使用 HTTPS 检查代理，请确认其根证书已受系统信任。'] },
  firewall: { title: '网络访问可能被防火墙拦截', checks: ['检查系统防火墙或安全软件的出站规则。', '确认网络策略允许访问该域名和端口。', '公司网络请检查 VPN 或代理的访问策略。'] },
  timeout: { title: '连接超时', checks: ['检查网络连接和目标服务状态。', '尝试打开其他站点以区分本地网络与目标站点问题。', '确认代理或 VPN 没有造成路由延迟。'] },
  unknown: { title: '浏览器无法加载页面', checks: ['检查网络连接、网址和代理设置。', '重试；如果仍失败，请按原始错误码排查 Chromium 网络错误。'] },
};
