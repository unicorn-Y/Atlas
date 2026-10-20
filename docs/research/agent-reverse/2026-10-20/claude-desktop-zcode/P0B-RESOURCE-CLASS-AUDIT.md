# P0B — 资源类文件逐类核对（补全"只登记未打开"的部分）

> 针对"整个包的东西是否都拆了"这个问题，把**非代码类**逐类打开核对一遍。
> 结论：除 `smol-bin.x64.vhdx`（已单独立报告，曾因误判 TEXT 被漏读）外，其余资源类**均属 Chromium/Windows 标准容器或纯视觉资源**，不含隐藏业务逻辑。

---

## 1. `.pak`（58 个，65,068,311 B）

### 分布

| 位置 | 个数 | 说明 |
|---|---:|---|
| `app/locales/` | 55 | Chromium 本地化包（每种语言一个） |
| `app/` | 3 | `resources.pak`（12,436,139 B）、`chrome_100_percent.pak`（719,654 B）、`chrome_200_percent.pak`（1,269,017 B） |

### 内容验证（PAK 格式头已解析，S）

PAK v5 头结构：`uint32 version, uint32 encoding, uint8 count_hi, uint16 count_lo, uint16 alias_count`。

| 文件 | 版本 | **内部条目数** | 字节 |
|---|---:|---:|---:|
| `resources.pak` | 5 | **34,060** | 12,436,139 |
| `chrome_100_percent.pak` | 5 | **44,289** | 719,654 |
| `chrome_200_percent.pak` | 5 | **44,289** | 1,269,017 |
| `locales/en-US.pak` | 5 | **74,800** | 586,582 |

**这些数字说明**：`resources.pak` 不是"几个资源"，而是 **34,060 个条目**；语言包每个 **74,800 条**。
它们是 Chromium 的 `grit` 资源系统，包含 HTML/CSS/JS 字符串、图片、音效等。

可读字符串极少（仅 37 条，主要是 `reference libFLAC 1.3.3`、`ENCODER=Sound Grinder 4.2`），
说明内容以二进制块存储（图片/音频/压缩文本），不是纯文本。

**判定**：**Chromium 运行时资源，无 Claude 业务逻辑**。Claude 自己的文案在 `ion-dist/i18n`（35,441 键）与 `app/resources/*.json`（837 键）。

## 2. `.pri`（5 个，1,127,072 B）

```
resources.pri            492,800
resources.scale-125.pri  158,568
resources.scale-150.pri  158,568
resources.scale-200.pri  158,568
resources.scale-400.pri  158,568
```

**判定**：Windows **MRT（Modern Resource Technology）资源索引**，为 MSIX 的图标/磁贴提供多倍率变体。纯打包元数据。

## 3. `ion-dist/i18n/`（35 MB，**逐文件已清点**）

| 文件 | 条目数 | 字节 |
|---|---:|---:|
| `en-US.json` | **35,441** | 2,575,148 |
| `de-DE.json` | 35,392 | 3,072,476 |
| `es-419.json` | 35,386 | 2,990,163 |
| `es-ES.json` | 35,390 | 3,000,967 |
| `fr-FR.json` | 35,388 | 3,197,977 |
| `hi-IN.json` | 35,387 | 5,619,587 |
| `id-ID.json` | 35,389 | 2,775,295 |
| `it-IT.json` | 35,389 | 3,004,460 |
| `ja-JP.json` | 35,389 | 3,587,253 |
| `ko-KR.json` | 35,389 | 3,142,278 |
| `pt-BR.json` | 35,388 | 2,965,032 |
| **合计** | **389,328 条** | 35,930,636 |

另有 `dynamic/` 子目录，同样 11 个语言文件。

**键的形状**：不是可读字符串，而是 **base64-ish 短哈希**，例如：

```
"2qhwlvx/Fl": "..."
"/5O7cdFfl5": "..."
"cqZwYWgaVv": "..."
```

这是 **FormatJS/react-intl 的 `id` 机制**：构建时把 `defaultMessage` 的文案哈希成 id，
运行时按 id 查找翻译。因此：

- **en-US.json 的 35,441 条 = SPA 的全部界面文案条目数**；
- 键不可读，但**值是可读英文/对应语言文本**；
- 每种语言的条目数略有差异（35,386–35,441），说明少数条目未完全翻译。

**判定**：内置 SPA 的完整文案库，**35,441 个键已全部清点**，无隐藏结构。

## 4. `app/resources/*.json` 语言包（逐文件已清点）

**43 个语言文件**，共 **29,655 条**，唯一键 **837 个**。

| 项 | 数值 |
|---|---:|
| 语言文件数 | 43 |
| 每个文件的条目数 | 约 690（837 键 × 覆盖率） |
| 合计条目 | 29,655 |
| 唯一键 | **837** |

键同样是 react-intl 的**哈希 id**（如 `8YQEOfuaGO`、`rdiPpQVqvY`）。

**与 §3 的关系**：

| 层 | 键数 | 语言数 | 用途 |
|---|---:|---:|---|
| `ion-dist/i18n/` | **35,441** | 11 | 内置 Web SPA（产品界面） |
| `app/resources/*.json` | **837** | **43** | 桌面壳的 6 套本地窗口（菜单/对话框/错误页） |

**这个比例很说明问题**：桌面壳的本地文案只有 837 条，而 Web SPA 有 35,441 条 ——
再次印证 **产品界面主要在内置 SPA / 远程站点，本地壳只承担很少的文案**。

43 种语言覆盖了 `am`（阿姆哈拉语）、`bho`（博杰普尔语）、`ig`（伊博语）等，
说明 Claude 的本地化覆盖面很广，而这些语言只翻译了那 837 条壳文案。

## 5. 字体与图标

| 类型 | 数量 | 说明 |
|---|---:|---|
| `.woff2` | 49 | AnthropicSans / AnthropicSerif / AnthropicMono / anthropicons（多字重与变体） |
| `.woff` | 20 | 旧格式兜底 |
| `.ttf` | 21 | 图标字体 |
| `.ico` | 5 | 托盘与窗口图标（`Tray-Win32.ico` 122,208 B 等） |
| `.png` | 128 | MSIX 磁贴（多倍率）+ 少量 UI 资源 |
| `.svg` | **379** | **内置 SPA 的图标集**（单个体积小，合计 1.35 MB） |
| `.gif` | 16 | 20.5 MB —— 内置 SPA 的演示动画 |
| `.webp` | 6 | 68 KB |
| `.mov` / `.webm` | 1 / 1 | `ion-dist/images/install-hub/clawd-laptop.mov`(128,048) 与其 webm 替代 |

**判定**：全部为视觉资源。GIF 占 20.5 MB 是安装引导页动画；SVG 379 个是图标系统。

## 6. 音频

`ion-dist/audio/voice/`：26 个 mp3（3.1 MB）+ 1 个 `audioSinkWorklet.js`。
**判定**：5 种语音音色的试听素材 + 播放 worklet（详见 `P6B-VOICE-PIPELINE.md`）。

## 7. 其它单件

| 文件 | 大小 | 判定 |
|---|---:|---|
| `app/LICENSES.chromium.html` | 20,477,229 | Chromium 第三方许可证汇总（纯文本） |
| `app/icudtl.dat` | 10,875,024 | ICU 国际化数据（Chromium 标准） |
| `app/v8_context_snapshot.bin` | 742,456 | V8 上下文快照（启动加速） |
| `app/snapshot_blob.bin` | 369,024 | V8 堆快照 |
| `app/resources/*.ico` | 122 KB each | 托盘图标 |
| `[Content_Types].old` | 2,180 | MSIX 打包残留 |
| `resources.pri` 等 | 见 §2 | Windows 资源索引 |
| `AppxSignature.p7x` | 10,547 | MSIX 签名（Authenticode PKCS#7） |
| `AppxBlockMap.xml` | 1,544,325 | MSIX 块映射（每个文件的哈希） |

## 8. 与"是否全拆"的关系

| 类别 | 打开核对了？ | 有无业务逻辑 |
|---|---|---|
| `.pak` 58 个 | ✅（头部+内容抽样） | 无（Chromium 资源） |
| `.pri` 5 个 | ✅ | 无（Windows 资源索引） |
| i18n 40+ 语言 | ✅ | 无（文案） |
| 字体/图标 599 个 | ✅（按类型） | 无 |
| GIF/SVG/图片 | ✅（按类型） | 无 |
| 音频 26 个 | ✅（见 P6B） | 无（试听素材） |
| VHDX 1 个 | ✅（见 P5C） | **有，且是最大发现** |
| 18 个 PE | ✅（见 P0/P5/P6） | 有 |
| 3,589 个 JS | ✅（见 P1/P1B/P1C） | 有 |
| 3 个 WASM | ✅（见 P1B） | 有 |

## 9. 结论

**除 VHDX 外，所有非代码资源都是标准容器或纯视觉/文案资源，不含隐藏逻辑。**
VHDX 是唯一一个"因为格式嗅探误判而差点被当作资源略过"的实质内容载体，已单独出报告并解出全部 5 个文件。

## 10. 一个方法论教训（写下来供后续复用）

P0 的格式嗅探器用"前 4 字节是否为可打印 ASCII"判定 TEXT，因此：

```
vhdxfile...  →  被判定为 TEXT
```

这类**文件头是 ASCII 但实际是二进制容器**的格式（VHDX、某些 SQLite 变体、tar、部分自定义格式）会被系统性漏判。

**已修正**：`FILE-LEDGER.tsv` 中该条目的 format 字段已从 `TEXT` 改为 `VHDX`。
**后续建议**：嗅探表应加入 `vhdxfile`、`SQLite format 3`、`ustar`、`\x1f\x8b`（已有）等签名。
