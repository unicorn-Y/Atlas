#!/usr/bin/env node
/** P3: NETWORK-ENDPOINTS.tsv — every literal URL/host in the bundles, classified. */
const fs = require('fs');
const path = require('path');
const ASAR = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar';
const OUT = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';

const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p); else if (/\.(js|mjs|html|json|css)$/i.test(e.name)) files.push(p);
  }
})(ASAR);

const re = /https?:\/\/[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%{}-]{3,200}/g;
const skip = /^(https?:\/\/(\$|\)|\.\.\.|\.|\*|REGION|12345|2f98127|[a-z]+@))/;
const rows = [];
for (const f of files) {
  const rel = path.relative(ASAR, f).replace(/\\/g, '/');
  let src;
  try { src = fs.readFileSync(f, 'utf8'); } catch { continue; }
  let m;
  const seen = new Set();
  while ((m = re.exec(src))) {
    let u = m[0].replace(/["'`),;\\]+$/, '');
    if (skip.test(u) || seen.has(u)) continue;
    seen.add(u);
    let host = '', cls = 'other';
    try {
      host = new URL(u.replace(/\$\{[^}]*\}/g, 'X')).host;
    } catch { host = u.split('/')[2] || ''; }
    if (/claude\.ai|claude\.com/.test(host)) cls = 'first-party-web';
    else if (/anthropic\.com|anthropic\.enterprise|claude-ai\.staging|ant\.dev|fedstart/.test(host)) cls = 'first-party-api';
    else if (/downloads\.claude\.ai/.test(host)) cls = 'first-party-download';
    else if (/sentry\.io/.test(host)) cls = 'telemetry';
    else if (/github\.com|api\.github\.com/.test(host)) cls = 'third-party-github';
    else if (/google\.com|gstatic|googleapis/.test(host)) cls = 'third-party-google';
    else if (/jsdelivr|cloudflare|cdnjs/.test(host)) cls = 'cdn';
    else if (/slack\.com/.test(host)) cls = 'third-party-slack';
    else if (/box\.com/.test(host)) cls = 'third-party-box';
    else if (/microsoft|azure|msal|office|entra/.test(host)) cls = 'third-party-ms';
    else if (/example\.com|dummy\.dsn|127\.0\.0\.1|localhost/.test(host)) cls = 'placeholder';
    rows.push([rel, u, host, cls]);
  }
}
const uniq = new Map();
for (const r of rows) {
  const k = r[1];
  if (!uniq.has(k)) uniq.set(k, { ...r, files: new Set() });
  uniq.get(k).files.add(r[0]);
}
const out = [...uniq.values()].sort((a, b) => (a[3] + a[2]).localeCompare(b[3] + b[2]));
fs.writeFileSync(path.join(OUT, 'NETWORK-ENDPOINTS.tsv'),
  'url\thost\tclass\tseen_in_files\tfile_count\n' +
  out.map(r => [r[1], r[2], r[3], [...r.files].join(' | '), r.files.size].join('\t')).join('\n') + '\n', 'utf8');
const cls = {};
for (const r of out) cls[r[3]] = (cls[r[3]] || 0) + 1;
console.log('unique urls', out.length);
console.log(cls);
