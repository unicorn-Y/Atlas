"""Extract all LEA-referenced string literals from Go functions, with attribution.

Go 1.20+ places literal *bytes* in .rdata and materialises them via
`lea reg,[rip+X]; mov ecx, LEN`. We resolve both to recover the exact literal
and the function that owns it.
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE
import inlinestr
import leautil

def extract_func_strings(pe, va, size, minlen=4, maxlen=2048):
    if size <= 0: return []
    ins = inlinestr.disasm(pe, va, size)
    out = []
    for i, a in enumerate(ins):
        t = leautil.lea_target(a)
        if t is None: continue
        ln = None
        for k in range(i + 1, min(i + 7, len(ins))):
            ii = ins[k]
            if ii.mnemonic == 'mov' and len(ii.operands) == 2 and ii.operands[0].type == 1 \
               and ii.operands[1].type == 2 and ii.operands[0].size in (4, 8):
                v = ii.operands[1].imm
                if minlen <= v <= maxlen:
                    ln = v
                    break
        if ln is None: continue
        s = leautil.fmt_string(pe, t, ln)
        if s is None: continue
        if not all(9 <= ord(c) < 127 for c in s): continue
        out.append((a.address, t, ln, s))
    return out

def extract_all(pe, funcs):
    res = []
    for f in funcs:
        if f['size'] <= 0: continue
        for addr, tgt, ln, s in extract_func_strings(pe, f['entry_va'], f['size']):
            res.append(dict(func=f['name'], func_entry='0x%x' % f['entry_va'],
                            insn='0x%x' % addr, data_va='0x%x' % tgt,
                            length=ln, text=s))
    return res

if __name__ == '__main__':
    path, js = sys.argv[1], sys.argv[2]
    md = PE(path)
    j = json.load(open(js, encoding='utf-8'))
    r = extract_all(md, j['funcs'])
    print(json.dumps(r[:20], indent=1))
    print('total', len(r))
