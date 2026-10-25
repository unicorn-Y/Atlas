const fs = require('node:fs');
const path = require('node:path');
const parser = require('@babel/parser');
const traverse = require('@babel/traverse').default;

const rendererRoot = path.resolve(__dirname, '../src/renderer');
const catalogPath = path.join(rendererRoot, 'services/locales/en-US.ts');
const catalogSource = fs.readFileSync(catalogPath, 'utf8');
const catalogAst = parser.parse(catalogSource, { sourceType: 'module', plugins: ['typescript'] });
const catalog = new Set();
traverse(catalogAst, {
  ObjectProperty(p) {
    if (p.node.key.type === 'StringLiteral') catalog.add(p.node.key.value);
  },
});

const files = [];
function collectFiles(directory) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) collectFiles(absolute);
    else if (/\.(?:ts|tsx)$/.test(entry.name) && !/\.test\.(?:ts|tsx)$/.test(entry.name)
      && !absolute.includes(`${path.sep}services${path.sep}locales${path.sep}`)
      && !absolute.endsWith(`${path.sep}services${path.sep}i18n.ts`)) files.push(absolute);
  }
}
collectFiles(rendererRoot);

const sourceStrings = new Set();
const hasCjk = (value) => /[\u3400-\u9fff]/.test(value);
for (const file of files) {
  const ast = parser.parse(fs.readFileSync(file, 'utf8'), {
    sourceType: 'unambiguous',
    plugins: ['typescript', 'jsx', 'decorators-legacy'],
  });
  traverse(ast, {
    StringLiteral(p) {
      if (hasCjk(p.node.value)) sourceStrings.add(p.node.value);
    },
    JSXText(p) {
      const value = p.node.value.trim();
      if (hasCjk(value)) sourceStrings.add(value);
    },
    TemplateLiteral(p) {
      if (!p.node.expressions.length) return;
      const value = p.node.quasis.map((quasi, index) => {
        const text = quasi.value.cooked ?? quasi.value.raw;
        return index < p.node.expressions.length ? `${text}__U26_SLOT_${index}__` : text;
      }).join('');
      if (hasCjk(value)) sourceStrings.add(value);
    },
  });
}

const missing = [...sourceStrings].filter((value) => !catalog.has(value));
if (missing.length) {
  console.error(`I18N COVERAGE FAIL: ${missing.length}/${sourceStrings.size} Chinese renderer strings missing from en-US.ts`);
  for (const value of missing.slice(0, 80)) console.error(`- ${JSON.stringify(value)}`);
  process.exit(1);
}
console.log(`I18N COVERAGE PASS: ${sourceStrings.size} Chinese static and interpolated renderer strings in ${files.length} files; ${catalog.size} locale entries`);
