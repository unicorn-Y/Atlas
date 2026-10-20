# P6F — 内嵌的 Claude Code / SSH 发布清单

> 部分解决 `U-013`。CLI 二进制本体不在包里，但**它的发布元数据在包里**，因此可以精确知道：
> Desktop 期望哪个版本、哪个 commit、什么大小的二进制、校验和是多少、从哪下载。

---

## 1. Claude Code 2.1.299 清单（S）

主 bundle 内以 `JSON.parse('...')` 内嵌：

```js
function og(){ return JSON.parse('{
  "version": "2.1.299",
  "manifest": {
    "version": "2.1.299",
    "manifestSignatureEnforcement": "flag",
    "commit": "c416f56ec7eca27e49747c35af51d5c92c856ba1",
    "buildDate": "2026-10-13T22:06:14Z",
    "platforms": { ... },
    "sdkCompat": {
      "testedWrapperVersions": ["0.3.266" … "0.3.285"],
      "harnessSchema": 1
    }
  },
  "baseUrl": "https://downloads.claude.ai/claude-code-releases",
  "sdkWrapperVersion": "0.3.299"
}') }
```

| 字段 | 值 |
|---|---|
| 版本 | **2.1.299** |
| commit | `c416f56ec7eca27e49747c35af51d5c92c856ba1` |
| 构建时间 | 2026-10-13T22:06:14Z |
| 签名强制 | `manifestSignatureEnforcement: "flag"`（由 flag 控制） |
| SDK wrapper | **0.3.299** |
| 测试过的 wrapper | 0.3.266 … 0.3.285（19 个版本，注意缺 0.3.279） |
| harness schema | 1 |

## 2. 八个平台的二进制（S）

| 平台 | 文件 | 压缩后大小 |
|---|---|---:|
| `darwin-arm64` | `claude.zst` | 83,064,935 |
| `darwin-x64` | `claude.zst` | 87,828,689 |
| `linux-arm64` | `claude.zst` | 92,333,403 |
| `linux-x64` | `claude.zst` | 93,164,406 |
| `linux-arm64-musl` | `claude.zst` | 90,689,368 |
| `linux-x64-musl` | `claude.zst` | 91,585,340 |
| **`win32-x64`** | **`claude.exe.zst`** | **95,700,039** |
| `win32-arm64` | `claude.exe.zst` | 91,644,699 |

每个平台都有 `checksum`（sha256）+ `size`；macOS 额外有 `bundle`（完整 .app 的校验和与大小）。

**这解释了 P4 的很多事**：CLI 是 ~95 MB 的独立分发物，不在安装包里，首次使用时按此清单下载并校验。

## 3. 签名验证机制（S）

清单拉取路径：

```
{baseUrl}/{version}/manifest.zst.json
{baseUrl}/{version}/manifest.zst.json.raw-sig.json
```

验证参数（原样）：

```js
var gLr = "claude-code-manifest-v1\0";     // signing context（含 NUL 结尾）
var _Lr = 1;                                // schema
var vLr = "RSASSA-PKCS1-v1_5-SHA512";       // 算法
roots: [{ id:"claude-code-release-signing-key", pem: rLr }]
```

流程：拉清单 → 拉签名 sidecar → `bLr({bytes, sidecarJson, signingContext, roots})` 验证 →
失败则 `[CCD-autoupdate] Signature verification failed for ${i}: ${reason}` 并放弃该版本。

**结论**：CLI 的分发是**带签名验证的自动更新链**，不是简单下载。

## 4. SDK 兼容性校验（S）

```js
if (schema !== 1) return { ok:false, reason:"unsupported_harness_schema" };
let c = e.embeddedWrapperVersion;
if (!c || tl.valid(c) === null) return { ok:false, reason:"wrapper_version_unknown" };
return s.testedWrapperVersions.includes(c)
  ? { ok:true, manifest:o }
  : { ok:false, reason:"wrapper_not_tested" };
```

即：**内嵌 wrapper 版本必须落在清单声明的 `testedWrapperVersions` 白名单内**，否则拒绝启用。这是一条明确的兼容性闸门。

## 5. Claude SSH helper 清单（S）

同样内嵌：

```js
{"version":"683cc6a9cd1d99430efd762587e02dd076fd5ada",
 "manifest":{"version":"683cc6a9cd1d99430efd762587e02dd076fd5ada",
   "platforms":{
     "linux-amd64":{"checksum":"385678...","size":2912875},
     "linux-arm64":{...,"size":2601570},
     "darwin-amd64":{...,"size":2928330},
     "darwin-arm64":{...,"size":2681170},
     "windows-amd64":{...,"size":2896919},
     "windows-arm64":{...,"size":2555703}}},
 "baseUrl":"https://downloads.claude.ai/claude-ssh-releases"}
```

**关键交叉验证**：版本 `683cc6a9cd1d99430efd762587e02dd076fd5ada` 与运行时日志里
`[ClaudeSSHManager] Initialized with version 683cc6a9cd1d99430efd762587e02dd076fd5ada` **完全一致**。
这是静态清单与运行时行为的独立互证（虽然该日志属 out-of-scope，但这里只用作一致性佐证，结论本身由静态清单给出）。

SSH helper 体积约 2.5–2.9 MB，六平台。

## 6. 为什么 U-013 仍不是 RESOLVED

| 已知 | 未知 |
|---|---|
| CLI 版本 2.1.299 / commit / 构建时间 | **CLI 自身的命令行参数表** |
| 8 平台二进制的大小与校验和 | 各参数的语义与取值范围 |
| 分发地址与签名算法 | — |
| SDK wrapper 兼容区间 | — |
| Desktop 主要用**环境变量**配置 CLI（653 个 `CLAUDE_CODE_*`） | 少量命令行参数（如 `--output-format`、`--permission-mode`）的确切拼写与组合 |

**原因是物理的**：CLI 二进制不在包内（95 MB，按需下载），所以无法静态读取它的 `--help` 或参数解析代码。
要把 U-013 变成 RESOLVED，需要合法取得 CLI 分发包本身 —— 这超出本包的范围。

## 7. 产物

```
（本报告即全部证据；清单原文内嵌在 index.chunk-lzaSYO3Q.js，可按 og()/zft() 函数体定位）
```

## 8. 结论

- **Desktop 与 CLI 的契约是"元数据 + 签名 + 版本白名单"三者齐备**，不是松耦合。
- 本包内嵌的 CLI 版本是 **2.1.299**（commit `c416f56`，2026-10-13 构建），与 P7 运行时日志里的 `[CCD] Initialized with version 2.1.299` 一致。
- 这层的完备程度说明：**Desktop 把自己定位为 CLI 的"受控宿主"**，连 CLI 在哪、多大、什么哈希、要不要签名都写死了。
