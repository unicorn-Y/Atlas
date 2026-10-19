"""Reconstruct inlined Go string comparisons from x86-64 code.

Go compiles `s == "literal"` / `switch s { case "a": ... }` into:

    cmp  rdx, 9                        ; length compare
    jne  next
    movabs rcx, 0x6e696e6e75527369     ; "isRunnin"
    cmp  qword ptr [r8], rcx
    jne  next
    cmp  byte ptr [r8 + 8], 0x67       ; 'g'
    jne  next
    <case body>

This module rebuilds the literal bytes and pairs them with the fallthrough
call target (the handler), giving a concrete method-dispatch table.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capstone import Cs, CS_ARCH_X86, CS_MODE_64
from capstone.x86 import X86_OP_IMM, X86_OP_MEM, X86_OP_REG

_cs = Cs(CS_ARCH_X86, CS_MODE_64)
_cs.detail = True

def disasm(pe, va, size):
    off = pe.rva2off(va - pe.image_base)
    if off is None: return []
    return list(_cs.disasm(pe.data[off:off+size], va))

def _imm_bytes(v, n):
    return (v & ((1 << (8*n)) - 1)).to_bytes(n, 'little')

def _is_mem(op):
    return op.type == 3

def _is_imm(op):
    return op.type == 2

def _is_reg(op):
    return op.type == 1

def reconstruct(insns, minlen=3, maxlen=260):
    """Return list of dicts {va, text, length, body_va, body_calls, cond_va}."""
    out = []
    n = len(insns)
    i = 0
    while i < n:
        ins = insns[i]
        # Detect a chain: (movabs reg,imm64 | mov reg,imm) cmp [mem(+off)], imm/reg
        chunks = {}   # offset -> bytes
        base = None
        cond_va = None
        j = i
        pending_reg_imm = None
        while j < n:
            ii = insns[j]
            mn = ii.mnemonic
            if mn in ('nop', 'int3', 'endbr64'):
                j += 1; continue
            if mn == 'movabs' and len(ii.operands) == 2 and _is_imm(ii.operands[1]):
                pending_reg_imm = (ii.operands[1].imm, 8)
                j += 1; continue
            if mn == 'mov' and ii.op_count == 2 and ii.operands[0].type == X86_OP_REG \
               and ii.operands[1].type == X86_OP_IMM:
                pending_reg_imm = (ii.operands[1].imm, ii.operands[1].size)
                j += 1; continue
            if mn == 'cmp' and len(ii.operands) == 2 and _is_mem(ii.operands[0]):
                m = ii.operands[0].mem
                if m.base == 0 and m.index == 0:
                    # absolute/rip-relative; not an inline string compare
                    pending_reg_imm = None; break
                off = m.disp
                if _is_imm(ii.operands[1]):
                    val, w = ii.operands[1].imm, ii.operands[1].size
                elif _is_reg(ii.operands[1]) and pending_reg_imm:
                    val, w = pending_reg_imm
                else:
                    break
                pending_reg_imm = None
                if base is None:
                    base = off
                    cond_va = ii.address
                chunks[off] = _imm_bytes(val, w)
                j += 1
                continue
            break
        if len(chunks) >= 1 and base is not None:
            lo = min(chunks)
            hi = max(chunks[o] and o + len(chunks[o]) for o in chunks)
            total = hi - base
            if minlen <= total <= maxlen:
                buf = bytearray(total)
                seen = bytearray(total)
                ok = True
                for off in chunks:
                    idx = off - base
                    b = chunks[off]
                    buf[idx:idx+len(b)] = b
                    for q in range(idx, idx+len(b)): seen[q] = 1
                if all(seen) and all(32 <= c < 127 for c in buf):
                    # walk forward to the case body: first call after the last jne
                    k = j
                    body_calls = []
                    while k < n and k < j + 40:
                        kk = insns[k]
                        if kk.mnemonic == 'call' and len(kk.operands) == 1 and _is_imm(kk.operands[0]):
                            body_calls.append((kk.address, kk.operands[0].imm))
                            if len(body_calls) >= 2: break
                        if kk.mnemonic == 'ret':
                            break
                        k += 1
                    out.append(dict(va=cond_va, text=buf.decode('ascii'),
                                    length=total,
                                    body_calls=body_calls))
            i = max(j, i + 1)
            continue
        i += 1
    return out

def direct_calls(insns):
    out = []
    for ins in insns:
        if ins.mnemonic == 'call' and len(ins.operands) == 1 and _is_imm(ins.operands[0]):
            out.append((ins.address, ins.operands[0].imm))
    return out

def switch_strings(insns):
    """Find Go's string-switch: cmp reg,imm(len); jne; then per-case compare chains."""
    return reconstruct(insns)
