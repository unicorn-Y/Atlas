"""Enumerate Go string constants by scanning .rdata for {ptr,len} headers.

Go emits each string literal as a 16-byte (ptr,len) pair in .rdata/.data.
We scan every 8-byte-aligned offset, validate ptr->image and len, and
dedupe on the target data address.
"""
import sys, os, json, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE

def enumerate_strings(md, minlen=1, maxlen=1 << 20):
    d = md.data
    base = md.image_base
    img_lo, img_hi = base, base + md.size_of_image
    found = {}
    for s in md.sections:
        if s['name'] not in ('.rdata', '.data', '.rodata'):
            continue
        lo = s['rawptr']
        hi = s['rawptr'] + s['rawsize'] - 16
        # align to 8
        i = lo + ((8 - (lo % 8)) % 8)
        while i <= hi:
            ptr, ln = struct.unpack_from('<QQ', d, i)
            if 0 < ln < maxlen and img_lo <= ptr < img_hi:
                doff = md.rva2off(ptr - base)
                if doff is not None and doff + ln <= len(d):
                    raw = d[doff:doff+ln]
                    ok = True
                    for c in raw:
                        if c < 0x09 or (0x0d < c < 0x20) or c == 0x7f:
                            ok = False
                            break
                    if ok and ln >= minlen:
                        try:
                            txt = raw.decode('utf-8')
                        except UnicodeDecodeError:
                            txt = raw.decode('latin1')
                        if ptr not in found or found[ptr][0] != txt:
                            found.setdefault(ptr, (txt, ln, i))
            i += 8
    return found

if __name__ == '__main__':
    path = sys.argv[1]
    md = PE(path)
    sm = enumerate_strings(md, minlen=2)
    print('strings:', len(sm))
    for ptr, (t, ln, hdr) in sorted(sm.items()):
        if ln >= 20:
            print('data 0x%x hdr 0x%x len %d %r' % (ptr, hdr, ln, t[:120]))
