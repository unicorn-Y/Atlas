"""Minimal PE parsing helpers (no external deps)."""
import struct

class PE:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            self.data = f.read()
        self._parse_headers()

    def _u16(self, off): return struct.unpack_from('<H', self.data, off)[0]
    def _u32(self, off): return struct.unpack_from('<I', self.data, off)[0]
    def _u64(self, off): return struct.unpack_from('<Q', self.data, off)[0]

    def _parse_headers(self):
        d = self.data
        if d[:2] != b'MZ':
            raise ValueError('not MZ')
        e_lfanew = self._u32(0x3C)
        if d[e_lfanew:e_lfanew+4] != b'PE\0\0':
            raise ValueError('not PE')
        self.coff_off = e_lfanew + 4
        self.machine = self._u16(self.coff_off)
        self.nsections = self._u16(self.coff_off + 2)
        self.timestamp = self._u32(self.coff_off + 4)
        self.opt_size = self._u16(self.coff_off + 16)
        self.characteristics = self._u16(self.coff_off + 18)
        self.opt_off = self.coff_off + 20
        self.magic = self._u16(self.opt_off)
        self.is64 = (self.magic == 0x20b)
        # data directories
        if self.is64:
            self.image_base = self._u64(self.opt_off + 24)
            self.dd_off = self.opt_off + 112
            self.entry_rva = self._u32(self.opt_off + 16)
            self.size_of_image = self._u32(self.opt_off + 56)
        else:
            self.image_base = self._u32(self.opt_off + 28)
            self.dd_off = self.opt_off + 96
            self.entry_rva = self._u32(self.opt_off + 16)
            self.size_of_image = self._u32(self.opt_off + 56)
        self.ndirs = self._u32(self.dd_off - 4) if self.opt_size >= 4 else 0
        # sections
        self.sections = []
        sec_off = self.opt_off + self.opt_size
        for i in range(self.nsections):
            o = sec_off + i * 40
            name = d[o:o+8].rstrip(b'\0').decode('latin1')
            vsize = self._u32(o + 8)
            va = self._u32(o + 12)
            rawsize = self._u32(o + 16)
            rawptr = self._u32(o + 20)
            chars = self._u32(o + 36)
            self.sections.append(dict(name=name, vsize=vsize, va=va,
                                      rawsize=rawsize, rawptr=rawptr, chars=chars))
        # header span (used for RVA mapping of header data)
        self.header_size = self._u32(self.opt_off + 60) if self.opt_size >= 64 else 0

    def dir(self, idx):
        o = self.dd_off + idx * 8
        if o + 8 > self.dd_off + self.opt_size:
            return (0, 0)
        return (self._u32(o), self._u32(o + 4))

    def rva2off(self, rva):
        for s in self.sections:
            span = max(s['vsize'], s['rawsize'])
            if s['va'] <= rva < s['va'] + span:
                delta = rva - s['va']
                if delta < s['rawsize']:
                    return s['rawptr'] + delta
                return None
        if rva < self.header_size:
            return rva
        return None

    def off2rva(self, off):
        for s in self.sections:
            if s['rawptr'] <= off < s['rawptr'] + s['rawsize']:
                return s['va'] + (off - s['rawptr'])
        if off < self.header_size:
            return off
        return None

    def cstr(self, rva):
        o = self.rva2off(rva)
        if o is None: return None
        e = self.data.find(b'\0', o)
        if e < 0: return None
        return self.data[o:e].decode('latin1')

    # ---- imports ----
    def imports(self):
        """Return list of (dll, [func names or ordinals])"""
        va, size = self.dir(1)
        if not va: return []
        out = []
        o = self.rva2off(va)
        while True:
            ent = self.data[o:o+20]
            if len(ent) < 20 or ent == b'\0'*20: break
            ilt, ts, fwd, name_rva, iat = struct.unpack('<IIIII', ent)
            dll = self.cstr(name_rva) or '?'
            thunk_rva = ilt or iat
            funcs = []
            to = self.rva2off(thunk_rva)
            step = 8 if self.is64 else 4
            while True:
                if self.is64:
                    v = self._u64(to)
                else:
                    v = self._u32(to)
                if v == 0: break
                if v & (1 << (63 if self.is64 else 31)):
                    funcs.append('#%d' % (v & 0xFFFF))
                else:
                    hn = self.rva2off(v & 0x7FFFFFFF)
                    if hn is not None:
                        s = self.data[hn+2:self.data.find(b'\0', hn+2)]
                        funcs.append(s.decode('latin1'))
                    else:
                        funcs.append('?')
                to += step
            out.append((dll, funcs))
            o += 20
        return out

    # ---- exports ----
    def exports(self):
        va, size = self.dir(0)
        if not va: return []
        o = self.rva2off(va)
        d = self.data
        nfuncs = self._u32(o + 20)
        nnames = self._u32(o + 24)
        funcs_rva = self._u32(o + 28)
        names_rva = self._u32(o + 32)
        ords_rva = self._u32(o + 36)
        out = []
        fo = self.rva2off(funcs_rva)
        no = self.rva2off(names_rva)
        oo = self.rva2off(ords_rva)
        for i in range(nnames):
            nr = self._u32(no + i*4)
            name = self.cstr(nr)
            ordi = struct.unpack_from('<H', d, oo + i*2)[0]
            fr = self._u32(fo + ordi*4)
            out.append((name, ordi, fr))
        return out

    def sections_summary(self):
        return [(s['name'], s['va'], s['vsize'], s['rawptr'], s['rawsize']) for s in self.sections]
