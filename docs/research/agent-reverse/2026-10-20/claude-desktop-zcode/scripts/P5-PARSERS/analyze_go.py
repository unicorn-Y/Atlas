"""Full Go binary analyzer: pclntab -> functions, packages, call edges, string refs.

Usage: python analyze_go.py <exe> <outjson>
"""
import sys, os, json, struct, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gopcln
from peutil import PE

IMPORT_PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_/.-~")

def split_funcname(s):
    """Return (package, function)."""
    if s.startswith('go:'):
        return ('go', s[3:])
    if s.startswith('type:'):
        rest = s[5:]
        if rest.startswith('.'):
            rest = rest[1:]
        if rest.startswith('eq.') or rest.startswith('hash.'):
            return ('type', s)
        # type:main.Foo
        p, f = split_funcname(rest)
        return ('type', s)
    # truncate at first char not valid in an import path
    i = 0
    while i < len(s) and s[i] in IMPORT_PATH_CHARS:
        i += 1
    prefix = s[:i]
    rest = s[i:]
    slash = prefix.rfind('/')
    dot = prefix.find('.', slash + 1)
    if dot < 0:
        return ('', s)
    return (prefix[:dot], prefix[dot+1:] + rest)

STDLIB_TOP = {
 'archive','bufio','bytes','cmp','compress','container','context','crypto','embed','encoding',
 'errors','expvar','flag','fmt','go','hash','html','image','index','internal','io','iter','log',
 'maps','math','mime','net','os','path','plugin','reflect','regexp','runtime','slices','sort',
 'strconv','strings','structs','sync','syscall','testing','text','time','unicode','unsafe',
 'unique','weak','arena','vendor','debug','database','hash','container','crypto','encoding',
 'go','index','log','math','mime','net','os','path','reflect','regexp','runtime','sort','strings',
 'sync','syscall','testing','text','time','unicode','unsafe','bytes','errors','flag','fmt','io',
 'iter','maps','slices','strconv','structs','cmp','embed','expvar','archive','bufio','compress',
 'context','html','image','plugin','unique','weak','arena','weak','syscall','net','os','runtime',
}

def is_stdlib(pkg):
    if not pkg: return False
    top = pkg.split('/')[0]
    return top in STDLIB_TOP

def classify(pkg, first_party_prefixes):
    if pkg in ('go', 'type'): return ('go-meta', False)
    if pkg.startswith('go.shape'): return ('go-shape', False)
    if pkg.startswith('main'): return ('first-party', True)
    for p in first_party_prefixes:
        if pkg == p or pkg.startswith(p + '/'):
            return ('first-party', True)
    if pkg.startswith('vendor/'):
        return ('vendor', False)
    if is_stdlib(pkg):
        return ('stdlib', False)
    if pkg.startswith('github.com/') or pkg.startswith('golang.org/') or pkg.startswith('gopkg.in/') \
       or pkg.startswith('google.golang.org/') or pkg.startswith('go.uber.org/') \
       or pkg.startswith('gvisor.dev/') or pkg.startswith('golang.zx2c4.com/') \
       or pkg.startswith('mvdan.cc/') or pkg.startswith('howett.net/') or pkg.startswith('lukechampine.com/'):
        return ('third-party', False)
    return ('other', False)

def _parse_modinfo_text(payload):
    """Parse Go's text-format module info: 'path\\tX\\nmod\\tY\\tv1.2\\n...' with escaping."""
    out = {}
    raw = payload.replace(b'\\n', b'\n').replace(b'\\t', b'\t')
    lines = raw.split(b'\n')
    deps = []
    for ln in lines:
        if not ln: continue
        f = ln.split(b'\t')
        if f[0] == b'path':
            out['Path'] = f[1].decode('utf-8', 'replace')
        elif f[0] == b'mod':
            out['Main'] = dict(Path=f[1].decode('utf-8', 'replace'),
                               Version=f[2].decode('utf-8', 'replace') if len(f) > 2 else '')
        elif f[0] == b'dep':
            deps.append(dict(Path=f[1].decode('utf-8', 'replace'),
                             Version=f[2].decode('utf-8', 'replace') if len(f) > 2 else ''))
        elif f[0] == b'=>':
            tgt = dict(Path=f[1].decode('utf-8', 'replace'),
                       Version=f[2].decode('utf-8', 'replace') if len(f) > 2 else '')
            if deps: deps[-1]['Replace'] = tgt
            elif 'Main' in out: out['Main']['Replace'] = tgt
        elif f[0] == b'build':
            out.setdefault('Build', []).append(f[1].decode('utf-8', 'replace'))
    if deps: out['Deps'] = deps
    return out

def find_buildinfo(data):
    i = data.find(b'\xff Go buildinf:')
    if i < 0:
        return None
    ptrsize = data[i+14]
    flags = data[i+15]
    mod = None
    # The module-info text sits right after the go version string in this build
    # (flags bit 1 = inline strings). Locate 'path\t<module>' and parse key-tab lines.
    win = data[i+32:i+32+8192]
    j = win.find(b'path\t')
    if j >= 0:
        start = i + 32 + j
        k = start
        while k < len(data):
            b = data[k]
            if b == 0 or b < 0x09 or (b > 0x0a and b < 0x20) or b >= 0x7f:
                break
            k += 1
        txt = data[start:k].decode('utf-8', 'replace')
        mod = _parse_modinfo_text(txt.encode('utf-8'))
        if mod is not None:
            mod['_text_offset'] = '0x%x' % start
            mod['_text_len'] = len(txt)
    # go version string
    gv = None
    m = re.search(rb'go1\.\d+(\.\d+)?', data[i:i+256])
    if m: gv = m.group(0).decode()
    return dict(offset=i, ptrsize=ptrsize, flags=flags, gover=gv, modinfo=mod)

def scan_code(md, funcs_by_entry, text_va, text_end):
    """Return call edges and LEA targets per function."""
    d = md.data
    f_entries = sorted(funcs_by_entry)
    import bisect
    out = []
    stats = dict(calls=0, leas=0)
    for f in funcs_by_entry.values():
        va = f['va']; size = f['size']
        if size <= 0: continue
        off = md.rva2off(va - md.image_base)
        if off is None: continue
        end = min(len(d), off + size)
        calls = []
        leas = []
        i = off
        while i < end - 5:
            b = d[i]
            if b == 0xE8:
                rel = struct.unpack_from('<i', d, i+1)[0]
                nxt = va + (i - off) + 5
                tgt = nxt + rel
                if tgt in funcs_by_entry:
                    calls.append(tgt)
                i += 5
                continue
            if (b == 0x48 or b == 0x4C) and i + 6 < end and d[i+1] == 0x8D and (d[i+2] & 0xC7) == 0x05:
                disp = struct.unpack_from('<i', d, i+3)[0]
                nxt = va + (i - off) + 7
                tgt = nxt + disp
                off_t = md.rva2off(tgt - md.image_base) if md.image_base <= tgt < md.image_base + md.size_of_image else None
                if off_t is not None:
                    leas.append(tgt)
                i += 7
                continue
            i += 1
        stats['calls'] += len(calls)
        stats['leas'] += len(leas)
        out.append(dict(func=f['name'], entry=va, calls=calls, leas=leas))
    return out, stats

def printable_runs(data, start, end, minlen=4):
    """Yield (offset, bytes) printable ASCII runs."""
    out = []
    i = start
    while i < end:
        b = data[i]
        if 0x20 <= b < 0x7f:
            j = i
            while j < end and 0x20 <= data[j] < 0x7f:
                j += 1
            if j - i >= minlen:
                out.append((i, data[i:j]))
            i = j
        else:
            i += 1
    return out

def main():
    path, outjson = sys.argv[1], sys.argv[2]
    md = PE(path)
    data = md.data
    best, data_, cands = gopcln.parse(path, verbose=False)
    textStart = best['textStart']
    funcs = best['funcs']
    base = md.image_base
    fmap = {}
    for f in funcs:
        va = textStart + f['entryoff']
        f['va'] = va
        fmap[va] = f
    # first-party detection from modinfo path
    bi = find_buildinfo(data)
    prefixes = set()
    if bi and bi.get('modinfo'):
        p = bi['modinfo'].get('Path', '')
        main = (bi['modinfo'].get('Main') or {}).get('Path')
        if p:
            prefixes.add(p)
        if main and main != '(devel)':
            prefixes.add(main)
        # replace directives pointing at local relative dirs are first-party builds too
        # (e.g. win-httpproxy) -- only add if the resolved Path looks like the same org
        for d in (bi['modinfo'].get('Deps') or []):
            r = d.get('Replace') or {}
            rp = r.get('Path', '')
            if rp.startswith('github.com/anthropics/'):
                prefixes.add(rp)
    # normalise: module root only
    prefixes = {x.rstrip('/') for x in prefixes if x}
    calls, stats = scan_code(md, fmap, 0, 0)
    # string index: map VA -> containing printable run
    runs = []
    for s in md.sections:
        if s['name'] in ('.rdata', '.data', '.text', '.rodata'):
            runs.extend(printable_runs(data, s['rawptr'], s['rawptr'] + s['rawsize'], minlen=4))
    # build sorted list of run VAs
    run_va = []
    for off, b in runs:
        rva = md.off2rva(off)
        if rva is None: continue
        run_va.append((base + rva, b))
    run_va.sort()
    run_starts = [r[0] for r in run_va]
    import bisect
    def lookup(tgt):
        i = bisect.bisect_right(run_starts, tgt) - 1
        if i < 0: return None
        sva, sb = run_va[i]
        if tgt < sva + len(sb):
            return (sva, sb, tgt - sva)
        return None
    # attach string refs
    for fc in calls:
        refs = []
        for tgt in fc['leas']:
            r = lookup(tgt)
            if r:
                refs.append((tgt, r[1].decode('latin1'), r[2]))
        fc['strrefs'] = refs
        fc.pop('leas', None)
    out = dict(
        binary=os.path.basename(path),
        path=path,
        size=len(data),
        image_base=base,
        pclntab=dict(offset=best['offset'], magic=best['magic'], version=best['version'],
                     nfunc=best['nfunc'], nfiles=best['nfiles'], textStart=textStart,
                     candidates=[('0x%x' % c[0], gopcln.MAGICS[c[1]]) for c in cands]),
        buildinfo=bi,
        first_party_prefixes=sorted(prefixes),
        sections=md.sections_summary(),
        funcs=[dict(index=f['index'], name=f['name'], entryoff=f['entryoff'],
                    entry_va=f['va'], entry_hex='0x%x' % f['va'], size=f['size']) for f in funcs],
        code=dict(stats=stats, funcs=calls),
    )
    with open(outjson, 'w', encoding='utf-8') as fo:
        json.dump(out, fo)
    print('wrote', outjson, 'funcs', len(funcs), 'calls', stats['calls'], 'leas', stats['leas'])

if __name__ == '__main__':
    main()
