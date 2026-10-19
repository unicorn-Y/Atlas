#!/usr/bin/env node
/**
 * P1c: identify the SPA's route table and React component surface via AST,
 * without relying on source-level property names surviving minification.
 *
 * Strategy:
 *  - find object literals that contain a "path" or "route" property whose value is
 *    a route-like string, plus sibling component references
 *  - collect component-ish identifiers (capitalized) that are used as JSX or passed
 *    as `component:`-style values
 *  - record React hook usage counts per file as a proxy for component density
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ION = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/app/resources/ion-dist';
const OUT = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';

const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (/\.js$/i.test(e.name)) files.push(p);
  }
})(ION);
files.sort();

function walkNode(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) { for (const n of node) walkNode(n, visit); return; }
  if (typeof node.type !== 'string') return;
  visit(node);
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'start' || k === 'end') continue;
    const v = node[k];
    if (v && typeof v === 'object') walkNode(v, visit);
  }
}

const routeRows = [], compRows = [], hookRows = [];
const routeLike = /^\/[a-z0-9][a-z0-9-]{0,40}(\/[a-z0-9:_.-]{0,40})*$/i;

for (const f of files) {
  const rel = path.relative(ION, f).replace(/\\/g, '/');
  let src;
  try { src = fs.readFileSync(f, 'utf8'); } catch { continue; }
  // skip enormous vendor blobs quickly for the component pass, but still scan routes
  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true, allowHashBang: true });
  } catch {
    try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true, allowHashBang: true }); }
    catch { continue; }
  }

  const caps = new Set();
  const hooks = {};
  walkNode(ast, (n) => {
    // route-bearing object literals
    if (n.type === 'ObjectExpression') {
      const p = {};
      for (const pr of n.properties) {
        if (pr.type !== 'Property' || !pr.key) continue;
        p[pr.key.name || pr.key.value] = pr.value;
      }
      const pv = p.path || p.route || p.to;
      if (pv && pv.type === 'Literal' && typeof pv.value === 'string' && routeLike.test(pv.value)) {
        let comp = '';
        for (const k of ['component', 'element', 'Component', 'render', 'loader', 'action', 'lazy']) {
          const v = p[k];
          if (!v) continue;
          if (v.type === 'Identifier') comp += k + '=' + v.name + ' ';
          else if (v.type === 'CallExpression' && v.callee) {
            const cn = v.callee.type === 'Identifier' ? v.callee.name
              : v.callee.type === 'MemberExpression' && v.callee.property ? v.callee.property.name : '';
            comp += k + '=' + cn + '() ';
          } else comp += k + '=<' + v.type + '> ';
        }
        routeRows.push([rel, pv.value, comp.trim()]);
      }
    }
    // capitalized identifiers used as values (components) or JSX tag names
    if (n.type === 'JSXOpeningElement' && n.name && n.name.type === 'JSXIdentifier') {
      const nm = n.name.name;
      if (/^[A-Z]/.test(nm) && nm !== 'Fragment') caps.add(nm);
    }
    // hooks
    if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Identifier' && /^use[A-Z]/.test(n.callee.name)) {
      hooks[n.callee.name] = (hooks[n.callee.name] || 0) + 1;
    }
  });

  if (caps.size) for (const c of caps) compRows.push([rel, c]);
  for (const [h, c] of Object.entries(hooks)) hookRows.push([rel, h, c]);
}

const w = (n, h, rows) => fs.writeFileSync(path.join(OUT, n),
  [h, ...rows.map(r => r.map(x => String(x).replace(/[\r\n\t]/g, ' ')).join('\t'))].join('\n') + '\n', 'utf8');
w('ION-ROUTE-TABLE.tsv', ['file', 'route', 'components'], routeRows);
w('ION-COMPONENTS.tsv', ['file', 'component_name'], compRows);
w('ION-HOOKS.tsv', ['file', 'hook', 'count'], hookRows);

const uniqRoutes = new Set(routeRows.map(r => r[1]));
const uniqComps = new Set(compRows.map(r => r[1]));
console.log(JSON.stringify({
  route_objects: routeRows.length,
  unique_routes: uniqRoutes.size,
  component_refs: compRows.length,
  unique_components: uniqComps.size,
  files_with_jsx: new Set(compRows.map(r => r[0])).size,
}, null, 2));
