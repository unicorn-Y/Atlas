"""Go pclntab parser (go1.18 - go1.25 functab format).

Layout (go1.20+, magic 0xfffffff1):
  header:
    magic   u32
    pad1    u8
    pad2    u8
    minLC   u8
    ptrSize u8
    nfunc   uintptr
    nfiles  uintptr
    textStart   uintptr
    funcnameOffset uintptr
    cuOffset       uintptr
    filetabOffset  uintptr
    pctabOffset    uintptr
    pclnOffset     uintptr
  funcnametab at magic+funcnameOffset (NUL-separated names)
  pclntab     at magic+pclnOffset: (nfunc+1) functab{entryoff u32, funcoff u32}
  _func structs at pclntab+funcoff (44 bytes, go1.20+)
"""
import struct, sys, os, json

MAGICS = {
    0xfffffff1: 'go1.20+',
    0xfffffff0: 'go1.18/1.19',
    0xfffffffa: 'go1.16/1.17',
    0xfffffffb: 'go1.2-1.15',
}

def find_candidates(data):
    out = []
    for magic in MAGICS:
        pat = struct.pack('<I', magic)
        start = 0
        while True:
            i = data.find(pat, start)
            if i < 0: break
            start = i + 1
            # sanity: pad1/pad2 must be 0, minLC 1..4, ptrSize 4 or 8
            if i + 8 > len(data): continue
            pad1, pad2, minlc, ptrsize = data[i+4], data[i+5], data[i+6], data[i+7]
            if pad1 != 0 or pad2 != 0: continue
            if minlc not in (1, 2, 4): continue
            if ptrsize not in (4, 8): continue
            out.append((i, magic))
    return out

def parse(path, verbose=True):
    with open(path, 'rb') as f:
        data = f.read()
    cands = find_candidates(data)
    best = None
    results = []
    for off, magic in cands:
        try:
            r = parse_at(data, off, magic)
        except Exception as e:
            if verbose:
                print('  cand 0x%x (%s) failed: %s' % (off, MAGICS[magic], e), file=sys.stderr)
            continue
        results.append(r)
        if best is None or r['nfunc'] > best['nfunc']:
            best = r
    if best is None:
        raise RuntimeError('no pclntab found')
    return best, data, cands

def parse_at(data, off, magic):
    # header fields are uintptr-sized; determine ptr size
    ptr = data[off+7]
    hs = 8 + 3*ptr  # magic+4 bytes, then nfunc,nfiles,textStart =3 ptrs
    fields = {}
    names = ['nfunc','nfiles','textStart','funcnameOffset','cuOffset','filetabOffset','pctabOffset','pclnOffset']
    # 8 ptr-sized fields after the 8-byte prefix
    for i, nm in enumerate(names):
        p = off + 8 + i*ptr
        if ptr == 8:
            fields[nm] = struct.unpack_from('<Q', data, p)[0]
        else:
            fields[nm] = struct.unpack_from('<I', data, p)[0]
    nfunc = fields['nfunc']
    # sanity check
    if nfunc <= 0 or nfunc > 5_000_000:
        raise ValueError('bad nfunc %d' % nfunc)
    funcnames_off = off + fields['funcnameOffset']
    pcln_off = off + fields['pclnOffset']
    if pcln_off + (nfunc+1)*8 > len(data):
        raise ValueError('pclntab out of range')
    entries = []
    for i in range(nfunc+1):
        eo, fo = struct.unpack_from('<II', data, pcln_off + i*8)
        entries.append((eo, fo))
    funcnames = data
    funcs = []
    for i in range(nfunc):
        eo, fo = entries[i]
        end_eo = entries[i+1][0]
        fo_abs = pcln_off + fo
        if fo_abs + 20 > len(data):
            funcs.append(dict(index=i, entryoff=eo, size=end_eo-eo, name='<bad funcoff>', nameoff=-1))
            continue
        entryOff, nameOff = struct.unpack_from('<Ii', data, fo_abs)
        # _func.entryOff should equal eo
        no = funcnames_off + nameOff
        e = data.find(b'\0', no)
        nm = data[no:e].decode('utf-8', 'replace') if e > 0 else '<bad name>'
        funcs.append(dict(index=i, entryoff=eo, size=end_eo-eo, name=nm,
                          nameoff=nameOff, funcoff=fo,
                          entryoff_field=entryOff))
    return dict(offset=off, magic='0x%08x' % magic, version=MAGICS[magic],
                nfunc=nfunc, nfiles=fields['nfiles'],
                textStart=fields['textStart'], funcnameOffset=fields['funcnameOffset'],
                pclnOffset=fields['pclnOffset'], funcs=funcs,
                fields=fields, ptr=ptr)

if __name__ == '__main__':
    p = sys.argv[1]
    best, data, cands = parse(p)
    print('file', p, 'size', len(data))
    print('candidates:', [('0x%x' % c[0], MAGICS[c[1]]) for c in cands])
    print('chosen offset 0x%x version %s nfunc %d nfiles %d textStart 0x%x' % (
        best['offset'], best['version'], best['nfunc'], best['nfiles'], best['textStart']))
    print('first 5:', [f['name'] for f in best['funcs'][:5]])
    print('last 5:', [f['name'] for f in best['funcs'][-5:]])
