# 全能力分母补核：运行中项目指令、网页获取契约

2026-11-16。固定DSH d743267388641bc76f17c45ce8b4c231aed1d32c。独立只读研究15个生产源码/装配文件及3个package入口；无实现/测试/模型/网络/实际配置或认证读取。本图不打断当前X30，生产仍由原桌面GPT-6 Luna高执行，不构成CLOSED。

历史135项只是既有审计清单分母，128/135及E/D100%不能外推固定DSH能力全集。本次没有证据重算总覆盖率，也不改判未审项。

## 项目指令的运行中协调

DSH真实base bundle packages/bundle/base/cordis.patch.yml:298装配dsh-agent-instructions。context/agent-instructions/src/index.ts:326 agent/pre-step等待协调并计算当前消息；:362 tools/result仅成功未取消的read/write/edit收集路径，nested执行先汇总父执行，开放step的触碰延到step/end。state.ts:268扩展触碰文件的下级scope；:371区分探测不可用与确实消失；:435生成set/replace/remove。:85构造带来源user-role消息；不要求Atlas复制Cordis事件名或把项目文本提升developer权限。上游:270仍有marker编辑后项目根scope重解释TODO，不当无缺陷标杆。

Atlas已有 agent/project_instructions.py:60 的git边界、祖先顺序、override、多种指令文件、真实路径限制、去重与预算。run_phases.py:1172加载request.workspace指令，:1344汇总system_message，:1430传引擎；InstructionsLoaded原因run_start。kernel/loop.py:1265动态重建更新plan/MCP；tool_node.py:1948文件结果处理快照/变更/通用hook，:2087返回消息，所查链没有接入项目指令协调。

限定缺口：同run首次触碰下级目录装当地指令、修改/删除后协调、来源及变更身份可解释回放。下一run会重新加载，不宣称永远不更新；通用hook可能有部署侧替代，本次未读实际配置。

后续验证：真实请求装配+fake provider，同run触碰子目录、修改/删除指令，核后续scope与只生效一次；失败/取消工具不提前发布，读取不可用不误报删除，重开可解释来源。无私有服务前提。所查链置信度high，全库替代路径medium。

## 网页获取策略与结果契约

DSH base bundle:460装配web/http fetch/tool；web/tool-web/src/index.ts:83注册fetch，fetch.ts:499将执行signal传ctx.web.fetch；web/web-fetch-http/src/index.ts:79注册provider。provider.ts:87仅自动跟同origin跳转，跨origin WEB_REDIRECT_BLOCKED；:147保留final URL/status/truncated，tool fetch.ts:328模型文本及展示metadata共用有效截断。provider.ts:123代理分支由代理解析origin，不能称所有情况本地DNS固定。

Atlas已有真实链 kernel/loop.py:4391→agent/tool_node.py:1797→tools/web.py:88 WebRuntime→websearch/service.py→providers/local.py:36→tools/web_extract.py。web_extract.py:98已有URL/凭据/地址校验；:243流式字节限额/timeout/逐跳检查与SSRF-safe client。不是缺网页读取。

限定差异：web_extract.py:252 urljoin后逐跳校验，没有同origin拒绝条件；:278结果不含HTTP status，tools/web.py:94只输出URL/标题/文本/长度/截断/provider。websearch/service.py:170 provider错误会尝试后续provider，本次未核VENDOR_ERRORS及供应商实现，不能宣称已证SSRF绕过。公网跨origin跳转本身不是漏洞；若保留为产品选择，应明确差异，不能默认功能等价。

后续验证：真实工具入口注入transport，核同origin/跨origin/禁止目标/取消/超限；策略拒绝不换provider继续，最终URL/status/有效截断统一；供应商外发与目标访问边界单列。该HTTP语义不依赖DeepSeek私有搜索协议。具体本地差异high，完整供应商策略medium。

上述行号为研究截点，仅用于定位，需实施时复核。不把项目文件或抓取内容当新的用户授权。
