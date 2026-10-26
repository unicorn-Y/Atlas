import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.ATLAS_OFFICE_PORT || 3000);
const atlasPort = Number(process.env.ATLAS_PORT || 8765);
const certificate = process.env.ATLAS_OFFICE_CERT_FILE || path.join(root, 'certs', 'localhost.pem');
const privateKey = process.env.ATLAS_OFFICE_KEY_FILE || path.join(root, 'certs', 'localhost-key.pem');
const mime = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.svg': 'image/svg+xml' };

function send(response, status, type, body) {
  response.writeHead(status, {
    'Content-Type': type,
    'Content-Security-Policy': "default-src 'self'; script-src 'self' https://appsforoffice.microsoft.com; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors https://*.office.com https://*.officeapps.live.com https://*.microsoft365.com https://localhost https://localhost:3000",
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store',
  });
  response.end(body);
}

if (!fs.existsSync(certificate) || !fs.existsSync(privateKey)) {
  process.stderr.write('TLS certificate not found. Generate a trusted localhost certificate with mkcert; see README.md.\n');
  process.exit(1);
}

https.createServer({ cert: fs.readFileSync(certificate), key: fs.readFileSync(privateKey) }, async (request, response) => {
  const host = String(request.headers.host || '').split(':')[0].toLowerCase();
  if (host !== 'localhost' && host !== '127.0.0.1') return send(response, 403, 'text/plain', 'Loopback host only');
  const target = new URL(request.url || '/', 'https://localhost');
  if (target.pathname.startsWith('/api/office/')) {
    if (!['GET', 'POST', 'DELETE'].includes(request.method || '')) return send(response, 405, 'application/json', JSON.stringify({ detail: 'Method not allowed' }));
    const chunks = [];
    let size = 0;
    for await (const chunk of request) {
      size += chunk.length;
      if (size > 220_000) return send(response, 413, 'application/json', JSON.stringify({ detail: 'Request too large' }));
      chunks.push(chunk);
    }
    try {
      const upstream = await fetch(`http://127.0.0.1:${atlasPort}${target.pathname}${target.search}`, {
        method: request.method,
        headers: {
          ...(request.headers['content-type'] ? { 'content-type': request.headers['content-type'] } : {}),
          ...(request.headers['x-atlas-office-token'] ? { 'x-atlas-office-token': request.headers['x-atlas-office-token'] } : {}),
        },
        ...(request.method === 'POST' ? { body: Buffer.concat(chunks) } : {}),
        signal: AbortSignal.timeout(5000),
      });
      const body = Buffer.from(await upstream.arrayBuffer());
      return send(response, upstream.status, upstream.headers.get('content-type') || 'application/json', body);
    } catch (error) {
      const message = error instanceof Error && error.name === 'TimeoutError' ? 'Atlas backend request timed out' : 'Atlas backend is unavailable';
      return send(response, 503, 'application/json', JSON.stringify({ detail: message }));
    }
  }
  const relative = target.pathname === '/' ? '/taskpane.html' : decodeURIComponent(target.pathname);
  const file = path.resolve(root, `.${relative}`);
  if (!file.startsWith(`${root}${path.sep}`)) return send(response, 404, 'text/plain', 'Not found');
  try { return send(response, 200, mime[path.extname(file)] || 'application/octet-stream', fs.readFileSync(file)); }
  catch { return send(response, 404, 'text/plain', 'Not found'); }
}).listen(port, '127.0.0.1', () => process.stdout.write(`Atlas Office Add-in: https://localhost:${port}/taskpane.html\n`));
