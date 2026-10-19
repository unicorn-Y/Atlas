"""Generate GO-FUNCTIONS.tsv, GO-PACKAGES.tsv, PE-IMPORTS.tsv, NATIVE-ADDON-EXPORTS.tsv."""
import sys, os, json, re, struct, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE
import analyze_go as A

IDX = r'D:\Atlas\_research\claude-desktop\2026-10-20\index\work-P5'
RES = r'D:\Atlas\_research\claude-desktop\2026-10-20\extract\app\resources'
BINARIES = ['cowork-svc', 'claude-ssh-broker', 'claude-ssh-proxy', 'claude-ssh-askpass']
STDLIB_TOP = A.STDLIB_TOP

def load(b):
    return json.load(open(os.path.join(IDX, b + '.json'), encoding='utf-8'))

def write(path, header, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\t'.join(header) + '\n')
        for r in rows:
            f.write('\t'.join('' if x is None else str(x).replace('\t', ' ').replace('\n', '\\n') for x in r) + '\n')
    print('wrote', os.path.basename(path), len(rows), 'rows')

# ---------------- GO-FUNCTIONS.tsv ----------------
def gen_functions():
    rows = []
    for b in BINARIES:
        j = load(b)
        for f in j['funcs']:
            pkg, fn = A.split_funcname(f['name'])
            rows.append([b, f['index'], pkg or '<none>', fn, f['entry_hex'], f['size']])
    write(os.path.join(IDX, 'GO-FUNCTIONS.tsv'),
          ['binary', 'func_index', 'package', 'function', 'entry_hex', 'size'], rows)
    return rows

# ---------------- GO-PACKAGES.tsv ----------------
def gen_packages():
    rows = []
    prefixes = {b: load(b)['first_party_prefixes'] for b in BINARIES}
    for b in BINARIES:
        j = load(b)
        per = collections.Counter()
        for f in j['funcs']:
            pkg, _ = A.split_funcname(f['name'])
            per[pkg or '<none>'] += 1
        for pkg, n in per.items():
            fp = 'no'
            if pkg == 'main':
                fp = 'yes'
            else:
                for p in prefixes[b]:
                    if pkg == p or pkg.startswith(p + '/'):
                        fp = 'yes'
                        break
            rows.append([b, pkg, n, fp])
    rows.sort(key=lambda r: (r[0], -r[2], r[1]))
    write(os.path.join(IDX, 'GO-PACKAGES.tsv'),
          ['binary', 'package', 'func_count', 'is_first_party'], rows)
    return rows

# ---------------- PE-IMPORTS.tsv ----------------
def gen_imports():
    rows = []
    targets = [(b, os.path.join(RES, b + '.exe')) for b in BINARIES]
    targets.append(('claude-native-binding.node',
                    os.path.join(RES, 'app.asar.unpacked', 'node_modules', '%40ant',
                                 'claude-native', 'claude-native-binding.node')))
    targets.append(('chrome-native-host.exe', os.path.join(RES, 'chrome-native-host.exe')))
    for name, path in targets:
        if not os.path.exists(path):
            continue
        md = PE(path)
        for dll, fs in md.imports():
            rows.append([name, dll, len(fs), ', '.join(fs[:25])])
    write(os.path.join(IDX, 'PE-IMPORTS.tsv'),
          ['binary', 'dll', 'import_count', 'sample_imports'], rows)
    return rows

# ---------------- NATIVE-ADDON-EXPORTS.tsv ----------------
def gen_native():
    p = os.path.join(RES, 'app.asar.unpacked', 'node_modules', '%40ant',
                     'claude-native', 'claude-native-binding.node')
    d = open(p, 'rb').read()
    md = PE(p)
    pat = re.compile(rb'Failed to register function \x60([a-z0-9_]{2,70})\x60')
    def camel(s):
        q = s.split('_')
        return q[0] + ''.join(x[:1].upper() + x[1:] for x in q[1:])
    rows = []
    seen = set()
    for m in pat.finditer(d):
        sn = m.group(1).decode()
        js = camel(sn)
        if js in seen:
            continue
        seen.add(js)
        rows.append([js, sn, 'napi_register_module_v1 -> exports.%s' % js,
                     '0x%x' % m.start(), 'register-msg'])
    # the PE's only export
    for n, o, r in md.exports():
        rows.append([n, n, 'PE export table', '0x%x' % (md.image_base + r), 'pe-export'])
    write(os.path.join(IDX, 'NATIVE-ADDON-EXPORTS.tsv'),
          ['js_name', 'napi_symbol', 'registration', 'evidence_offset', 'evidence_kind'], rows)
    return rows

if __name__ == '__main__':
    gen_functions()
    gen_packages()
    gen_imports()
    gen_native()
