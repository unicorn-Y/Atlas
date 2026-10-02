import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(frontendDir, '..');
const venvPython = path.join(repoRoot, 'core', '.venv', 'Scripts', 'python.exe');
const outputDir = path.join(frontendDir, 'backend-release');
const workDir = path.join(frontendDir, 'backend-build');

function run(command, args) {
  const result = spawnSync(command, args, { cwd: repoRoot, stdio: 'inherit', windowsHide: true });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}

if (process.platform !== 'win32') {
  throw new Error('The Windows backend bundle must be built on Windows.');
}

process.env.LITELLM_LOCAL_MODEL_COST_MAP ??= 'true';

if (!fs.existsSync(venvPython)) run('py', ['-3', '-m', 'venv', path.join(repoRoot, 'core', '.venv')]);
run(venvPython, ['-m', 'pip', 'install', '-e', 'core[release]']);

for (const target of [outputDir, workDir]) {
  const resolved = path.resolve(target);
  if (!resolved.startsWith(`${frontendDir}${path.sep}`)) throw new Error(`Unsafe build path: ${resolved}`);
  fs.rmSync(resolved, { recursive: true, force: true });
}

run(venvPython, [
  '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
  '--name', 'atlas_backend',
  '--distpath', outputDir,
  '--workpath', workDir,
  '--specpath', workDir,
  '--collect-all', 'atlas',
  '--collect-all', 'litellm',
  '--collect-all', 'langchain_core',
  '--collect-all', 'uvicorn',
  '--collect-all', 'fastapi',
  '--collect-all', 'apscheduler',
  '--collect-all', 'cua_driver', '--copy-metadata', 'cua-driver',
  '--collect-all', 'pywinauto', '--copy-metadata', 'pywinauto',
  '--collect-all', 'browser_use', '--copy-metadata', 'browser-use',
  '--collect-all', 'dbos', '--copy-metadata', 'dbos',
  '--collect-all', 'claude_agent_sdk', '--copy-metadata', 'claude-agent-sdk',
  '--collect-all', 'acp', '--copy-metadata', 'agent-client-protocol',
  '--hidden-import', 'tiktoken_ext.openai_public',
  path.join(repoRoot, 'core', 'atlas', 'desktop_entry.py'),
]);
