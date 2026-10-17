# 本机与隔离验证

本轮只验证影响判定或 W1 验收的必要事项，不把静态代码、构建、健康接口或旧测试当成整套功能可用证明。

## 已执行的只读观察

| 项目 | 方法 | 实际结果 | 可推出的结论与边界 |
|---|---|---|---|
| 主目录源码基线 | git branch / rev-parse / status；对12个tracked dirty文件计算SHA-256 | ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f；存在dirty | 当前磁盘源码不同于HEAD；最终再次对比指纹 |
| 桌面/后端关系 | Win32_Process父子关系与监听端口 | Electron55644→Python1800→Python53140；8765归53140，9335归55644 | 可归因到D:\Atlas启动的源码桌面；不证明进程加载版本与磁盘最近修改完全相同 |
| 健康接口 | GET http://127.0.0.1:8765/api/health | HTTP200 status=ok | 端点可达；不证明聊天、工具或记忆端到端通过 |
| 通用ready路径探测 | GET http://127.0.0.1:8765/v1/ready | HTTP404 | 此版本不暴露该路径；不能单凭此结果认定就绪缺陷 |
| CDP可达性 | GET http://127.0.0.1:9335/json/version | HTTP200，Chrome/152.0.7977.130 | 已启动Electron的调试接口可达；未操作页面、会话或真实电脑输入 |
| 模型设置指向 | GET /api/settings/configuration，仅输出白名单字段 | default deepseek-v4.1-flash；memory gemini-3.8-flash；gateway_source=user-settings；key仅记录configured=true | 实时默认设置可见；不代表既有每会话选项或真实模型请求成功 |
| 分支源数据 | GitHub branches API与fetch后refs核对 | W0枚举74条远程分支（审查开始时）；详见01 | 全分支谱系统计以审查开始快照为准，后续新增本轮交付分支另列 |

## W1验证口径

W1 在独立代码工作树 `D:\\atlas-luna-w1-20261017`、隔离数据根和本地假调用下执行，不花真实模型 token。最终测试命令、输出摘要、覆盖案例与代码 commit 见 [06-MODEL-RETRY-FIX.md](06-MODEL-RETRY-FIX.md)；本节结果为已执行的实际输出。

必须覆盖：一次连接故障后同模型成功；持续503累计最多3次；401/402/404无重试；主与辅助调用不换模型；429 Retry-After阈值；已有文本/reasoning/tool delta或工具副作用后不重发；模型故障暂停队列并保留消息。必要前端类型检查与手工错误呈现的执行情况分别报告。

## 本轮隔离结果

- W1后端相关整文件最终：38 passed、5 warnings、无deselect；不是用筛选绕过旧重试断言。前端timeline 17 passed；失败队列1 passed（24 skipped）；renderer类型检查exit 0。精确命令见06。
- W1针对永久错误覆盖400/401/402/403/404/413/422；另含503总请求上限、取消退避、429阈值、partial text/tool delta不重发、辅助路由不fallback、route resolve attempts=0。测试使用隔离夹具/假调用，不请求真实provider；未启动独立HTTP网关，故不称真实HTTP网关端到端证明。
- W1全store套件不能报告全绿：clean baseline亦存在history、SettingsPage React、profiles夹具失败；W1分支精确差异和命令见06。失败队列用例单独通过。
- W5当前HEAD的三个现有隔离用例各1 passed：pending turn跨对象重读；Dream全部成功才推进checkpoint；Dream成功写项目段落。它们不覆盖启动drain、扫描并发迟到或手动编辑冲突。曾有setup失败及组合进程挂起，已停止该命令专属进程并逐项运行，见W5模块完整边界。
- W3/W6对W1前后端进行了独立静态diff复核；子类别标签映射、非瞬态tool-call协议错误重试、5xx长Retry-After和HTTPX流式错误正文丢失问题均已反馈修正并复核。错误正文读取上限16KiB，经已有共享redactor清洗后详情限1000字符；不承诺任意未知secret格式检测。静态复核不替代真实UI验收。
- 收口检查：主目录仍为ui-redesign、HEAD未变；初始12个tracked dirty文件SHA-256全相同；完整porcelain状态（含untracked路径）相同。git fetch仅更新远程跟踪refs；未改主目录源码或配置。

## 明确未执行的事项

- 未修改或重启D:\Atlas运行实例，未在真实会话注入模型故障，未请求真实上游模型。
- 未读写真实记忆/会话内容，未运行Dream、迁移、忘记或清理真实数据。
- 未执行真实电脑输入、SSH/Android远程操作或插件安装；工具端到端可用性不据静态审查推定。
- 未进行源码更新、依赖安装升级、全套后端回归、安装包性能或冷启动测试。
- 未把旧报告中失败或通过直接转录为本轮测试结果；模块独立最小复现如有执行，应在相应模块报告列出命令、隔离根与结果。
