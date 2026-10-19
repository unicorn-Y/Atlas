"""Recover Go struct field names + json tags from runtime type metadata.

moduledata (go1.20..1.25, amd64) relevant offsets:
  +0x128 types       (base for typelinks / nameOff)
  +0x130 etypes
  +0x160 typelinks   []int32  (offsets relative to types)
  +0x178 itablinks   []*itab

rtype (48 bytes):
  +0x00 size, +0x08 ptrdata, +0x10 hash(u32), +0x14 tflag, +0x15 align,
  +0x16 fieldAlign, +0x17 kind, +0x18 equal, +0x20 gcdata, +0x28 str(int32),
  +0x2c ptrToThis(int32)

structtype adds:
  +0x30 pkgPath(int32), +0x34 pad, +0x38 fields.ptr, +0x40 fields.len,
  +0x48 fields.cap
structfield (16 bytes): name int32, typ int32, offset uintptr
"""
import sys, os, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE

KIND_STRUCT = 25

NAME_BASE_ADJUST = 1   # empirically types+1 for these builds

def parse_name(d, types_off, off):
    o = types_off + NAME_BASE_ADJUST + off
    if o < 0 or o + 1 >= len(d): return None
    flags = d[o]
    l = flags >> 1
    p = o + 1
    if flags & 1:
        if p >= len(d): return None
        l = (flags >> 1) | (d[p] << 7)
        p += 1
    if l == 0 or l > 400 or p + l > len(d): return None
    nb = d[p:p+l]
    if not all(32 <= c < 127 for c in nb): return None
    p += l
    tag = None
    if flags & 2:
        if p >= len(d): return None
        tl = d[p]; q = p + 1
        if tl & 0x80:
            if q >= len(d): return None
            tl = (tl & 0x7f) | (d[q] << 7); q += 1
        if q + tl > len(d): return None
        tag = d[q:q+tl].decode('latin1'); p = q + tl
    return nb.decode('ascii'), tag, p

def find_moduledata(md, pchdr_va):
    d = md.data
    pat = struct.pack('<Q', pchdr_va)
    i = d.find(pat)
    while i >= 0:
        if i % 8 == 0:
            types = struct.unpack_from('<Q', d, i + 0x128)[0]
            etypes = struct.unpack_from('<Q', d, i + 0x130)[0]
            tl_ptr = struct.unpack_from('<Q', d, i + 0x160)[0]
            tl_len = struct.unpack_from('<Q', d, i + 0x168)[0]
            if (md.image_base <= types < md.image_base + md.size_of_image
                    and etypes > types and 0 < tl_len < 2_000_000
                    and md.image_base <= tl_ptr < md.image_base + md.size_of_image):
                return dict(off=i, types=types, etypes=etypes, tl_ptr=tl_ptr, tl_len=tl_len)
        i = d.find(pat, i + 1)
    return None

def parse_all_structs(md, mdm):
    d = md.data
    base = md.image_base
    types_va = mdm['types']
    types_off = md.rva2off(types_va - base)
    tl_off = md.rva2off(mdm['tl_ptr'] - base)
    out = []
    for k in range(mdm['tl_len']):
        rel = struct.unpack_from('<i', d, tl_off + k * 4)[0]
        st_va = types_va + rel
        off = md.rva2off(st_va - base)
        if off is None or off + 0x50 > len(d): continue
        kind = d[off + 0x17] & 0x1f
        if kind != KIND_STRUCT: continue
        nameoff = struct.unpack_from('<i', d, off + 0x28)[0]
        nm = parse_name(d, types_off, nameoff)
        fptr = struct.unpack_from('<Q', d, off + 0x38)[0]
        flen = struct.unpack_from('<Q', d, off + 0x40)[0]
        if flen > 300: continue
        fo = md.rva2off(fptr - base)
        if fo is None or fo + flen * 16 > len(d): continue
        fields = []
        for j in range(flen):
            noff, toff, offset = struct.unpack_from('<iiQ', d, fo + j * 16)
            if not (0 < noff < 8_000_000):
                continue
            r = parse_name(d, types_off, noff)
            if not r: continue
            fields.append(dict(name=r[0], tag=r[1], offset=offset))
        out.append(dict(type_va='0x%x' % st_va, name=(nm[0] if nm else '?'), fields=fields))
    return out

if __name__ == '__main__':
    import gopcln, json
    md = PE(sys.argv[1])
    best, _, _ = gopcln.parse(md.path, verbose=False)
    pchdr = md.image_base + md.off2rva(best['offset'])
    mdm = find_moduledata(md, pchdr)
    print('moduledata', {k: hex(v) for k, v in mdm.items()})
    ss = parse_all_structs(md, mdm)
    print('structs', len(ss))
    for s in ss:
        if s['name'] in ('pipe.Request', 'pipe.Response', 'pipe.ConfigureParams', 'vm.Message'):
            print(s['name'], [(f['name'], f['tag']) for f in s['fields']])
