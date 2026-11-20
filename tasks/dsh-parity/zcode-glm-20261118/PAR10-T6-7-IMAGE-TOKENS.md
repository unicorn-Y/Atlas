# PAR-10 · T6-7 任务书 · DeepSeek 图像 token 网格

## 选行与依据

- QUEUE 行:`F06-model` / `B-F06-DEEPSEEK-ADAPTER-01`;已证实缺口 A-5——Atlas 缺 DSH 的图像 token 网格(单图 ≤1024)与请求尺寸投影。
- 依据:`evidence/exec06-f06-adapter-credentials-20261118.txt` §A/§D A-5;DSH 源 `D:\ENGINE-V3-UPSTREAM-20261118\deepseek-harness\packages\llm\llm-deepseek\src\image-tokens.ts` 与 `tests/image-tokens.spec.ts`。

## 工作树

- `D:\Atlas\.worktrees\zcode-par10-image-tokens`
- 分支 `zcode/par10-image-tokens`,HEAD `060071ab`。
- 只写本树与 `evidence/par10-t6-7.md`;主工作区只读;不 commit/push/merge/stash。
- 主树 `core/atlas/models/router.py` 在途;候选树 HEAD 干净。不得改主树。

## 交付

1. 新建 `core/atlas/models/image_tokens.py`,逐行移植 DSH v41 配置:
   - `PATCH_SIZE=14`、`DOWNSAMPLE_RATIO=3`、`MAX_IMAGE_TOKENS=1024`、`MIN_PIXELS=544*544`、`CELL_SIZE=42`;
   - `grid_tokens`、`grid_cells`、`solve_resize_ratio`、`safe_resize`、`resize_once` 与 `deepseek_image_tokens(width,height)`(fixpoint,≤1024);
   - `deepseek_request_image_dimensions(width,height)`(源图可容则原尺寸,否则按 solved 长边做 aspect-preserving;小图不放大,与 DSH 注释/测试一致);
   - 输入非法(0/负/非整数/超大)明确 `ValueError`,不静默。
2. 移植 DSH `tests/image-tokens.spec.ts` 的可见 fixture/边界:1×1、小图、大图、极端宽高比、恰在 1024 边界、超出 cap、fixpoint/非法尺寸;断言与 DSH 完全一致。
3. 可选最小接线:在 `core/atlas/models/router.py` 的预算 `estimate` 中把消息内 image_url/base64 图像按新函数计入(当前只 `estimate_tokens(request_text)` 忽略图像);若主树在途导致 patch 不可直接应用,交付 patch + `git apply --check` 并标链路待接,不改主树。
4. 测试 `core/tests/test_image_tokens.py`(@pytest.mark.unit),不依赖第三方图像库;命令 `--basetemp=<worktree>/.tmp/... -p no:cacheprovider`;记录解释器/版本、完整命令、退出码、通过数;ruff。

## 验收

- 给定宽高返回与 DSH 网格一致 token 数;单图 ≤1024;请求尺寸投影与 DSH 一致;非法输入明确拒绝。
- 若做了 router 接线,给出真实预算路径测试/补丁;否则记录链路待接的文件/行。
- 回执 `evidence/par10-t6-7.md`,末行 `PAR10_RECEIPT T6-7 READY|PARTIAL|BLOCKED`。