import { createHash } from 'node:crypto';
import { createWriteStream, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import { spawn } from 'node:child_process';
import path from 'node:path';

export interface ReleaseStatus { supported: boolean; available: boolean; current: string; latest?: string; notes?: string; assetName?: string; error?: string; skipped?: boolean }
const semver = (raw: string) => raw.replace(/^v/, '').split(/[+-]/, 1)[0].split('.').map((part) => Number(part));
export function compareSemver(a: string, b: string): number {
  const left = semver(a); const right = semver(b);
  for (let i = 0; i < 3; i += 1) { const diff = (left[i] ?? 0) - (right[i] ?? 0); if (diff) return diff > 0 ? 1 : -1; }
  return 0;
}
function releasePrefsPath(userData: string) { return path.join(userData, 'release-update-prefs.json'); }
function prefs(userData: string): { skipped?: string; remindAfter?: number } {
  try { return JSON.parse(readFileSync(releasePrefsPath(userData), 'utf8')) as { skipped?: string; remindAfter?: number }; } catch { return {}; }
}
export function setReleasePreference(userData: string, update: { skipped?: string; remindAfter?: number }) {
  const current = prefs(userData); writeFileSync(releasePrefsPath(userData), JSON.stringify({ ...current, ...update }, null, 2), 'utf8');
}
const jsonFetch = async (url: string) => {
  const response = await fetch(url, { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'Atlas-Desktop-Updater' } });
  if (!response.ok) throw new Error(`更新服务返回 HTTP ${response.status}`);
  return response.json() as Promise<Record<string, any>>;
};
export async function checkReleaseUpdate(source: string, current: string, userData: string): Promise<ReleaseStatus> {
  if (!source.trim()) return { supported: false, available: false, current, error: '请在更新设置中配置 GitHub Releases 地址。' };
  try {
    const release = await jsonFetch(source.trim());
    const latest = String(release.tag_name ?? release.name ?? '').trim();
    if (!/^v?\d+\.\d+\.\d+/.test(latest)) throw new Error('Release tag 不是语义化版本号。');
    const asset = (release.assets as Array<{ name: string; browser_download_url: string }> | undefined)?.find((item) => /setup\.exe$/i.test(item.name));
    const p = prefs(userData);
    const skipped = p.skipped === latest;
    return { supported: true, current, latest, notes: String(release.body ?? ''), assetName: asset?.name,
      available: compareSemver(latest, current) > 0 && !skipped && !(p.remindAfter && Date.now() < p.remindAfter), skipped };
  } catch (error) { return { supported: true, available: false, current, error: error instanceof Error ? error.message : String(error) }; }
}
export async function downloadVerifiedInstaller(source: string, expectedVersion: string, userData: string, progress: (percent: number) => void): Promise<string> {
  const release = await jsonFetch(source.trim());
  const tag = String(release.tag_name ?? release.name ?? '');
  if (compareSemver(tag, expectedVersion) !== 0) throw new Error('Release 版本已变化，请重新检查后重试。');
  const assets = release.assets as Array<{ name: string; browser_download_url: string }> | undefined;
  const installer = assets?.find((item) => /setup\.exe$/i.test(item.name));
  if (!installer) throw new Error('Release 中没有 Windows Setup.exe 安装包。');
  let expected = '';
  const sidecar = assets?.find((item) => item.name.toLowerCase() === `${installer.name.toLowerCase()}.sha256` || item.name.toLowerCase() === `${installer.name.toLowerCase()}.sha256.txt`);
  if (sidecar) {
    const response = await fetch(sidecar.browser_download_url);
    if (!response.ok) throw new Error(`SHA256 文件读取失败：HTTP ${response.status}`);
    expected = (await response.text()).match(/[a-f\d]{64}/i)?.[0] ?? '';
  }
  if (!expected) {
    const manifestAsset = assets?.find((item) => item.name === 'release-manifest.json');
    if (manifestAsset) {
      const manifest = await jsonFetch(manifestAsset.browser_download_url);
      const record = manifest.installer as Record<string, unknown> | undefined;
      if (record?.file === installer.name) expected = String(record.sha256 ?? '');
    }
  }
  if (!expected) expected = String(release.body ?? '').match(new RegExp(`${installer.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}[^\\n\\r]*?([a-f\\d]{64})`, 'i'))?.[1] ?? '';
  if (!/^[a-f\d]{64}$/i.test(expected)) throw new Error('Release 没有提供安装包 SHA256，已拒绝安装。');
  const response = await fetch(installer.browser_download_url);
  if (!response.ok || !response.body) throw new Error(`安装包下载失败：HTTP ${response.status}`);
  const targetDir = path.join(userData, 'updates'); mkdirSync(targetDir, { recursive: true });
  const target = path.join(targetDir, installer.name);
  const total = Number(response.headers.get('content-length') ?? 0); let received = 0;
  const stream = Readable.fromWeb(response.body as import('node:stream/web').ReadableStream);
  stream.on('data', (chunk: Buffer) => { received += chunk.length; if (total) progress(Math.min(99, Math.round(received * 100 / total))); });
  await pipeline(stream, createWriteStream(target));
  const actual = createHash('sha256').update(readFileSync(target)).digest('hex');
  if (actual.toLowerCase() !== expected.toLowerCase()) throw new Error(`SHA256 不匹配：期望 ${expected}，实际 ${actual}；安装已拒绝。`);
  if (process.platform === 'win32') {
    const quote = target.replace(/'/g, "''");
    const verifier = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `(Get-AuthenticodeSignature -LiteralPath '${quote}').Status`], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    const output: Buffer[] = []; verifier.stdout.on('data', (chunk) => output.push(Buffer.from(chunk)));
    const error: Buffer[] = []; verifier.stderr.on('data', (chunk) => error.push(Buffer.from(chunk)));
    const status = await new Promise<string>((resolve, reject) => { verifier.once('error', reject); verifier.once('close', (code) => code === 0 ? resolve(Buffer.concat(output).toString('utf8').trim()) : reject(new Error(Buffer.concat(error).toString('utf8') || 'Authenticode 校验失败'))); });
    if (status !== 'Valid' && status !== 'NotSigned') throw new Error(`Windows Authenticode 签名无效：${status}`);
  }
  progress(100); return target;
}
export function launchVerifiedInstaller(installerPath: string, appExecutable: string, onExit: () => void, onError: (error: Error) => void): void {
  if (!existsSync(installerPath)) throw new Error('已验证的安装包不存在，请重新下载。');
  if (process.platform !== 'win32') throw new Error('发布版重启安装目前只支持 Windows 安装包。');
  const quoted = installerPath.replace(/'/g, "''"); const executable = appExecutable.replace(/'/g, "''");
  const child = spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', `Start-Sleep -Seconds 2; $p=Start-Process -FilePath '${quoted}' -ArgumentList '/S' -PassThru -Wait; if($p.ExitCode -eq 0 -and (Test-Path '${executable}')){Start-Process -FilePath '${executable}'}; exit $p.ExitCode`], { windowsHide: true, stdio: 'ignore', detached: true });
  child.once('error', onError); child.once('spawn', () => { child.unref(); onExit(); });
}
