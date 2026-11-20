// Extract product-facing TypeScript/JavaScript declarations to JSONL.
// Usage: node extract_decls.mjs <root> <out.jsonl> <product> [includeDirs]
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire('D:/Atlas/.worktrees/_codex-compare-parser-20261120/package.json');
const ts = require('typescript');

const [root, out, product, includeArg] = process.argv.slice(2);
const includeDirs = (includeArg || '').split(',').filter(Boolean).map(s => path.resolve(root, s));
const EXCLUDE_RE = /(^|[\\/])(node_modules|dist|build|coverage|tests?|__tests__|fixtures?|examples?|benchmarks?|\.git)([\\/]|$)|\.(test|spec|stories)\.[cm]?[jt]sx?$/i;
const EXTS = new Set(['.ts', '.tsx', '.mts', '.cts', '.js', '.mjs', '.cjs']);

function walk(dir, acc) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of ents) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (EXCLUDE_RE.test(p)) continue;
      walk(p, acc);
    } else if (e.isFile()) {
      const ext = path.extname(e.name).toLowerCase();
      if (!EXTS.has(ext)) continue;
      if (EXCLUDE_RE.test(p)) continue;
      acc.push(p);
    }
  }
}

// package.json index: nearest ancestor
const pkgIndex = new Map();
function indexPackages(dir) {
  let ents;
  try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
  for (const e of ents) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (EXCLUDE_RE.test(p)) continue;
      indexPackages(p);
    } else if (e.name === 'package.json') {
      try {
        const j = JSON.parse(fs.readFileSync(p, 'utf8'));
        pkgIndex.set(path.dirname(p), { name: j.name || '', desc: j.description || '', version: j.version || '' });
      } catch { /* ignore */ }
    }
  }
}
indexPackages(root);

function nearestPkg(file) {
  let d = path.dirname(file);
  for (let i = 0; i < 8; i++) {
    if (pkgIndex.has(d)) return { dir: d, ...pkgIndex.get(d) };
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return { dir: '', name: '', desc: '', version: '' };
}

function rel(p) { return path.relative(root, p).replace(/\\/g, '/'); }

function layerOf(p) {
  const r = rel(p);
  if (/test-support|[\\/]tests?[\\/]|\.test\.|\.spec\./i.test(r)) return '测试基座';
  if (/^packages\/[^/]+\/[^/]+\/src\//.test(r) || /^apps\/[^/]+\/src\//.test(r)) return '产品运行面';
  if (/scripts\/|\.github\/|packaging\//.test(r)) return '构建发布面';
  return '其他';
}

function docOf(node) {
  const parts = [];
  for (const d of (node.jsDoc || [])) {
    if (typeof d.comment === 'string') parts.push(d.comment);
    else if (Array.isArray(d.comment)) parts.push(d.comment.map(x => x.text || '').join(''));
  }
  return parts.join(' ').replace(/\s+/g, ' ').trim().slice(0, 400);
}

function mods(node) {
  const out = [];
  const ms = ts.canHaveModifiers(node) ? ts.getModifiers(node) : undefined;
  for (const m of (ms || [])) {
    const k = ts.SyntaxKind[m.kind];
    if (k) out.push(k.replace('Keyword', '').toLowerCase());
  }
  return out;
}

function paramText(node) {
  const ps = (node.parameters || []).map(p => {
    const t = p.type ? ': ' + p.type.getText() : '';
    const q = p.questionToken ? '?' : '';
    return p.name.getText() + q + t;
  });
  return '(' + ps.join(', ') + ')';
}

function fnSig(node) {
  const ret = node.type ? ': ' + node.type.getText() : '';
  return paramText(node) + ret;
}

function propSig(node) {
  const t = node.type ? node.type.getText() : '';
  const init = node.initializer ? ' = ' + node.initializer.getText().slice(0, 80) : '';
  return t + init;
}

const files = [];
for (const d of (includeDirs.length ? includeDirs : [root])) {
  if (fs.existsSync(d) && fs.statSync(d).isDirectory()) walk(d, files);
  else if (fs.existsSync(d)) files.push(d);
}
files.sort();

const stream = fs.createWriteStream(out, { encoding: 'utf8' });
let n = 0;
function emit(row) {
  stream.write(JSON.stringify(row) + '\n'); n++;
}

for (const file of files) {
  let text;
  try { text = fs.readFileSync(file, 'utf8'); } catch { continue; }
  const sf = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
  const pkg = nearestPkg(file);
  const base = { product, package: pkg.name, package_dir: rel(pkg.dir), file: rel(file), layer: layerOf(file), dts: file.endsWith('.d.ts') };
  const line = node => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;

  for (const stmt of sf.statements) {
    // export { a, b as c } from './x'
    if (ts.isExportDeclaration(stmt) && stmt.exportClause && ts.isNamedExports(stmt.exportClause)) {
      const from = stmt.moduleSpecifier ? stmt.moduleSpecifier.getText().slice(0, 160) : '';
      for (const el of stmt.exportClause.elements) {
        emit({ ...base, kind: '再导出', symbol: el.name.text, parent: '', signature: (el.propertyName ? el.propertyName.text + ' as ' : '') + from, decorators: '', doc: '', line: line(stmt), exported: true });
      }
      continue;
    }
    // export default expr
    if (ts.isExportAssignment(stmt)) {
      emit({ ...base, kind: '默认导出', symbol: 'default', parent: '', signature: stmt.expression.getText().slice(0, 240), decorators: '', doc: docOf(stmt), line: line(stmt), exported: true });
      continue;
    }
    const exported = (mods(stmt).includes('export'));
    if (!exported) continue;

    if (ts.isClassDeclaration(stmt) && stmt.name) {
      const name = stmt.name.text;
      const heritage = (stmt.heritageClauses || []).map(h => h.getText()).join(' ').slice(0, 200);
      emit({ ...base, kind: '类', symbol: name, parent: '', signature: heritage, decorators: (stmt.decorators || []).map(d => d.getText()).join(' ').slice(0, 120), doc: docOf(stmt), line: line(stmt), exported: true });
      for (const m of stmt.members) {
        const mm = mods(m);
        if (mm.includes('private') || mm.includes('protected')) continue;
        if (!m.name || m.name.text === undefined) continue;
        const mn = m.name.text;
        if (mn.startsWith('#')) continue;
        if (ts.isMethodDeclaration(m)) {
          emit({ ...base, kind: mm.includes('static') ? '静态方法' : '方法', symbol: name + '.' + mn, parent: name, signature: fnSig(m), decorators: (m.decorators || []).map(d => d.getText()).join(' ').slice(0, 120), doc: docOf(m), line: line(m), exported: false });
        } else if (ts.isGetAccessor(m)) {
          emit({ ...base, kind: 'getter', symbol: name + '.' + mn, parent: name, signature: (m.type ? ': ' + m.type.getText() : ''), decorators: '', doc: docOf(m), line: line(m), exported: false });
        } else if (ts.isSetAccessor(m)) {
          emit({ ...base, kind: 'setter', symbol: name + '.' + mn, parent: name, signature: fnSig(m), decorators: '', doc: docOf(m), line: line(m), exported: false });
        } else if (ts.isPropertyDeclaration(m)) {
          emit({ ...base, kind: mm.includes('static') ? '静态属性' : '属性', symbol: name + '.' + mn, parent: name, signature: propSig(m), decorators: (m.decorators || []).map(d => d.getText()).join(' ').slice(0, 120), doc: docOf(m), line: line(m), exported: false });
        } else if (ts.isConstructorDeclaration(m)) {
          emit({ ...base, kind: '构造函数', symbol: name + '.constructor', parent: name, signature: fnSig(m), decorators: '', doc: docOf(m), line: line(m), exported: false });
        }
      }
    } else if (ts.isFunctionDeclaration(stmt) && stmt.name) {
      emit({ ...base, kind: '函数', symbol: stmt.name.text, parent: '', signature: fnSig(stmt), decorators: (stmt.decorators || []).map(d => d.getText()).join(' ').slice(0, 120), doc: docOf(stmt), line: line(stmt), exported: true });
    } else if (ts.isInterfaceDeclaration(stmt)) {
      emit({ ...base, kind: '接口', symbol: stmt.name.text, parent: '', signature: (stmt.heritageClauses || []).map(h => h.getText()).join(' ').slice(0, 200), decorators: '', doc: docOf(stmt), line: line(stmt), exported: true });
    } else if (ts.isTypeAliasDeclaration(stmt)) {
      emit({ ...base, kind: '类型', symbol: stmt.name.text, parent: '', signature: stmt.type.getText().slice(0, 240), decorators: '', doc: docOf(stmt), line: line(stmt), exported: true });
    } else if (ts.isEnumDeclaration(stmt)) {
      emit({ ...base, kind: '枚举', symbol: stmt.name.text, parent: '', signature: (stmt.members || []).map(m => m.name.getText()).join(', ').slice(0, 240), decorators: '', doc: docOf(stmt), line: line(stmt), exported: true });
    } else if (ts.isVariableStatement(stmt)) {
      for (const d of stmt.declarationList.declarations) {
        if (!d.name || d.name.text === undefined) continue;
        let sig = d.type ? d.type.getText() : '';
        let kind = '常量';
        if (d.initializer && (ts.isArrowFunction(d.initializer) || ts.isFunctionExpression(d.initializer))) {
          kind = '函数';
          sig = fnSig(d.initializer);
        } else if (d.initializer) {
          sig = sig || d.initializer.getText().slice(0, 200);
        }
        emit({ ...base, kind, symbol: d.name.text, parent: '', signature: sig, decorators: '', doc: docOf(stmt), line: line(d), exported: true });
      }
    } else if (ts.isModuleDeclaration(stmt) && stmt.name) {
      emit({ ...base, kind: '命名空间', symbol: stmt.name.getText(), parent: '', signature: '', decorators: '', doc: docOf(stmt), line: line(stmt), exported: true });
    }
  }
}
stream.end();
console.log(JSON.stringify({ product, files: files.length, rows: n, out }));