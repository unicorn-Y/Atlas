#!/usr/bin/env node
/**
 * P1/P3: extract every string-enum table and every IPC registration site from
 * the minified main-process bundles. The enums are generated as
 *   var NAME=function(e){return e.Key="value",...,e}({})
 * and channels are referenced symbolically (e.g. ipcMain.handle(Za.Foo, ...)).
 * We therefore resolve symbolic channel args back to their literal enum value.
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ASAR = process.argv[2];
const OUT = process.argv[3];
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (/\.(js|mjs|cjs)$/i.test(e.name)) files.push(p);
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

const enumRows = [], regRows = [], bridgeRows = [];
for (const f of files) {
  const rel = path.relative(ASAR, f).replace(/\\/g, '/');
  const src = fs.readFileSync(f, 'utf8');
  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true, allowHashBang: true });
  } catch {
    try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true, allowHashBang: true }); }
    catch { continue; }
  }

  // Pass 1: collect enum tables declared in this file
  const localEnums = {};
  for (const node of ast.body) {
    if (node.type !== 'VariableDeclaration') continue;
    for (const d of node.declarations) {
      const id = d.id && d.id.name;
      const init = d.init;
      if (!id || !init || init.type !== 'CallExpression') continue;
      const callee = init.callee;
      const arg = init.arguments[0];
      if (callee.type !== 'FunctionExpression' || !arg || arg.type !== 'ObjectExpression') continue;
      const members = [];
      walkNode(callee.body, (n) => {
        if (n.type === 'AssignmentExpression' && n.left.type === 'MemberExpression' &&
            n.right.type === 'Literal' && typeof n.right.value === 'string') {
          const prop = n.left.property;
          members.push([prop.name || String(prop.value), n.right.value]);
        }
      });
      if (members.length) {
        localEnums[id] = Object.fromEntries(members);
        for (const [k, v] of members) enumRows.push([rel, id, k, v]);
      }
    }
  }

  // Pass 2: registration sites
  // Channels are frequently built as BinaryExpression concatenations such as
  // "Foo"+"_$_"+"bar"; fold them back to a literal and mark the folding.
  const resolve = (a, depth = 0) => {
    if (!a || depth > 8) return ['', 'none'];
    if (a.type === 'Literal') return [String(a.value), 'literal'];
    if (a.type === 'BinaryExpression' && a.operator === '+') {
      const [l, lk] = resolve(a.left, depth + 1);
      const [r, rk] = resolve(a.right, depth + 1);
      if (lk !== 'none' && rk !== 'none' && lk !== 'unresolved' && rk !== 'unresolved') {
        return [l + r, lk === 'literal' && rk === 'literal' ? 'concat' : 'concat:' + lk + '+' + rk];
      }
      return ['', 'concat-unresolved'];
    }
    if (a.type === 'TemplateLiteral') {
      let out = '';
      const kinds = [];
      for (let i = 0; i < a.quasis.length; i++) {
        out += a.quasis[i].value.cooked ?? '';
        if (i < a.expressions.length) {
          const [v, k] = resolve(a.expressions[i], depth + 1);
          if (k === 'none' || k === 'unresolved' || k === 'concat-unresolved') { out += '${?}'; kinds.push('dyn'); }
          else { out += v; kinds.push(k); }
        }
      }
      return [out, kinds.includes('dyn') ? 'template-partial' : 'template'];
    }
    if (a.type === 'MemberExpression') {
      const o = a.object, p = a.property;
      if (o.type === 'Identifier' && localEnums[o.name]) {
        const key = p.name || String(p.value);
        if (localEnums[o.name][key] !== undefined) return [localEnums[o.name][key], 'enum:' + o.name + '.' + key];
      }
      if (o.type === 'Identifier') return [p.name || String(p.value), 'member:' + o.name];
      return ['', 'member-expr'];
    }
    if (a.type === 'CallExpression') return ['', 'call'];
    if (a.type === 'Identifier') return ['', 'identifier:' + a.name];
    return ['', a.type];
  };

  walkNode(ast, (n) => {
    if (n.type !== 'CallExpression') return;
    const callee = n.callee;
    if (callee.type !== 'MemberExpression') return;
    const obj = callee.object, prop = callee.property;
    const pname = prop.name || String(prop.value);
    const oname = obj.type === 'Identifier' ? obj.name
      : obj.type === 'MemberExpression' ? (obj.property.name || String(obj.property.value)) : '';
    const full = oname + '.' + pname;
    const interesting = /^(ipcMain|ipcRenderer|webContents|sender)\.(handle|handleOnce|on|once|send|sendSync|invoke|postMessage|removeHandler|removeAllListeners)$/.test(full)
      || /^(contextBridge)\.(exposeInMainWorld|exposeInIsolatedWorld)$/.test(full)
      || /^(MessageChannelMain|MessagePortMain)/.test(oname);
    if (!interesting) return;
    const [ch, kind] = resolve(n.arguments[0]);
    const norm = oname === pname ? pname : full;
    if (/contextBridge/.test(norm)) bridgeRows.push([rel, norm, ch, kind]);
    else regRows.push([rel, norm, ch, kind]);
  });
}

const w = (n, h, rows) => fs.writeFileSync(path.join(OUT, n), [h, ...rows.map(r => r.join('\t'))].join('\n') + '\n', 'utf8');
w('STRING-ENUMS.tsv', ['path', 'enum_var', 'key', 'value'], enumRows);
w('IPC-REGISTRATIONS.tsv', ['path', 'api', 'channel_resolved', 'resolution'], regRows);
w('CONTEXTBRIDGE-EXPOSURES.tsv', ['path', 'api', 'world_key', 'resolution'], bridgeRows);
console.log('enum members', enumRows.length, 'registrations', regRows.length, 'bridges', bridgeRows.length);
