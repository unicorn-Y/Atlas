# 最小集成计划

状态：仅建议，AWAITING_GPT6_REVIEW；本轮没有执行下列合并、部署或额外施工。

## 起点与边界

以独立、干净的 ui-redesign@0b1ba4114e25643369c95bfac85d37563788444f 为可比较起点。D:\Atlas是运行中的dirty主工作树，不能reset/stash/覆盖以制造干净基线。先封存dirty研究功能和配置差异，再由独立审查决定整合分支；这不要求本轮修改或停止真实运行实例。

本轮唯一代码补丁为W1，先验收该补丁的所选模型锁定、最多3次请求、失败元数据和队列暂停，再考虑其他问题。不得把新W1分支直接部署到当前主目录来代替隔离验收。

## 优先顺序与最小验收

| 阶段 | 成果 | 验收边界 |
|---|---|---|
| 1 | W1独立补丁 | 06列出的隔离测试+错误字段/队列静态复核；真实provider/真实UI仍待验收 |
| 2 | 当前P1安全和正确性问题的独立任务 | 先处理取消、记忆checkpoint/并发/死队列、精确来源、CDP、更新回滚；每项另获施工授权 |
| 3 | 每个独有候选能力的小补丁 | 按03实际缺口选择；确认API注册→调用→权限→结果UI，不整分支盲合并 |
| 4 | 干净整合版本的运行验收 | 配置有效来源、启动产物、聊天/工具/取消、记忆、旧会话分别证明；通过后另行决定部署 |

## 14个代码独有最大候选组

这些是Git谱系收敛候选，不是14个已获准合并分支，也不证明每一改动尚缺失。完整74 refs和逐路径证据见01及evidence/BRANCHES.json。共同祖先上的能力不需要重复吸收。

| 候选refs | tip SHA | 相对merge-base独有路径数 | 处理建议 |
|---|---|---:|---|
| card-b-tc-10 | `0dfc918c7bbc481f6fa99d4f697dd5fccbd7a20f` | 20 | 模型轨迹/诊断/后台任务；按服务注册、API、UI三段移植，不能从面板文件存在推出可用。 |
| memory-w2-ui | `11153a028feace09e952e23544e0adf1d155887c` | 7 | 记忆浏览器虚拟滚动；先和选定memlib API契约对齐，再移植UI。 |
| f2-c | `132a95d88606defa79421d15523427a592bd0053` | 26 | OAuth PKCE/vault及MCP设置、来源更新/崩溃报告；旧基线落后153提交，只挑能力及必要依赖，禁止整体覆盖。 |
| mem-integrate | `4046764fbabda187a4b329c830a4b9cab9631951` | 57 | 优先核SourceRef精确UID与兼容性；M1失败链路和真实验收另做，不把M2静态实现当全部记忆验收通过。 |
| fix-p1-audit | `56615d0f21b39c4cf30a6d14972e65174461c32c` | 20 | 安全/依赖/runtime补丁按当前代码逐条比对；共享sqlite DLL不得直接替换。 |
| memory-w2-fix | `6c5240e41381a1eda4f0c8d74687c47476f95721` | 19 | 记忆API修复；先确认与mem-integrate重叠及数据契约，避免重复覆盖。 |
| wip/kernel-deep-research-20261015 | `7f0ee93293786f8d884cdf45650f1fb8aa7e29c4` | 2 | 仅2个独有路径；与主目录untracked research功能比对，以kernel实际工具注册和取消链为准。 |
| absorb-all | `8d7b01d829f1332e9305fe8ee56758a6294139f7` | 46 | 会话发现/hooks/UI等；git merge-tree无文本冲突不等于语义安全。相对merge-base双方均有新提交，按46路径逐能力吸收。 |
| memory-v1 / memory-w1 | `9ace88c5731ed8be6dd7406d758161236938e2de` | 21 | memory-v1/w1同tip同tree，不重复集成；旧memory体系与当前library差异大，先定数据与迁移契约。 |
| wip/c3-frontend-from-laptop | `a451723b38be3e01b886811f16e6f0cca8d0ef33` | 22 | TeamBoard等候选前端；不得误算为f2-d，先验证后端接线。 |
| ctx-opt | `bddafde3ce6f76fb953085b89c096b68188e1ea0` | 30 | 上下文压缩恢复/handoff；确认用户控制历史及当前持久化兼容，分项移植。 |
| wip/f4-bc-20261009 | `bfea9fbfa69df15a5240d721be60c6a9d100e867` | 26 | 旧工作流功能组；以405逐项当前缺口筛选，不能全分支合并。 |
| feat/personal-todos | `f1b20f6eca3f91f514b4fb6c48aa82c183bf0339` | 5 | 独立待办UI+GET/PUT API；小范围API注册与挂载验证后吸收。 |
| card-c-tc-04 | `fba530af68422556c98d489ebe242203c3343f49` | 21 | 设置/平台相关候选；和f2-c及现存设置API去重后移植。 |

## 本机独有与dirty功能

- 本地 codex/desktop-repair-20261013@b177a6a94a7f1a9adb2891955a37cd4d4490054d 有3个独有代码提交。它重排记忆架构、打包staging/sqlite，且移除工具结果去重和准备进度；禁止整包覆盖当前library/memlib，先保留基线事件语义并单独验收。
- p11b-worker-leftover仅空提交、无独有tree改动，不作为待吸收功能。
- D:\Atlas的expert_harness/deep_research与tracked研究overlay没有提交版本；将来应先在另一个隔离分支固化、记录hash，再审工具注册、取消、引用真实性和费用边界。此次只读。
- atlas-boot-core环境/secret_scope、atlas-f1-d工具dirty、atlas-p1fix-verify2预加载脚本等是其他工作树磁盘独有内容，不能从远程tip推断已发布；原样保留。

## 复用与不做事项

取消复用kernel现有cancel_waiter，来源复用M2 SourceRef与SessionDB message_uid，队列/错误UI复用现有store和卡片，记忆检索复用当前Index接口，LSP复用现有bridge，启动依赖复用requirements.lock。协议/第三方链接若仅为源码引用，不能写成已在线核验或已成功集成。

不新增通用错误框架、不重写模型路由体系、不做全盘重构。语音/视觉仅保留后续计划与资源清理问题，未授权施工；详见modules/ROOT-ADDITIONAL.md。

