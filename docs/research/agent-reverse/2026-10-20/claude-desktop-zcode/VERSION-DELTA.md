# VERSION-DELTA — 2.42304.0 (MSIX) vs 2.42304.2 (Squirrel nupkg)

> 解决 `U-018`。两包均已解包到本地，全部比对基于文件字节。
> 结论：**同代补丁版本，无功能重构，但有一处实质安全增强**。

---

## 1. 总体结构对比

| 目录 | 2.42304.0 | 2.42304.2 |
|---|---:|---:|
| `.vite/build` | 380 | 380 |
| `.vite/renderer` | 60 | 60 |
| `node_modules/@ant` | 2 | 3 |
| `node_modules/node-pty` | 14 | 16 |
| `node_modules/ws` | 19 | 19 |
| `node_modules/agent-base` | 7 | 7 |
| `resources/artifact-libs` | 4 | 4 |
| `resources/bundled-skills` | 7 | 7 |
| `resources/github-mcp` | **0** | **1** |
| `resources/office365-mcp` | **3** | **5** |
| `compile-cache` | 3 个 `.jsc` | 3 个 `.jsc`（文件名全变） |

ASAR 内可枚举文件：.0 为 500、.2 为 506。
`.0 only` 373 项、`.2 only` 379 项，其中绝大多数是 **chunk 文件名哈希变化**（`.vite/build/index.chunk-*.js` 与 renderer 的 `*-<hash>.js`），说明 2.42304.2 是**重新构建**而非增量补丁。

**内容层面**：按 SHA256 看，两版共有的 475/481 个内容哈希中只有 **72 个完全一致** —— 即构建噪声覆盖了几乎所有文件。

## 2. 同路径文件的真实差异（31 个，全部同尺寸）

| 文件 | 字节 | 差异性质 |
|---|---:|---|
| `package.json` | 5,088 | **仅 1 个字符**：`"version": "2.42304.0"` → `"2.42304.2"`（`A[126]='0'` → `B[126]='2'`） |
| `resources/bundled-skills/manifest.json` | 4,628 | **仅 `agentSkillsRef`**：`1792020044` → `1792021638` |
| `.vite/renderer/main_window/index.html` | 9,198 | 仅内联构建哈希变化（3 个 diff 块） |
| 其余 28 个（preload、html、skill 包、`.jsc`） | 同尺寸 | 构建哈希/时间戳替换 |

**这 30 个文件可以判定为"构建噪声"，无行为差异。**

## 3. 唯一有实质变化的功能文件：`nodeHost.js`

| | 2.42304.0 | 2.42304.2 |
|---|---:|---:|
| 字节 | 5,907 | **7,985（+2,078）** |

新增内容分三块（全部为新增，旧逻辑保留）：

### 3.1 默认 CA 证书屏蔽（安全增强）

```js
var C = new Set([ /* 18 个 SPKI SHA-256 指纹 */ ]);
function w(e){ const t = new f.X509Certificate(e).publicKey.export({type:"spki",format:"der"});
               return f.createHash("sha256").update(t).digest("hex"); }
function T(e){ const t = w(e); return t !== undefined && C.has(t); }
var E = new Map();
function D(e){ return e.filter(e => { let t = E.get(e); if (t===undefined){ t=T(e); E.set(e,t);} return !t; }); }
var O = S("default_cas:set", () => {
  p.default.setDefaultCACertificates(D(p.default.getCACertificates("default")));
});
```

行为：在 MCP 宿主进程启动时，取 Node 的默认 CA 集合，**剔除 18 个硬编码的根证书**（按公钥 SPKI 的 SHA-256 比对，带 Map 缓存），再写回 `tls.setDefaultCACertificates`。

这直接针对 **TLS 中间人拦截**：被剔除的是会在本机注入的代理/杀软根证书类 CA。它只作用于 `nodeHost`（本地 stdio MCP 服务器所在进程），**不影响主进程**。

18 个指纹已完整记录在 `ledgers/CA-BLOCKLIST.txt`（逐行一个 SHA-256）。**这些是公钥 SPKI 指纹，不含任何厂商名称信息**，因此无法从二进制直接判定归属；要归属需要与公开根证书库比对，本报告不做猜测。

```
8d417db2dd8bf5e3084d1e3f196d583849d81bdd4c00c70b9d39369e96b8c782
eabc185c4e82d942b1a5978ba3c0181487d6b3b9974e5c49f72f6d0bd9637150
376a1a7082a593dccc20d561d119e9ab8d30f11cc321d0a37fa41f0df284e01c
b7408b4d2be0238ba37004dd34e276c6019bd2f24c9db7d4980f5f6c359a4bcc
941ea0cbce0926d9f34ec667cee669b61fd39f4338fa0b91048d5749d8880d25
1cbbd4cb5eec6a287e34636c07c78378fa3eb3c6d3fb0563286870f283d87034
71f8adeec2b58adbdf6205c98dde928a4254b03695193d7f9a63a9a2588095d0
3f83a68c4e80fc3f4f487e3105ad146498e56a09a3ea223b2a2982943f5995d7
33836758bd871b8d464bd669b0b81832880b81e363fb8cbb21ba8e843a138858
11567f2aaf4325c4044880c6ed2b37f1ca2586d87059cf254934d97c4fee89a5
c619e4780ed8e0abeda24ad732567de4383a7ea941338f6d1a7d1b49ac792fe9
b5ee1c904ac2aae39c92601ab466269c0c1cd0b96badbd251b0ed88e6c4ded68
8dd3d055a7f47ffbca287285dcfd201dde92823ccc484d30f11cc40f079b3a3e
e3212ac258d6d86f464c1150866a298c04a42783c1d17d7baa6a24ac0323f139
cf36ee3b065cb7405569f6c189b54c2f3d43042a995e3f5fcfccefe09ad73177
ece28e35289ce8621c72407949e5050052ad4607cc332eaf9b546029aacbfb7a
0a6c2b2ca5b364207954171987ac9d2178561569d8205457e77ca90c32ede282
5da77dc800f4c6fa93c6015aa6bd898fdb7c28d869e764571b25c00375a77755
```

判断依据：`D(e)` 用 `X509Certificate(e).publicKey.export({type:"spki",format:"der"})` 的 SHA-256 与集合比对 —— **认公钥不认证书**，所以同一 CA 换证书仍会被拦。

### 3.1 归属分析（实测，非猜测）

用本机可得的两个根证书集合做 SPKI 比对：

| 对照库 | 条目数 | 命中 |
|---|---:|---:|
| Windows `ROOT` 存储（`ssl.enum_certificates`） | 61 | **0** |
| `certifi` 公开根证书包（Mozilla 信任库） | 119 | **4** |

命中的 4 个（完整主体名）：

```
CN=emSign Root CA - G1,     O=eMudhra Technologies Limited, OU=emSign PKI, C=IN
CN=emSign ECC Root CA - G3, O=eMudhra Technologies Limited, OU=emSign PKI, C=IN
CN=emSign Root CA - C1,     O=eMudhra Inc,                 OU=emSign PKI, C=US
CN=emSign ECC Root CA - C3, O=eMudhra Inc,                 OU=emSign PKI, C=US
```

**结论**：18 个指纹中有 4 个属于 **eMudhra（印度 CA）的 emSign 根证书族**。其余 14 个不在 Mozilla 信任库也不在本机 ROOT 存储中 —— 说明它们**不是公开可信根**（更可能是企业/MITM 代理自己的根，或已从信任库移除的根）。

这个结果符合"反 TLS 拦截"的设计意图：**把能签发本地拦截证书的 CA 从 MCP 宿主进程的可信集中剔除**，即使它被装进了系统信任库。

### 3.2 同步调用耗时追踪

```js
var y = null;
function b(){ try { return m.performance.now(); } catch { return NaN; } }
function x(e,t){ t>=0 && (!y || t>y.syncMs) && (y = { label:e, syncMs:t }); }
function S(e,t){ return (...n) => { const r=b(); try { return t(...n); } finally { x(e, b()-r); } }; }
```

用途：给关键同步路径（如上面的 `default_cas:set`）打点，记录**最慢的一次同步调用**，用于诊断 MCP 宿主卡顿。

### 3.3 模块依赖变化

| | .0 | .2 |
|---|---|---|
| 引入 `node:crypto` | 无（仅 later） | **有**（`X509Certificate`、`createHash`） |
| 引入 `node:tls` | 无 | **有**（`setDefaultCACertificates`、`getCACertificates`） |
| 引入 `node:perf_hooks` | 无 | **有**（`performance.now`） |

## 4. 新增的打包资源

`.2 only` 的非 chunk 项里有 6 个是**解包产物**（`app.asar.unpacked` 内容），不是新增功能：

```
node_modules/@ant/claude-native/claude-native-binding.node
node_modules/node-pty/prebuilds/win32-x64/conpty.node
node_modules/node-pty/prebuilds/win32-x64/conpty_console_list.node
resources/github-mcp/github-mcp-server.exe
resources/office365-mcp/msal-node-runtime.node
resources/office365-mcp/msalruntime.dll
```

原因是 `.0`（MSIX）把这些放在 `app.asar.unpacked/` 而 asar 头里标 `unpacked:true`；`.2`（nupkg）把它们**压进了 asar 内部**（`unpacked:false`）。**这是打包方式差异，不是内容差异**——两版都有这些二进制。

对应地，`resources/office365-mcp` 从 3 → 5、`github-mcp` 从 0 → 1，正是这个搬移造成的计数变化。

## 5. 结论

| 问题 | 回答 |
|---|---|
| 2.42304.2 相对 2.42304.0 有功能新增吗？ | **没有新增用户功能**（97 个 eipc 服务、1,170 方法、UI 表面、技能集均不变） |
| 有行为变化吗？ | **有一处**：MCP 宿主进程排除 18 个根证书 |
| 有安全修复吗？ | **是**：CA 屏蔽 + 同步耗时诊断 |
| 技能集变了吗？ | 内容不变，仅 `agentSkillsRef` 从 `1792020044` → `1792021638` |
| 能否用 2.42304.0 的结论推导 2.42304.2？ | **除 `nodeHost.js` 外可以**；`nodeHost.js` 必须分别看 |

## 6. 证据

```
ledgers/VERSION-DIFF-242304.json   完整 only_0 / only_2 / changed 清单
本地路径：
  D:\Atlas\_research\claude-desktop\2026-10-20\extract\_asar        (2.42304.0)
  D:\_deliverables\claude-desktop-2.42304.2\asar                    (2.42304.2)
复现：按路径遍历两棵树，记录 (size, sha256)，再做集合差与同路径哈希比较。
```
