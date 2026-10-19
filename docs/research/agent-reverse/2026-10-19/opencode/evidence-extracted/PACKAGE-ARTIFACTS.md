# OpenCode 2.0.32 package evidence

## Exact assets

All five requested cached files were re-hashed and byte-counted before analysis. Each matches the corresponding SHA256 in the dispatch manifest.

| Asset | Bytes | SHA256 | Result |
|---|---:|---|---|
| Windows x64 desktop installer | 236,735,200 | `c6beba4a54ce5daf2c7cc4017aee61c4af2bfb89b377a3a3f059917d263aea2e` | exact |
| npm Windows x64 CLI package | 100,022,170 | `bbc00de2c5cdbb6c11649e7c6e2c094e8b55d16d4bfab41577d3cdbe5d36c90d` | exact |
| npm CLI wrapper package | 2,958 | `3395134eec1cf24f91e8d2c660843a851e933794172a13c2507d9a9805ed5760` | exact |
| v2.0.32 source ZIP | 84,041,220 | `0c4dfbc2f94c15e0e94bc1b2b4a8524c3474f5fb6c682d6f96c505ca58a55554` | exact |
| v1.19.3 source ZIP | 77,886,321 | `662ef890f51c49c364bc8e91ab04f25c8a3abf8833c86d42d9d0e5c31df34b0b` | exact |

The verified source commits are v2.0.32 `843a6c514e606b436a7fe713422ace0a93ad3d61` and v1.19.3 `60c9be092129745688bb3c3a752affc6cbd66ede`.

## Shipped desktop structure

Extracted installer root: `D:\agent-client-staging\opencode-zcode\OpenCode\desktop\v2.0.32\extracted-installer\application\`.

- `OpenCode.exe`: PE product/file version 2.0.32.0.
- `resources\app.asar`: 176,346,919 bytes; ASAR header contains 8,307 file entries. Root package is `@opencode/desktop`, version `2.0.32`, main `./out/main/index.js`.
- `resources\opencode-cli.exe`: 213,722,504 bytes; PE file/product metadata says 1.4.2, while isolated `--version` says `opencode v2.0.32`.
- `resources\app.asar.extracted`: 8,307 extracted files, including 6,599 JS, 487 TS and 463 JSON files.
- No `.map` files were found under the extracted `out` tree.

Selected shipped bundle anchors (path relative to `resources\app.asar`):

| Path | Bytes | SHA256 | Anchor |
|---|---:|---|---|
| `out/main/index.js` | 819,133 | `a43fc9bd7ce7e27cc215d1f1b630087a93b4e7b889075860ae6864c76429c9fc` | Bootstrap; CLI sidecar and desktop RPC initialization |
| `out/main/desktop-CiR2Cmvk.js` | 189,882 | `a0e11ee1c666103aa5ee77b28fa9d1e89eb500918978960abf159712d3543e5b` | `ExtensionSubscribe` byte 23,827; `opencode-cli.version` byte 157,446 |
| `out/main/host-R1JTLSvD.js` | 65,932 | `b128dd40399a4e840385b392031687f73a826273af68defecf8501544f481aa5` | Browser and `browser.pane` byte 27,546 |
| `out/main/main-CFnF_jTV.js` | 16,371 | `adfb5ff7184956a0d2b7c0324beedacd874706bfe3b2cb889c1ec2d056bf80d0` | `browser.pane` byte 14,691 |
| `out/main/pane-bxT5y0e5.js` | 81,715 | `efaf9c20f0136ef971becc9372aed75e5cb781b3472298a119a91bea82ea4814` | pane host bundle |
| `out/renderer/assets/main-CZyBNj5O.js` | 1,321,667 | `1fda7588c16a4c245717c80d320b1a413c7ca0ca009e1fba9ffc15bfc457d405` | `ExtensionSubscribe` byte 1,302,996; `browser.pane` byte 1,222,691 |
| `out/renderer/assets/model-CFhkIZEf.js` | 11,089 | `31cb047330225095bc400ada4fbd87bc33d5ff64b20edb312ee58d8ec2bc4314` | Browser registration/reopen state |

The desktop sidecar hash differs from the npm package's `package/bin/opencode.exe` (same 213,722,504-byte size; package binary SHA begins `045c13859180608981b87abb901a31f9`). Both report version 2.0.32 when invoked with `--version`. No cause for the byte-level difference is established here.

An observed ASAR integrity mismatch is present at `node_modules/@lydell/node-pty-win32-x64/prebuilds/win32-x64/conpty/OpenConsole.exe`: ASAR integrity entry SHA256 `7f68c840226505004215c0b82d4e502c24b5bc3f4b93c4baaaa19bd679c0def8`; extracted observed SHA256 `c2216ab94daaa4f6e6da636da7296487fe8629c29d564fa4893fe1a0ea17d2fa`. This records a mismatch only; cause is unknown.

## Isolated CLI observations

Both the packaged npm binary and desktop sidecar returned `opencode v2.0.32` for `--version`. In a scratch HOME/config/data root, the npm binary returned exit code 0 for `--help`, `serve --help`, `service --help`, `plugin --help`, `mcp --help`, and `run --help`; stdout was captured locally during the session. This is narrow CLI runtime evidence, not validation of server session execution or desktop UI behavior.

One localhost-only `serve` startup did not yield a successful API operation. The server required generated local authentication; no credentials or account state were used. The process was stopped and its temporary output removed. Desktop/browser runtime behavior remains unobserved.

## v1 to v2 source tree comparison

An exact path + SHA256 comparison of `.ts`/`.tsx` files in the two verified source trees found 4,993 v2 files and 3,313 v1 files: 3,782 paths added, 2,102 removed, and 970 same-path files with changed content. These are raw inventory counts (not rename detection or semantic change counts). In particular, v2 removes the `packages/opencode` monolith and adds substantial `packages/core` and `packages/gui-extensions` trees. See fixed-tag source anchors in the reports before drawing behavior conclusions.

## Tool boundary

The REA JavaScript application analyzer was attempted against the shipped ASAR. Its default integrity policy stopped on the mismatch above; retrying with record-and-continue timed out at the tool-call boundary after 300 seconds. The resulting source findings therefore use the verified release bytes plus fixed-tag source, with ASAR path/byte-string inspection; they are not the output of a completed REA analysis. No runtime desktop launch or authenticated server API operation was completed.


Isolated stdout evidence files are committed in [cli-help](cli-help/README.md). They contain version/help output only.
