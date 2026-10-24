"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = __importStar(require("vscode"));
const crypto = __importStar(require("node:crypto"));
const fs = __importStar(require("node:fs/promises"));
const os = __importStar(require("node:os"));
const path = __importStar(require("node:path"));
const ws_1 = require("ws");
const lockPath = path.join(os.homedir(), '.atlas', 'ide', 'vscode.json');
function editorContext() {
    const editor = vscode.window.activeTextEditor;
    if (!editor)
        return { file: null, selection: null, workspace: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? null };
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
async function handle(req) {
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
async function activate(context) {
    const token = crypto.randomBytes(32).toString('hex');
    const server = new ws_1.WebSocketServer({ host: '127.0.0.1', port: 0 });
    await new Promise((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
    const address = server.address();
    if (!address || typeof address === 'string')
        throw new Error('Atlas IDE bridge did not bind a TCP port');
    server.on('connection', (socket, request) => {
        const url = new URL(request.url ?? '/', 'http://127.0.0.1');
        if (url.searchParams.get('token') !== token) {
            socket.close(1008, 'unauthorized');
            return;
        }
        socket.on('message', async (raw) => {
            let req;
            try {
                req = JSON.parse(raw.toString());
                const result = await handle(req);
                socket.send(JSON.stringify({ id: req.id, result }));
            }
            catch (error) {
                socket.send(JSON.stringify({ id: '', error: error instanceof Error ? error.message : String(error) }));
            }
        });
    });
    await fs.mkdir(path.dirname(lockPath), { recursive: true });
    await fs.writeFile(lockPath, JSON.stringify({ host: '127.0.0.1', port: address.port, token, pid: process.pid }), { mode: 0o600 });
    const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 50);
    status.text = '$(plug) Atlas IDE';
    status.tooltip = 'Atlas IDE bridge connected';
    status.show();
    context.subscriptions.push(status, { dispose: () => { server.close(); void fs.rm(lockPath, { force: true }); } });
}
function deactivate() { }
//# sourceMappingURL=extension.js.map