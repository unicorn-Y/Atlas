#!/usr/bin/env node
/**
 * P3: extract the eipc RPC service definitions.
 * Shape:  var NS="$eipc_message$<guid>_$_<namespace>_$_";
 *         eo(NS,"ServiceName",senderCheck,{methods:[[name,[[param,Validator],...]],...],
 *                                          events:[[name,Validator],...], ...})
 * and the generated renderer side:
 *         dispatch<Event>(), update<Store>Store(), etc.
 * Emits EIPC-SERVICES.tsv, EIPC-METHODS.tsv, EIPC-EVENTS.tsv.
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ASAR = process.argv[2], OUT = process.argv[3];
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p); else if (/\.(js|mjs)$/i.test(e.name)) files.push(p);
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

const lit = (n) => n && n.type === 'Literal' ? n.value : null;
const idName = (n) => n && n.type === 'Identifier' ? n.name : null;

const services = [], methods = [], events = [];
for (const f of files) {
  const rel = path.relative(ASAR, f).replace(/\\/g, '/');
  let src;
  try { src = fs.readFileSync(f, 'utf8'); } catch { continue; }
  if (!src.includes('_$_')) continue;
  let ast;
  try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true, allowHashBang: true, allowAwaitOutsideFunction: true }); }
  catch { continue; }

  // collect namespace vars: var X = "$eipc_message$<guid>_$_<ns>_$_"
  const nsVars = {};
  for (const node of ast.body) {
    if (node.type !== 'VariableDeclaration') continue;
    for (const d of node.declarations) {
      const v = lit(d.init);
      if (typeof v === 'string' && v.includes('$eipc_message$')) nsVars[idName(d.id)] = v;
    }
  }

  walkNode(ast, (n) => {
    if (n.type !== 'CallExpression') return;
    // eo(<nsVar>, "Service", <check>, { ... })
    const a = n.arguments;
    if (a.length < 4) return;
    const ns = a[0].type === 'Identifier' ? nsVars[a[0].name] : lit(a[0]);
    const svc = lit(a[1]);
    const opts = a[3];
    if (!svc || !opts || opts.type !== 'ObjectExpression') return;
    if (typeof ns !== 'string' || !ns.includes('$eipc_message$')) return;
    const props = {};
    for (const p of opts.properties) {
      const k = p.key && (p.key.name || p.key.value);
      if (k) props[k] = p.value;
    }
    services.push([rel, ns, svc, Object.keys(props).join(',')]);
    const grab = (propName, kind) => {
      const arr = props[propName];
      if (!arr || arr.type !== 'ArrayExpression') return;
      for (const el of arr.elements) {
        if (!el || el.type !== 'ArrayExpression') continue;
        const name = lit(el.elements[0]);
        if (typeof name !== 'string') continue;
        const params = el.elements[1];
        const pnames = [];
        if (params && params.type === 'ArrayExpression') {
          for (const pdef of params.elements) {
            if (!pdef) continue;
            const pn = pdef.type === 'ArrayExpression' ? lit(pdef.elements[0]) : lit(pdef);
            if (typeof pn === 'string') pnames.push(pn);
          }
        }
        const row = [rel, svc, name, pnames.join(','), kind, ns];
        if (kind === 'method') methods.push(row);
        else events.push(row);
      }
    };
    grab('methods', 'method');
    grab('events', 'event');
    grab('subscriptions', 'subscription');
  });
}

const w = (n, h, rows) => fs.writeFileSync(path.join(OUT, n),
  [h, ...rows.map(r => r.map(x => String(x).replace(/[\r\n]/g, ' ')).join('\t'))].join('\n') + '\n', 'utf8');
w('EIPC-SERVICES.tsv', ['path', 'namespace', 'service', 'option_keys'], services);
w('EIPC-METHODS.tsv', ['path', 'service', 'method', 'params', 'kind', 'namespace'], methods);
w('EIPC-EVENTS.tsv', ['path', 'service', 'event', 'params', 'kind', 'namespace'], events);
console.log('services', services.length, 'methods', methods.length, 'events', events.length);
