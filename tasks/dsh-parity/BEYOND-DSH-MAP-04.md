# S10 图像 occurrence 预算卸载：独立能力核对

2026-11-16。固定DSH d743267388641bc76f17c45ce8b4c231aed1d32c。只读核对，无代码修改/模型/网络/服务/测试，不打断当前X5/X7。生产实施仍由原Codex Desktop Luna承担。本图不构成CLOSED。

## 结论与历史修正

S10不能由S19附件字节持久化替代。历史DSH-GAP-LEDGER.md:103/:114所称“图片从不进历史、无可卸载内容”不符合当前Atlas：session_sync.py:196/:327会将atlas-attachment引用恢复成data URL再次发给模型。保留S19，不另建附件库；S10作为独立候选增量。

## 固定DSH真实链

- compaction-image-offload/src/image-offload.ts:16按失败请求顺序选最老user/message和tool/result图像的出现位置，事件保存seq/imageIndexes，不按唯一blob；assistant排除，已卸载位置仍占索引。
- llm-deepseek/src/images.ts:38及llm/src/content.ts:284/:299对实际请求表示逐次出现计算count/bytes；Files raw bytes和inline base64分别预算，量化释放，byteQuantum>1时边界严格超过目标。
- compaction-image-offload/src/index.ts:25处理IMAGE_OFFLOAD_REQUIRED，先追加image/offload再重试；这是surface修复，不耗普通provider retry预算。
- projection.ts:39/project-message.ts:13严格校验角色/稳定节点/索引/重复卸载，保持消息身份，live与detached replay共享纯投影。
- llm-deepseek/src/images.ts:42先将已卸载位置变占位再准备剩余图像，换宽松预算不会自动恢复旧位置。
- llm/src/content.ts:34/:108占位仅给授权环境可映射的只读路径，否则提示重附；卸载不删除字节、不撤回已发请求、不清远端文件。
- bundle/base/cordis.patch.yml:429真实配置；llm-deepseek/adapter.ts:81/:104实际prepare/inline；agent-loop/agent.ts:511失败分派；compaction-basic/index.ts:442摘要恢复。

路径以上均相对固定DSH packages。当前遍历平铺content，不能凭注释声称任意嵌套结构支持。

## Atlas已有与主链缺口

已有：session_sync.py:275内容寻址/fsync/先落附件后消息，loop.py:1157接线；loop.py:2528 price_surface_nodes已接route_image_pricer，token_meter.py:281图像计价；kernel/context.py:157/:383/:423与loop.py:2214/:2790已有压缩/媒体保护/overflow恢复。run_drive.py:2949入站单图4MiB/总8MiB只限制本轮输入，不是历史图像卸载。

限定所查主链缺口：实际图像count/表示bytes超额→稳定消息+image index决策持久化→回放占位→普通/摘要请求共享恢复，未核到完整链。context.py:105 JSON长度估算及loop.py:2331压缩阈值不等于图像预算；可视token计价也不自动成为压缩预算。

工具图像关联边界：loop.py:3099把图像加入本轮messages，但该分支持久化文本content而非组合tool_content；不能由用户附件推广所有工具图像回放。附件解析器本身不按conversation_id授权，外层权限未审，不能据此宣称跨会话泄漏。

## 后续最小增量

复用附件/SessionDB：实际route图像预算→结构化卸载需要；追加稳定occurrence决策；投影先决策后读blob并版本化缓存；普通与摘要请求先持久化再重试，写失败/取消/无进展停止。保留原消息和blob，路径仅按执行环境授权映射；工具图像先补规范持久表示。事件若进桌面需三真源同步。

本地fake-provider/临时DB验证：重复blob只卸指定位置、raw/base64/count/量化边界、普通/摘要先写再重试、写失败/取消、清缓存/重开/宽松route仍保持卸载、新附同blob为新位置、卸载不读blob、保留blob完整性校验、无授权路径不暴露host路径、tool图像配对。

未核验所有adapter、工具图像规范表示、缓存失效与跨环境授权映射。DSH语义及Atlas已有基础high；全替代缺口范围medium，静态不冒充实测。
