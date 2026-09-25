import { mockConversations, mockModels, mockTools, streamMockRun } from './mock';
import type { ApprovalResponse, ConversationMessage, ConversationSummary, Fact, ModelListResponse, ResumeRequest, RunStartRequest, RuntimeEventEnvelope, RuntimeStreamEvent, ToolListResponse } from './types';

export interface BackendAdapterOptions {
  baseUrl: string;
}

export class BackendAdapter {
  readonly baseUrl: string;
  private live = false;
  private mockCancelled = new Set<string>();
  private mockControls = new Map<string, (event: string, data?: Record<string, unknown>) => void>();
  private runSockets = new Map<string, WebSocket>();
  private approvalResolvers = new Map<string, { runId: string; resolve: (choice: 'allow' | 'deny') => void }>();
  private runtimeProtocol: 'v1' | '1.1' | '1.2' | null = null;

  constructor(options: BackendAdapterOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
  }

  get mode(): 'mock' | 'backend' { return this.live ? 'backend' : 'mock'; }

  async initialize(timeoutMs = 1200): Promise<'mock' | 'backend'> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${this.baseUrl}/api/health`, { signal: controller.signal });
      this.live = response.ok;
    } catch {
      this.live = false;
    } finally {
      clearTimeout(timeout);
    }
    return this.mode;
  }

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({})) as { detail?: string };
      throw new Error(body.detail ?? `Backend request failed (${response.status})`);
    }
    return response.json() as Promise<T>;
  }

  private async supportsRuntimeProtocol(): Promise<boolean> {
    if (this.runtimeProtocol === null) {
      try {
        const response = await fetch(`${this.baseUrl}/api/runtime/protocol`);
        const body = response.ok ? await response.json() as { version?: string } : {};
        this.runtimeProtocol = body.version === '1.2' ? '1.2' : body.version === '1.1' ? '1.1' : 'v1';
      } catch {
        this.runtimeProtocol = 'v1';
      }
    }
    return this.runtimeProtocol === '1.2';
  }

  async getModels(): Promise<ModelListResponse> { return this.live ? this.request('/api/models') : mockModels; }
  async selectModel(model: string): Promise<void> {
    if (this.live) await this.request('/api/models/select', { method: 'POST', body: JSON.stringify({ model }) });
    else mockModels.current = model;
  }
  async getConversations(): Promise<ConversationSummary[]> { return this.live ? this.request('/api/conversations') : mockConversations; }
  async getMessages(id: string): Promise<ConversationMessage[]> { return this.live ? this.request(`/api/conversations/${encodeURIComponent(id)}/messages`) : []; }
  async renameConversation(id: string, title: string): Promise<void> {
    if (this.live) await this.request(`/api/conversations/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify({ title }) });
  }
  async deleteConversation(id: string): Promise<void> {
    if (this.live) await this.request(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' });
  }
  async getTools(): Promise<ToolListResponse> { return this.live ? this.request('/api/tools') : mockTools; }
  async getFacts(): Promise<Fact[]> { return this.live ? this.request('/api/facts') : []; }
  async saveFact(fact: Pick<Fact, 'key' | 'value' | 'category'>): Promise<void> {
    if (this.live) await this.request('/api/facts', { method: 'POST', body: JSON.stringify(fact) });
  }
  async deleteFact(key: string): Promise<void> {
    if (this.live) await this.request(`/api/facts/${encodeURIComponent(key)}`, { method: 'DELETE' });
  }
  async search(query: string): Promise<unknown[]> {
    return this.live ? this.request(`/api/search?q=${encodeURIComponent(query)}`) : [];
  }

  async startRun(request: RunStartRequest, onEvent: (event: RuntimeStreamEvent) => void, shouldPause: () => boolean = () => false, maxReconnectAttempts = 5): Promise<void> {
    if (!this.live) {
      this.mockCancelled.delete(request.run_id);
      try {
        await streamMockRun(request, onEvent, shouldPause, () => this.mockCancelled.has(request.run_id), (eventId) => new Promise((resolve) => this.approvalResolvers.set(eventId, { runId: request.run_id, resolve })), (send) => this.mockControls.set(request.run_id, send));
      } finally {
        this.mockControls.delete(request.run_id);
        this.mockCancelled.delete(request.run_id);
        for (const [eventId, pending] of this.approvalResolvers) if (pending.runId === request.run_id) this.approvalResolvers.delete(eventId);
      }
      return;
    }

    const supportsReplay = await this.supportsRuntimeProtocol();
    if (!supportsReplay) throw new Error('Backend Agent Runtime 1.2 is required for event runs and approvals');
    const cursorKey = `atlas.runtime.cursor.${request.run_id}`;
    let lastSequence = Number(localStorage.getItem(cursorKey) ?? 0) || 0;
    let retries = 0;
    let terminal = false;
    const connect = (resume: boolean): Promise<void> => new Promise((resolve, reject) => {
      const path = '/ws/chat';
      const socket = new WebSocket(`${this.baseUrl.replace(/^http/, 'ws')}${path}`);
      this.runSockets.set(request.run_id, socket);
      let opened = false;
      let settled = false;
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        if (this.runSockets.get(request.run_id) === socket) this.runSockets.delete(request.run_id);
        if (error) reject(error); else resolve();
      };
      socket.addEventListener('open', () => {
        opened = true;
        const wireRequest: RunStartRequest | ResumeRequest = resume
          ? { type: 'resume', run_id: request.run_id, after_sequence: lastSequence }
          : request;
        socket.send(JSON.stringify(wireRequest));
      }, { once: true });
      socket.addEventListener('message', (message) => {
        let event: RuntimeStreamEvent;
        try { event = JSON.parse(String(message.data)) as RuntimeStreamEvent; } catch { return; }
        if ('type' in event && event.type === 'agent_event') {
          const runtimeEvent = event as RuntimeEventEnvelope;
          if (runtimeEvent.run_id !== request.run_id || !Number.isInteger(runtimeEvent.sequence) || runtimeEvent.sequence <= lastSequence) return;
          lastSequence = runtimeEvent.sequence;
          localStorage.setItem(cursorKey, String(lastSequence));
          onEvent(runtimeEvent);
          if (['run.completed', 'run.failed', 'run.cancelled'].includes(runtimeEvent.event)) {
            terminal = true; socket.close(1000, 'Run complete'); finish();
          }
          return;
        }
        return;
      });
      socket.addEventListener('error', () => {
        if (!opened) finish(new Error('WebSocket connection failed'));
      });
      socket.addEventListener('close', () => {
        if (this.runSockets.get(request.run_id) === socket) this.runSockets.delete(request.run_id);
        if (settled) return;
        if (terminal || this.mockCancelled.has(request.run_id)) { finish(); return; }
        if (!opened) { finish(new Error('WebSocket closed before the run started')); return; }
        if (!supportsReplay) { finish(new Error('Connection lost; this backend does not support run event replay')); return; }
        if (retries >= maxReconnectAttempts) { finish(new Error('Run disconnected; reconnect limit reached')); return; }
        retries += 1;
        window.setTimeout(() => { void connect(true).then(() => finish(), (error: Error) => {
          if (retries < maxReconnectAttempts && !terminal && !this.mockCancelled.has(request.run_id)) {
            window.setTimeout(() => { void connect(true).then(() => finish(), finish); }, Math.min(1000 * 2 ** (retries - 1), 8000));
          } else finish(error);
        }); }, Math.min(1000 * 2 ** (retries - 1), 8000));
      }, { once: true });
    });
    try { await connect(lastSequence > 0); }
    finally {
      if (terminal) localStorage.removeItem(cursorKey);
      this.mockControls.delete(request.run_id);
    }
  }

  respondToApproval(runId: string, response: ApprovalResponse): void {
    const pending = this.approvalResolvers.get(response.event_id);
    if (pending) {
      this.approvalResolvers.delete(response.event_id);
      pending.resolve(response.choice);
      return;
    }
    const socket = this.runSockets.get(runId);
    if (!socket || socket.readyState !== WebSocket.OPEN) throw new Error('Agent Runtime socket is not connected');
    socket.send(JSON.stringify(response));
  }

  cancelRun(runId: string): void {
    this.mockCancelled.add(runId);
    if (!this.live) {
      for (const [eventId, pending] of this.approvalResolvers) {
        if (pending.runId === runId) { this.approvalResolvers.delete(eventId); pending.resolve('deny'); }
      }
      return;
    }
    const socket = this.runSockets.get(runId);
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'run.cancel', run_id: runId }));
    }
  }

  controlRun(runId: string, type: 'run.pause' | 'run.resume'): void {
    if (!this.live) {
      this.mockControls.get(runId)?.(type === 'run.pause' ? 'run.paused' : 'run.resumed');
      return;
    }
    if (this.runtimeProtocol !== '1.2') throw new Error('This backend does not support Agent Run controls');
    const socket = this.runSockets.get(runId);
    if (socket?.readyState !== WebSocket.OPEN) throw new Error('Agent Runtime socket is not connected');
    socket.send(JSON.stringify({ type, run_id: runId }));
  }
}
