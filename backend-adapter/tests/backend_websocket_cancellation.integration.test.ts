import { afterEach, describe, expect, it, vi } from 'vitest';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import { createServer as createTcpServer } from 'node:net';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { delimiter, join, resolve } from 'node:path';
import { BackendAdapter } from '../src/client';
import { normalizeRuntimeEvent } from '../../frontend/src/renderer/services/runtimeEvents';
import { useAtlasStore } from '../../frontend/src/renderer/store/useAtlasStore';
import { projectMessageDeltaText, TimelineProjection } from '../../frontend/src/renderer/components/timelineProjection';

afterEach(() => vi.unstubAllGlobals());

async function freePort(): Promise<number> {
  const server = createTcpServer();
  await new Promise<void>((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolveListen());
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('could not resolve temporary loopback port');
  const port = address.port;
  await new Promise<void>((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()));
  return port;
}

function startStalledProvider(): { server: Server; baseUrl: string; requests: () => number } {
  let requestCount = 0;
  const server = createServer((request, response) => {
    if (!request.url?.endsWith('/chat/completions')) {
      response.writeHead(404).end();
      return;
    }
    requestCount += 1;
    response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
    response.write('data: {"id":"fixture","object":"chat.completion.chunk","created":0,"model":"fake-model","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n');
    response.write('data: {"id":"fixture","object":"chat.completion.chunk","created":0,"model":"fake-model","choices":[{"index":0,"delta":{"content":"OLD"},"finish_reason":null}]}\n\n');
  });
  return { server, baseUrl: '', requests: () => requestCount };
}

function makeIsolatedBackendRoot(root: string, providerUrl: string): { env: NodeJS.ProcessEnv; coreRoot: string } {
  const repoRoot = resolve(process.cwd(), '..');
  const coreRoot = join(repoRoot, 'core');
  const data = join(root, 'atlas');
  const dirs = [
    join(data, 'config'), join(data, 'data'), join(data, 'engine'),
    ...['home', 'userprofile', 'appdata', 'localappdata', 'temp', 'tmp', 'tmpdir'].map((name) => join(root, name)),
    join(root, 'server-cwd'), join(root, 'workspace'),
  ];
  for (const directory of dirs) mkdirSync(directory, { recursive: true });
  writeFileSync(join(data, 'data', 'user-settings.json'), JSON.stringify({ fallback_chain: [] }));
  writeFileSync(join(data, 'config', 'atlas.toml'), [
    '[models]', 'default="fake-model"', 'fallback=[]',
    '[models.gateway]', `base_url="${providerUrl}"`, 'api_key="sk-local-fixture"',
    '[[models.custom]]', 'id="fake-model"', 'name="Fake fixture"', 'provider="openai"',
    `base_url="${providerUrl}"`, 'litellm_model="openai/fake-model"', 'max_output_tokens=256',
    '[agent]', 'engine="hermes"', 'verify_before_stop=false',
    '[tools]', 'auto_start=[]', '[tools.servers]', '[scheduler]', 'enabled=false', '',
  ].join('\n'));
  writeFileSync(join(data, 'engine', 'config.yaml'), [
    'model:', '  provider: custom', `  base_url: ${providerUrl}`, '  default: fake-model',
    '  context_length: 128000', 'agent:', '  api_max_retries: 1', '  auto_recovery_cycles: 0',
    'telemetry:', '  shared_metrics:', '    enabled: false',
    'auxiliary:', '  title_generation:', '    model_upgrade_enabled: false', 'models:', '  fallback: []', '',
  ].join('\n'));

  const env: NodeJS.ProcessEnv = { ...process.env };
  for (const key of Object.keys(env)) {
    const upper = key.toUpperCase();
    if (['API_KEY', 'ACCESS_KEY', 'SECRET', 'TOKEN', 'PASSWORD', 'PASSWD', 'CREDENTIAL'].some((part) => upper.includes(part))
      || upper.startsWith('HERMES_SESSION_') || upper.endsWith('_PROXY')) delete env[key];
  }
  Object.assign(env, {
    ATLAS_DATA_DIR: data,
    HERMES_HOME: join(data, 'engine'),
    HERMES_TEST_MODE: '1',
    ATLAS_SCHEDULER_ENABLED: 'false',
    ATLAS_API_BASE: providerUrl,
    OPENAI_API_BASE: providerUrl,
    OPENAI_BASE_URL: providerUrl,
    OPENAI_API_KEY: 'sk-local-fixture',
    PYTHONPATH: [coreRoot, env.PYTHONPATH].filter(Boolean).join(delimiter),
    HOME: join(root, 'home'), USERPROFILE: join(root, 'userprofile'),
    APPDATA: join(root, 'appdata'), LOCALAPPDATA: join(root, 'localappdata'),
    TEMP: join(root, 'temp'), TMP: join(root, 'tmp'), TMPDIR: join(root, 'tmpdir'),
    HTTP_PROXY: 'http://127.0.0.1:1', HTTPS_PROXY: 'http://127.0.0.1:1',
    ALL_PROXY: 'http://127.0.0.1:1', NO_PROXY: '127.0.0.1,localhost',
    http_proxy: 'http://127.0.0.1:1', https_proxy: 'http://127.0.0.1:1',
    all_proxy: 'http://127.0.0.1:1', no_proxy: '127.0.0.1,localhost',
  });
  return { env, coreRoot };
}

describe('isolated backend WebSocket → adapter → renderer cancellation', () => {
  it('preserves OLD rollback ordering across the actual server, adapter and renderer store', async () => {
    const root = mkdtempSync(join(tmpdir(), 'atlas-ws-adapter-cancel-'));
    const provider = startStalledProvider();
    const providerPort = await freePort();
    const providerUrl = `http://127.0.0.1:${providerPort}/v1`;
    const backendPort = await freePort();
    const backendUrl = `http://127.0.0.1:${backendPort}`;
    const { env, coreRoot } = makeIsolatedBackendRoot(root, providerUrl);
    let backendProcess: ChildProcessWithoutNullStreams | undefined;
    const serverOutput: string[] = [];
    let providerListening = false;

    try {
      await new Promise<void>((resolveListen, reject) => {
        provider.server.once('error', reject);
        provider.server.listen(providerPort, '127.0.0.1', () => { providerListening = true; resolveListen(); });
      });

      backendProcess = spawn(
        process.env.ATLAS_TEST_PYTHON || 'python',
        ['-m', 'uvicorn', 'atlas.server:app', '--host', '127.0.0.1', '--port', String(backendPort), '--log-level', 'warning'],
        { cwd: join(root, 'server-cwd'), env, stdio: 'pipe', windowsHide: true },
      );
      const collect = (chunk: Buffer) => {
        serverOutput.push(chunk.toString('utf8'));
        if (serverOutput.length > 30) serverOutput.shift();
      };
      backendProcess.stdout.on('data', collect);
      backendProcess.stderr.on('data', collect);
      const readyDeadline = Date.now() + 45_000;
      let ready = false;
      while (Date.now() < readyDeadline) {
        if (backendProcess.exitCode !== null) break;
        try {
          const response = await fetch(`${backendUrl}/api/health`);
          if (response.ok) { ready = true; break; }
        } catch { /* poll the isolated loopback startup */ }
        await new Promise((resolveDelay) => setTimeout(resolveDelay, 100));
      }
      expect(ready, serverOutput.join('').slice(-3000)).toBe(true);

      vi.stubGlobal('window', new EventTarget());
      vi.stubGlobal('localStorage', {
        values: new Map<string, string>(),
        getItem(key: string) { return this.values.get(key) ?? null; },
        setItem(key: string, value: string) { this.values.set(key, value); },
        removeItem(key: string) { this.values.delete(key); },
      });
      const adapter = new BackendAdapter({ baseUrl: backendUrl });
      await expect(adapter.initialize(10_000)).resolves.toBe('backend');
      const conversation = await adapter.createConversation();
      const runId = 'run-cross-runtime-cancel';
      const timestamp = new Date().toISOString();
      useAtlasStore.setState({ runs: [{
        id: runId, conversationId: conversation.id, title: 'server cancellation', status: 'running', phase: 'execution',
        startedAt: timestamp, updatedAt: timestamp, lastEventSequence: 0, events: [],
      }], activeRunId: runId, activeConversationId: conversation.id, busy: true });
      const seenEvents: string[] = [];
      let cancelSent = false;
      const running = adapter.startRun({
        type: 'run.start', run_id: runId, content: 'cancel after OLD reaches the desktop adapter',
        conversation_id: conversation.id, model: 'fake-model', workspace: join(root, 'workspace'),
      }, (envelope) => {
        seenEvents.push(`${envelope.sequence}:${envelope.event}`);
        const normalized = normalizeRuntimeEvent(envelope);
        if (normalized) useAtlasStore.getState().appendEvent(normalized);
        if (envelope.event === 'rules.trust_required' && !cancelSent) {
          adapter.trustRules(runId, String(envelope.data?.event_id || envelope.data?.trust_id || ''), true);
        }
        if (envelope.event === 'message.delta' && String(envelope.data?.content || '').includes('OLD') && !cancelSent) {
          cancelSent = true;
          adapter.cancelRun(runId);
        }
      });
      await expect(running).resolves.toBeUndefined();

      const run = useAtlasStore.getState().getRun(runId)!;
      const oldIndex = run.events.findIndex((event) => event.type === 'message.delta' && String(event.data.content).includes('OLD'));
      const rollbackIndex = run.events.findIndex((event) => event.type === 'message.rollback');
      const cancelledIndex = run.events.findIndex((event) => event.type === 'run.cancelled');
      expect(cancelSent).toBe(true);
      expect(run.status).toBe('cancelled');
      expect(oldIndex).toBeGreaterThanOrEqual(0);
      expect(rollbackIndex).toBeGreaterThan(oldIndex);
      expect(cancelledIndex).toBeGreaterThan(rollbackIndex);
      expect(run.events[rollbackIndex].data.attempt_id).toBe(run.events[oldIndex].data.attempt_id);
      expect(projectMessageDeltaText(run.events)).toBe('');
      expect(new TimelineProjection().project(run.events).some(
        (item) => item.kind === 'reply' && item.content.includes('OLD'),
      )).toBe(false);
      expect(provider.requests()).toBe(1);
      expect(seenEvents).toContain(`${run.events[rollbackIndex].sequence}:message.rollback`);

    } finally {
      if (backendProcess && backendProcess.exitCode === null) {
        backendProcess.kill();
        await Promise.race([
          new Promise<void>((resolveExit) => backendProcess!.once('exit', () => resolveExit())),
          new Promise<void>((resolveTimeout) => setTimeout(resolveTimeout, 5000)),
        ]);
      }
      if (providerListening) await new Promise<void>((resolveClose) => provider.server.close(() => resolveClose()));
      rmSync(root, { recursive: true, force: true });
    }
  }, 60_000);
});
