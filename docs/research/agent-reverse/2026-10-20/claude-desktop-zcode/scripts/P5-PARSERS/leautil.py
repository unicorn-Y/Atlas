"""Helper: resolve LEA immediate strings (raw bytes + explicit length in code)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

_cs = Cs(CS_ARCH_X86, CS_MODE_64)
_cs.detail = True

def lea_target(ins):
    """Return absolute target of lea reg,[rip+disp] else None."""
    if ins.mnemonic != 'lea' or len(ins.operands) != 2:
        return None
    m = ins.operands[1]
    if m.type != 3:
        return None
    if m.mem.base == 0:
        return None
    # rip-relative: disp is relative to end of instruction; capstone may already
    # encode as rip base name; recompute robustly
    return ins.address + ins.size + m.mem.disp

def read_at(pe, va, length):
    off = pe.rva2off(va - pe.image_base)
    if off is None:
        return None
    return pe.data[off:off+length]

def fmt_string(pe, va, length):
    b = read_at(pe, va, length)
    if b is None:
        return None
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return b.decode('latin1')
