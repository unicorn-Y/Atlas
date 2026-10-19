# Extraction log: ZCode 3.15.3 checkpoint

## Inputs and verification

Release assets came from GitHub release `agent-client-packages-20261019` in `unicorn-Y/Atlas`, retained under `D:\agent-client-staging\opencode-zcode\requested-assets`. SHA-256 and byte sizes were independently recalculated and match the release manifest:

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `zcode-desktop-v3.15.3-bc8100ba43.exe` | 181367144 | `bc8100ba4377256fbe1531d549b4775f18e3ba21768b6294ca50751cd461faca` |
| `zcode-agent-runtime-embedded-v3.15.3-31965ce1d5.cjs` | 15127039 | `31965ce1d5d4a808ef156784f67996de42ccab335591d2386a61ea8f6f506a54` |
| `zcode-source-main-aac4755-45034cfbc0.zip` | 100436252 | `45034cfbc064716a34a06a117af6aed359012927834a3e40c24cf89682ef8ab1` |

The ZIP source commit is `aac4755666d09fdcd70272fcf063c077a639015f`, version 3.15.1. It is a separate version from the desktop and runtime 3.15.3 assets. The desktop installer was statically unpacked into the retained staging tree; neither EXE nor CJS was executed.

## Tools and results

- REA PE binary inspection: EXE identified as PE x86 installer; evidence also recorded resource inventory (61 entries / 28 resources). This does not imply installer execution.
- REA full application-tree analysis: strict validation stopped at `resources/app.asar/node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node`, whose unpacked companion bytes did not match declared ASAR integrity. `record-and-continue` did not return before the MCP 300-second wait limit; the whole-app semantic graph remains incomplete.
- REA `resources/glm` analysis: completed with partial/truncated semantic coverage; 360 relevant files, 294 parsed JS, 186 modules, 1,292,029 AST nodes, 0 parser failures, 413 limitations. It does not supply desktop main/renderer IPC mapping.
- REA whole `resources/app.asar` attempt: exceeded the 300-second wait limit. A separate REA `open_binary` operation was still pending at checkpoint time. No claim of completed ASAR extraction is made.
- Acorn 8.16.0 from the packaged desktop dependencies parsed the verified CJS as a CommonJS script. It contains 15,124,982 UTF-16 code units / 15,127,039 UTF-8 bytes, 3,458,803 AST nodes, 58,079 function nodes, 43,602 variable declarations, and 231,843 call expressions. Acorn's offsets were converted to UTF-8 byte offsets for the evidence tables. CJS parsing is independent from REA's `parse_status=null` for that file.

## Output inventory status

This checkpoint contains release hashes/metadata, an initial package manifest, a partial retained-tree inventory, CJS AST/byte-offset indexes, exact code slices and family hits, runtime comparison anchors, and this log. It is not a complete file/package inventory. Desktop IPC/UI extraction, full app-ASAR validation, further call-chain closure, and runtime behavior remain open. No source map was found in the retained collection index. Potential false positives are minimized by using exact byte offsets in the SHA-verified bundle and AST-confirmed function ranges; semantic identifications of webpack symbols remain analyst interpretations pending source correspondence.
