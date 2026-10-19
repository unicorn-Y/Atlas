# dsh-desktop extraction evidence map

Source assets are the two taskbook-pinned Atlas Release source ZIPs listed in `ASSET-VERIFICATION.md`. SHA-256, byte size, ZIP CRCs, entry counts, duplicate/path safety, and expanded size are recorded there. Full upstream ZIPs and extracted source trees were kept only in the lane worktree's external `work/` scratch and are excluded from Git.

| File | Content |
|---|---|
| `A-package-tree.tsv`, `B-package-tree.tsv` | ZIP entry path, compressed/uncompressed bytes, CRC, compression method |
| `A-code-sha256.tsv`, `B-code-sha256.tsv` | Per-file SHA/size for A Next and B source/config code scope |
| `A-symbol-index.md`, `B-symbol-index.md` | Static source path, line and symbol/call anchors for both community apps |
| `A-vendor-package-index.tsv` | A's vendored npm package name/version/license/file hash and package metadata |
| `A-runtime-symbol-index.md` | Selected real DSH runtime tarballs with nested SHA and source-file symbol/line anchors; not extracted upstream code |
| `LICENSE-MAP.tsv` | Root/runtime/vendor license and attribution inventory |
| `RUNTIME-OBSERVATIONS.md` | Explicitly NOT-RUN status and boundary |

Classification: A/B archive identity and bundled file contents = S (static artifact); implementation behavior inferred from those contents = S, not R. No product app was launched. The source archives do not contain compiled installable desktop apps. Atlas comparison baseline is `main@aa6196f550098cc46081dc6db2c376cb87ddffa5`.
