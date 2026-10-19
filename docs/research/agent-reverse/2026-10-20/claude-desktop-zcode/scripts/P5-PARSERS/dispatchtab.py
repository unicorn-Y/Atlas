"""Extract Go string-switch dispatch tables.

A Go string switch compiles to:

    cmp  LEN, k                      ; per-case length check
    jne  <next_case>
    movabs reg, <first 8 bytes>
    cmp  [strptr+0], reg
    jne  <next_case>
    cmp  [strptr+8], imm             ; remaining bytes
    jne  <next_case>
    <case body: call handler>

Two compare chunks belong to the same literal only when they are *instruction
adjacent* (separated at most by the guard `jne`). We merge on that adjacency,
never on jne equality (the last case shares the global no-match target).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import inlinestr
from peutil import PE

def _imm_bytes(v, n):
    return (v & ((1 << (8*n)) - 1)).to_bytes(n, 'little')

MAX_JNE_BYTES = 16

def switch_table(pe, va, size, minlen=3, maxlen=80):
    insns = inlinestr.disasm(pe, va, size)
    n = len(insns)
    cases = []
    i = 0
    while i < n:
        chunks = []          # list of (off, bytes, cmp_addr, cmp_end)
        base = None
        cond_va = None
        j = i
        pending = None
        while j < n:
            ii = insns[j]
            mn = ii.mnemonic
            if mn in ('nop', 'int3'):
                j += 1; continue
            if mn == 'movabs' and len(ii.operands) == 2 and ii.operands[1].type == 2:
                pending = (ii.operands[1].imm, 8); j += 1; continue
            if mn == 'mov' and len(ii.operands) == 2 and ii.operands[0].type == 1 \
               and ii.operands[1].type == 2:
                pending = (ii.operands[1].imm, ii.operands[1].size); j += 1; continue
            if mn == 'cmp' and len(ii.operands) == 2 and ii.operands[0].type == 3:
                m = ii.operands[0].mem
                if m.base == 0:
                    pending = None; break
                off = m.disp
                if ii.operands[1].type == 2:
                    val, w = ii.operands[1].imm, ii.operands[1].size
                elif ii.operands[1].type == 1 and pending:
                    val, w = pending
                else:
                    break
                pending = None
                if base is None:
                    base = off; cond_va = ii.address
                chunks.append((off, _imm_bytes(val, w), ii.address, ii.address + ii.size))
                j += 1
                continue
            if mn == 'jne':
                j += 1; continue
            break
        if chunks and base is not None:
            # merge only adjacent chunks
            groups = []
            for c in chunks:
                if groups and c[2] - groups[-1][-1][3] <= MAX_JNE_BYTES:
                    groups[-1].append(c)
                else:
                    groups.append([c])
            for g in groups:
                lo = min(x[0] for x in g); hi = max(x[0] + len(x[1]) for x in g)
                total = hi - base
                if not (minlen <= total <= maxlen):
                    continue
                buf = bytearray(total); seen = bytearray(total); ok = True
                for off, b, a, e in g:
                    idx = off - base
                    if idx < 0 or idx + len(b) > total: ok = False; break
                    buf[idx:idx+len(b)] = b
                    for q in range(idx, idx + len(b)): seen[q] = 1
                if not ok or not all(seen) or not all(32 <= c < 127 for c in buf):
                    continue
                # body call: first direct call after the group's last jne
                k = j
                calls = []
                while k < n and k < j + 80:
                    kk = insns[k]
                    if kk.mnemonic == 'call' and len(kk.operands) == 1 and kk.operands[0].type == 2:
                        calls.append((kk.address, kk.operands[0].imm)); break
                    if kk.mnemonic == 'ret': break
                    k += 1
                cases.append(dict(va=g[0][2], text=buf.decode('ascii'), length=total,
                                  body_calls=calls))
            i = max(j, i + 1); continue
        i += 1
    return cases

if __name__ == '__main__':
    md = PE(sys.argv[1])
    va = int(sys.argv[2], 16); size = int(sys.argv[3], 16)
    for d in switch_table(md, va, size):
        print('0x%x len=%-3d %-32r calls=%s' % (d['va'], d['length'], d['text'],
                                                [hex(c[1]) for c in d['body_calls']]))
