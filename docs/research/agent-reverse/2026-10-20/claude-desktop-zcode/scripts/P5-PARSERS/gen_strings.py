"""Generate SVC-STRINGS.tsv from real literals plus exact-token extraction.

Priority of sources:
  1. funstrings.extract_all()          exact LEA + MOV(LEN) literals, function-attributed
  2. stringenum.enumerate_strings()    go:string {ptr,len} header constants
  3. exact-token scans for closed vocabularies (HCS/HCN API names, DLL names)
     so pooled-blob neighbours never leak into a value.

Output columns: binary, category, value, count, evidence
  evidence = "<source>@<file offset or VA>" of the best occurrence found.
"""
import sys, os, json, re, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from peutil import PE
import funstrings
import stringenum

RES = r'D:\Atlas\_research\claude-desktop\2026-10-20\extract\app\resources'
IDX = r'D:\Atlas\_research\claude-desktop\2026-10-20\index\work-P5'
BINARIES = ['cowork-svc', 'claude-ssh-broker', 'claude-ssh-proxy', 'claude-ssh-askpass']

# Closed vocabulary: the HCS/HCN entry points the code actually resolves.
HCS_NAMES = [
 'HcsCreateComputeSystem','HcsOpenComputeSystem','HcsCloseComputeSystem',
 'HcsStartComputeSystem','HcsShutdownComputeSystem','HcsShutDownComputeSystem',
 'HcsTerminateComputeSystem','HcsModifyComputeSystem','HcsGetComputeSystemProperties',
 'HcsGetServiceProperties','HcsEnumerateComputeSystems','HcsCreateOperation',
 'HcsCloseOperation','HcsGetOperationResult','HcsWaitForOperationResult',
 'HcnEnumerateNetworks','HcnOpenNetwork','HcnCloseNetwork','HcnDeleteNetwork',
 'HcnQueryNetworkProperties','HcnCreateNetwork',
]
DLL_NAMES = ['kernel32.dll','vmcompute.dll','computecore.dll','computenetwork.dll',
             'virtdisk.dll','user32.dll','advapi32.dll','ole32.dll','oleaut32.dll',
             'shell32.dll','ntdll.dll','crypt32.dll','bcryptprimitives.dll',
             'api-ms-win-core-winrt-l1-1-0.dll','api-ms-win-shcore-scaling-l1-1-1.dll',
             'api-ms-win-core-synch-l1-2-0.dll','dwmapi.dll','powrprof.dll',
             'iphlpapi.dll','gdi32.dll','shlwapi.dll','mpr.dll','ncrypt.dll',
             'userenv.dll','propsys.dll','ws2_32.dll','dbghelp.dll','winhttp.dll',
             'wininet.dll','netapi32.dll','wtsapi32.dll','psapi.dll','setupapi.dll']
PIPE_NAMES = ['\\\\.\\pipe\\cowork-vm-service', '\\\\.\\pipe\\cowork-vm-service-store',
              '\\\\.\\pipe\\cowork-daemon-console', '\\\\.\\pipe\\cowork-daemon-console-store']
ENV_NAMES = ['GODEBUG','GOMAXPROCS','GOTRACEBACK','GOMEMLIMIT','GOTOOLCHAIN',
             'CLAUDE_SSH_ASKPASS_BROKER','CLAUDE_SSH_ASKPASS_RELAY',
             'SSH_ASKPASS','SSH_ASKPASS_PROMPT','SSH_ASKPASS_REQUIRE',
             'SSH_ASKPASS_BROKER','SSH_ASKPASS_RELAY','WINDIR','SYSTEMROOT',
             'USERPROFILE','LOCALAPPDATA','APPDATA','PROGRAMDATA','SystemDrive',
             'http_proxy','https_proxy','no_proxy','HTTP_PROXY','HTTPS_PROXY','NO_PROXY']
REG_NAMES = [
 'SOFTWARE\\Policies\\Claude',
 'SOFTWARE\\Policies\\Claude\\coworkEDRIntegration',
 'SOFTWARE\\Policies\\Claude\\coworkEDRIntegrationVendor',
 'Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings',
 'SYSTEM\\CurrentControlSet\\Services\\EventLog\\Application',
 'SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\ProfileList\\ssh',
]
PATH_NAMES = [
 'C:\\ProgramData\\Claude\\Logs',
 'C:\\ProgramData\\Claude\\Logs\\cowork-service.log',
 'C:\\ProgramData\\Claude\\Logs\\cowork-service-store.log',
 'C:\\ProgramData\\Claude\\Logs\\coworkd',
 'C:\\ProgramData\\Claude\\Logs\\coworkd-store',
 '\\\\.\\UNC',
]
URL_NAMES = ['https://go.dev/issue/66821', 'https://go.dev/pkg/crypto/rsa']

ERROR_HINTS = ('failed','error','invalid','cannot','refus','denied','not found',
               'timeout','unable','too large','unknown','not configured',
               'not initialized','not available','not signed','not installed',
               'not running','mismatch','panic','dropped','exceeded','aborted',
               'unexpected','malformed','desynchron','desync')

def find_evidence(d, needle_bytes):
    off = d.find(needle_bytes)
    return off

def classify(v):
    if v in PIPE_NAMES or re.fullmatch(r'\\\\[.?]\\pipe\\[A-Za-z0-9_.-]{3,60}', v):
        return 'pipe_name'
    if v in HCS_NAMES:
        return 'hcs_api'
    if re.fullmatch(r'[A-Za-z0-9_.-]+\.dll', v, re.I):
        return 'dll'
    if v.startswith('json:"'):
        return 'json_tag'
    if v in REG_NAMES or v.startswith(('SOFTWARE\\','SYSTEM\\','HKEY_')):
        return 'registry'
    if v in ENV_NAMES:
        return 'env_var'
    if v in URL_NAMES or re.match(r'^https?://', v):
        return 'url'
    if v in PATH_NAMES or re.match(r'^[A-Za-z]:\\', v) or v.startswith('\\\\'):
        return 'file_path'
    low = v.lower()
    if any(h in low for h in ERROR_HINTS) and len(v) >= 10 and ' ' in v:
        return 'error_message'
    if '%w' in v and len(v) >= 12:
        return 'error_message'
    return None

def gen(binary):
    exe = os.path.join(RES, binary + '.exe')
    md = PE(exe); d = md.data
    j = json.load(open(os.path.join(IDX, binary + '.json'), encoding='utf-8'))
    rows = []
    seen = {}

    # ---- 1. exact code literals ----
    for x in funstrings.extract_all(md, j['funcs']):
        v = x['text']
        cat = classify(v)
        if cat is None:
            continue
        key = (cat, v)
        if key not in seen:
            seen[key] = [0, '%s@%s' % (x['func'].split('/')[-1], x['insn'])]
        seen[key][0] += 1

    # ---- 2. go:string header constants ----
    sm = stringenum.enumerate_strings(md, minlen=2)
    for t, l, h in sm.values():
        cat = classify(t)
        if cat is None:
            continue
        key = (cat, t)
        if key not in seen:
            seen[key] = [0, 'go:string@file:0x%x' % h]
        seen[key][0] += 1

    # ---- 3. exact-token scans for closed vocabularies ----
    def scan(names, cat):
        for n in names:
            b = n.encode('latin1')
            if b in d:
                cnt = d.count(b)
                off = find_evidence(d, b)
                key = (cat, n)
                if key not in seen:
                    seen[key] = [0, 'token@file:0x%x' % off]
                seen[key][0] = max(seen[key][0], cnt)

    scan(HCS_NAMES, 'hcs_api')
    scan(DLL_NAMES, 'dll')
    scan(PIPE_NAMES, 'pipe_name')
    scan(REG_NAMES, 'registry')
    scan(ENV_NAMES, 'env_var')
    scan(PATH_NAMES, 'file_path')
    scan(URL_NAMES, 'url')

    # ---- 4. json tags (all of them, exact) ----
    for m in re.finditer(rb'json:"([A-Za-z0-9_,]+)"', d):
        t = 'json:"%s"' % m.group(1).decode()
        key = ('json_tag', t)
        if key not in seen:
            seen[key] = [0, 'structtag@file:0x%x' % m.start()]
        seen[key][0] += 1

    out = [(binary, cat, v, n, ev) for (cat, v), (n, ev) in seen.items()]
    out.sort(key=lambda r: (r[1], -r[3], r[2]))
    return out

if __name__ == '__main__':
    allrows = []
    for b in BINARIES:
        r = gen(b)
        print(b, 'rows:', len(r))
        allrows.extend(r)
    path = os.path.join(IDX, 'SVC-STRINGS.tsv')
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('binary\tcategory\tvalue\tcount\tevidence\n')
        for b, c, v, n, ev in allrows:
            f.write('%s\t%s\t%s\t%d\t%s\n' % (b, c,
                    v.replace('\t', ' ').replace('\n', '\\n').replace('\r', ''), n, ev))
    print('wrote', path, len(allrows), 'rows')
