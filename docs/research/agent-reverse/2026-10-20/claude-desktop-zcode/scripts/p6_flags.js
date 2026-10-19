#!/usr/bin/env node
/**
 * P6/P4: extract the feature-flag registry and policy gates.
 * The bundle registers flags as object literals with keys such as
 *   flatKey / support:{enabled:{scopes,availableInVersion},executionTarget,visibility}
 *   default:{...}, failClosedValue, categories, surfaces
 * We locate every `flatKey:"..."` and pull the surrounding literal fields.
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ASAR = process.argv[2], OUT = process.argv[3];
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p); else if (/\.js$/i.test(e.name)) files.push(p);
  }
})(ASAR);

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

const lit = (n) => {
  if (!n) return null;
  if (n.type === 'Literal') return n.value;
  if (n.type === 'TemplateLiteral' && n.expressions.length === 0) return n.quasis.map(q => q.value.cooked).join('');
  if (n.type === 'Identifier') return n.name;
  if (n.type === 'UnaryExpression' && n.operator === '!') return !lit(n.argument);
  return null;
};

const rows = [];
for (const f of files) {
  const rel = path.relative(ASAR, f).replace(/\\/g, '/');
  let src;
  try { src = fs.readFileSync(f, 'utf8'); } catch { continue; }
  if (!src.includes('flatKey')) continue;
  let ast;
  try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true, allowHashBang: true }); }
  catch { continue; }

  walkNode(ast, (n) => {
    if (n.type !== 'ObjectExpression') return;
    const props = {};
    for (const p of n.properties) {
      if (p.type !== 'Property' || !p.key) continue;
      const k = p.key.name || p.key.value;
      if (k) props[k] = p.value;
    }
    if (!props.flatKey) return;
    const flatKey = lit(props.flatKey);
    if (typeof flatKey !== 'string') return;
    const support = props.support;
    let scopes = '', target = '', vis = '', avail = '';
    if (support && support.type === 'ObjectExpression') {
      for (const sp of support.properties) {
        const sk = sp.key && (sp.key.name || sp.key.value);
        if (sk === 'enabled' && sp.value.type === 'ObjectExpression') {
          for (const ep of sp.value.properties) {
            const ek = ep.key && (ep.key.name || ep.key.value);
            if (ek === 'scopes' && ep.value.type === 'ArrayExpression') scopes = ep.value.elements.map(lit).filter(Boolean).join(',');
            if (ek === 'availableInVersion') avail = String(lit(ep.value) ?? '');
            if (ek === 'executionTarget') target = String(lit(ep.value) ?? '');
            if (ek === 'visibility') vis = String(lit(ep.value) ?? '');
          }
        }
        if (sk === 'executionTarget') target = target || String(lit(sp.value) ?? '');
        if (sk === 'visibility') vis = vis || String(lit(sp.value) ?? '');
      }
    }
    const failClosed = props.failClosedValue ? String(lit(props.failClosedValue)) : '';
    let title = '';
    if (props.title && props.title.type === 'ObjectExpression') {
      for (const tp of props.title.properties) {
        if ((tp.key.name || tp.key.value) === 'defaultMessage') title = String(tp.value.value ?? '');
      }
    }
    rows.push([rel, flatKey, title, scopes, target, vis, avail, failClosed]);
  });
}
const hdr = ['path', 'flat_key', 'title', 'scopes', 'execution_target', 'visibility', 'available_in_version', 'fail_closed'];
fs.writeFileSync(path.join(OUT, 'FEATURE-FLAGS.tsv'), [hdr, ...rows.map(r => r.map(x => String(x).replace(/\t/g, ' ')))].map(r => r.join('\t')).join('\n') + '\n', 'utf8');
console.log('flags', rows.length);
