import * as vscode from 'vscode';
import * as crypto from 'node:crypto';
import * as fs from 'node:fs/promises';
import * as os from 'node:os';
import * as path from 'node:path';
import { WebSocketServer, WebSocket } from 'ws';

type Request = { id: string; method: string; params?: Record<string, unknown> };
const lockPath = path.join(os.homedir(), '.atlas', 'ide', 'vscode.json');

function editorContext() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return { file: null, selection: null, workspace: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? null };
  const selection = editor.selection;
  return {
    file: editor.document.uri.fsPath,
    language: editor.document.languageId,
    selection: selection.isEmpty ? null : {
      text: editor.document.getText(selection),
      startLine: selection.start.line + 1, endLine: selection.end.line + 1,
      startColumn: selection.start.character + 1, endColumn: selection.end.character + 1,
    },
    workspace: vscode.workspace.getWorkspaceFolder(editor.document.uri)?.uri.fsPath ?? null,
  };
}

async function handle(req: Request): Promise<unknown> {
  switch (req.method) {
    case 'context': return editorContext();
    case 'diagnostics': {
      const errors = [vscode.DiagnosticSeverity.Error, vscode.DiagnosticSeverity.Warning];
      return vscode.languages.getDiagnostics().flatMap(([uri, diagnostics]) => diagnostics
        .filter(d => errors.includes(d.severity)).map(d => ({
          file: uri.fsPath, severity: d.severity === vscode.DiagnosticSeverity.Error ? 'error' : 'warning',
          message: d.message, code: d.code, source: d.source,
          startLine: d.range.start.line + 1, endLine: d.range.end.line + 1,
        })));
    }
    case 'open_diff': {
      const p = req.params ?? {};
      const file = String(p.file ?? 'Atlas change');
      const original = vscode.Uri.parse(`untitled:${file}.before`);
      const modified = vscode.Uri.parse(`untitled:${file}.after`);
      const beforeDoc = await vscode.workspace.openTextDocument(original);
      const afterDoc = await vscode.workspace.openTextDocument(modified);
      const edit = new vscode.WorkspaceEdit();
      edit.insert(original, new vscode.Position(0, 0), String(p.before ?? ''));
      edit.insert(modified, new vscode.Position(0, 0), String(p.after ?? ''));
      await vscode.workspace.applyEdit(edit);
      await vscode.commands.executeCommand('vscode.diff', beforeDoc.uri, afterDoc.uri, `Atlas: ${file}`);
      return { opened: true };
    }
    default: throw new Error(`Unsupported Atlas IDE method: ${req.method}`);
  }
}

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const token = crypto.randomBytes(32).toString('hex');
  const server = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise<void>((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Atlas IDE bridge did not bind a TCP port');
  server.on('connection', (socket: WebSocket, request) => {
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    if (url.searchParams.get('token') !== token) { socket.close(1008, 'unauthorized'); return; }
    socket.on('message', async raw => {
      let req: Request;
      try {
        req = JSON.parse(raw.toString()) as Request;
        const result = await handle(req);
        socket.send(JSON.stringify({ id: req.id, result }));
      } catch (error) {
        socket.send(JSON.stringify({ id: '', error: error instanceof Error ? error.message : String(error) }));
      }
    });
  });
  await fs.mkdir(path.dirname(lockPath), { recursive: true });
  await fs.writeFile(lockPath, JSON.stringify({ host: '127.0.0.1', port: address.port, token, pid: process.pid }), { mode: 0o600 });
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
  status.text = '$(plug) Atlas IDE'; status.tooltip = 'Atlas IDE bridge connected'; status.show();
  context.subscriptions.push(status, { dispose: () => { server.close(); void fs.rm(lockPath, { force: true }); } });
}

export function deactivate(): void { /* VS Code disposes the extension context. */ }
