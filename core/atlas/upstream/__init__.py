"""上游组件追新：盘点 Atlas 里所有「别人的东西」，查最新版本，一键（或自动）更新到最新。

- :mod:`.inventory` 自动扫描清单——pyproject / package.json 依赖、Hermes fork、
  git 直引、MCP 启动参数、借鉴代码的来源标注、运行时、已装技能。清单不靠手工登记，
  以后新加的依赖或新借鉴的代码会自动出现。
- :mod:`.check` 查每一项的最新版本，结果缓存在 ``<data>/upstream/status.json``。
- :mod:`.staging` 在仓库旁的「预演副本」里应用更新、跑测试；单项失败自动回退；通过后提交并
  推送。正在用的 Atlas 不受影响，重启（scripts/atlas-update.mjs）时才换上新版本。
- :mod:`.auto` 后台定时检查，开启「自动追新」时检查完直接开始预演。
"""
