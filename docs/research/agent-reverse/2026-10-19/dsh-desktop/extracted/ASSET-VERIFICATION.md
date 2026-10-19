# dsh-desktop 源包核验记录

核验对象是 Atlas 发布的两份社区项目源码 ZIP，不是可安装桌面二进制。原始 ZIP 与解包树保存在 worktree 外的 `D:\atlas-research-agent-reverse-dsh-desktop-20261019\work\`，不进入本研究分支。

| lane | 精确发行资产 | bytes | SHA-256 | ZIP 条目 | 解包文件 | ZIP 未压缩字节 | CRC / 路径检查 |
|---|---|---:|---|---:|---:|---:|---|
| A | `https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-anywhere-labs-03d18d13bb.zip` | 222,488,979 | `03d18d13bb4a5bbfe79e3cd340d465d415a24f69968828c045efb5ea234b0a31` | 4,686 | 4,559 | 232,634,271 | `ZipFile.testzip()` returned null; no duplicate normalized paths; no absolute or `..` paths |
| B | `https://github.com/unicorn-Y/Atlas/releases/download/agent-client-packages-20261019/dsh-desktop-dongdong-agent-1dd3b7ded3.zip` | 5,400,611 | `1dd3b7ded3646abf5245f46b76e214d33908ac563d1c796d1a9baf592a9f5dc6` | 163 | 133 | 6,939,965 | `ZipFile.testzip()` returned null; no duplicate normalized paths; no absolute or `..` paths |

ZIP/SHA 是对 Atlas release asset 实际字节的来源身份核验。它们不证明运行行为。A 包内嵌的 DSH npm tarball 另按 `vendor/dsh-runtime/0.2.1-rc.2/manifest.json` 中逐包 SHA-256 与实际 tarball 计算值比对；343/343 项匹配。A、B 均为 tracked-source archive，未包含可直接启动的编译桌面发行包。本 lane 没有启动产品，故 `R=0`。

相关细目：`A-package-tree.tsv`、`B-package-tree.tsv`、`A-code-sha256.tsv`、`B-code-sha256.tsv`、`A-vendor-package-index.tsv`、`LICENSE-MAP.tsv`。官方运行时选定文件与关键符号位置见 `A-runtime-symbol-index.md`。上游源码本身没有复制进仓库。

Tree TSV 的 `compression` 列保留 ZIP 标准数值方法 ID（0 = stored，8 = deflate）；`crc32` 为 entry CRC32 十六进制值。ZIP 内同时出现 directory entries 与 files，因此 tree-entry count 和 extracted-file count 不相等。
