# PAR-10 · T6-9 任务书 · Windows 文件占用下的工作树恢复

## 选行与依据

- QUEUE 行:`PAR09-D2-recovery-boundary`、`PAR10-T4-desktop-candidate`;已证实缺口:`evidence/par10-t4.md` §6——D 未复现真实 OS 级 Windows `Permission denied` 文件锁,清理失败用 monkeypatch 注入。
- 依据:`PAR10-RUNTIME-READY-NEXT.md` §Windows 工作树被文件占用时的恢复;`evidence/par09-d2.md` / `par10-d2` 归属校验实现。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-worktree-windows-lock`
- 分支 `zcode/par10-worktree-windows-lock`,HEAD `060071ab`。
- 从 T4 候选 `D:\Atlas\.worktrees\zcode-par10-desktop-recovery-candidate` 的 D2 最小 diff 起步(写者已停):移入 `core/atlas/api/workspace_router.py`、`core/atlas/memory/__init__.py`、`core/tests/test_conversation_worktree_create.py`、`core/tests/snapshots/routes.json`;逐文件 sha256。
- 主工作区/其他树只读;不 commit/push/merge/stash。

## 任务

1. 用真实 Windows 文件句柄(独立 holder 进程打开并保持 managed worktree 内文件;退出时释放)、临时 Git 仓库、真实已管理 worktree:
   - 注入/触发创建记录失败后,清理遇到真实文件占用 → 响应 `rollback_failed`、recovery 记录含准确 path/branch/base/reason、Git 仍列出残留;
   - 释放句柄后再次请求/显式 recovery → 幂等清理成功,标记清除,可重新 create;
   - 拒绝清理其他临时树/非受管路径,保留归属校验;
   - 正常 create/status/merge/delete、route snapshot。
2. 只有真实平台行为证实产品缺口才做最小修复;保留现有规范化路径/TOCTOU/归属校验;若测试本身无法稳定复现,给出准确 holder 实现、错误输出与平台边界,不冒充。
3. 测试 `@pytest.mark.unit`;命令 `--basetemp=<worktree>/.tmp/... -p no:cacheprovider`;记录解释器/Windows/句柄进程、完整命令、退出码、通过数。

## 验收

- 真实文件占用下回滚失败语义准确、恢复记录可定位;释放后恢复成功;不误删其他树;正常生命周期与快照通过。
- 回执 `evidence/par10-t6-9.md`,末行 `PAR10_RECEIPT T6-9 READY|PARTIAL|BLOCKED`。