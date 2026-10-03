# R6：Hermes managed local runtime（llama.cpp/GGUF）研究与 Atlas adapter 方案

- 日期：2026-10-03
- 来源（冻结）：Hermes fork `D:\hermes-agent`（branch `atlas`，HEAD `ef4571dec5`）；Atlas `D:\Atlas`（HEAD `a034bff`）；OpenClaw `D:\Atlas-persistent-sources\openclaw`（HEAD `3e5560873a4`）
- 结论先行：**推荐方案 A（Atlas 进程内 import hermes 包）**——Atlas core 已经以 pinned git 依赖方式安装 hermes-agent 并大量进程内 import（`atlas/engine/hermes_runtime.py`、`hermes_policy.py`），`hermes_cli.local_runtime` 是纯 stdlib+psutil 的库层，没有任何 web/CLI 耦合；Atlas 只需补一层薄 adapter（十几条内部函数 + 一条 FastAPI 子路由 + 一个 activation probe），不复制 local_runtime 任何逻辑代码。

---

## 1. 包全景与公开 API

### 1.1 `hermes_cli/local_runtime/` 模块清单（HEAD ef4571dec5）

| 模块 | 行数 | 职责 | 关键公开符号 |
|---|---|---|---|
| `__init__.py` | 26 | 汇出 | 见下 |
| `binaries.py` | 249 | 后端选择 + PM store 中的引擎定位/安装/旧版收养 | `BACKEND_PACKAGES`, `Engine(backend,tag,binary)`, `BinaryResolutionError`, `runtimes_root()`, `pinned_tag(backend)`, `select_backend(gpu_vendor,os_name)`, `resolve_backend(requested)`, `installed_engine(backend,allow_outdated=True)`, `unavailable_reason`, `adopt_legacy_engine`, `ensure_engine(backend,progress,pause_event,download_progress)` |
| `bootstrap.py` | 502 | 引导：config→引擎→受监督 server；单例 + 跨进程 boot 锁 | `ensure_local_runtime(config,force=False)`（幂等、永不 raise、返回 supervisor 或 None）、`shutdown_local_runtime()`、`get_supervisor()`、`serving_engine()`、`refresh_local_runtime()`（下载/删除后 bounce 重扫）、`models_dir()`、`assets_dir()`、`staged_models()/staged_model_ids()/staged_in()`, `adopt_legacy_models()`, `refit_idle_presets(sup)`, `_detect_gpu_vendor()` |
| `supervisor.py` | 475 | 单个 llama-server（router 模式）进程监督 | `LlamaServerSupervisor`（见 §3）、`state_path()`（`runtimes/llamacpp/server.json`）、`TOUCH_PROMPT/TOUCH_EXPECT`、`_DEFAULT_PORT=18434` |
| `hardware.py` | 485 | 硬件预算探测 | `probe_budget(planning=False)`（planning=True=容量定价，False=live 空闲）、`launch_budget(capacity,own_bytes)`、`_ram_bytes()`, `_cached_nvidia_gpu_query()`（TTL 4s 共享 nvidia-smi 查询）、`_cuda_driver_pool()`（ctypes 加载 nvcuda/libcuda）、`_engine_device_pool()`（引擎自身 `--list-devices`）、`_accelerator_device()`（Vulkan/HIP 引擎设备） |
| `devices.py` | 88 | **新文件**：一次性子进程里问已装引擎看到哪些加速器 | `probe_devices(engine_dir, backend)`→`[{description,type,free,total}]`（`type∈{1=GPU,2=IGPU}`）；可直接 `python -I devices.py <engine_dir> <backend>` 运行；ctypes 加载 ggml-base/ggml/ggml-<backend> 枚举 `ggml_backend_dev_*` |
| `detect.py` | 66 | 发现已在跑的 llama-server | `probe_port(port)`, `detect_server(extra_ports)`, `DetectedServer`, `DEFAULT_PROBE_PORTS=(8080,)`；指纹=`/props` 的 `build_info`（Ollama/LM Studio 答不了） |
| `endpoint.py` | 149 | provider 解析 + 跨进程端点状态 | `resolve_llamacpp_endpoint(config,wait_for_boot_s=8)`（managed→detected→等待 boot）、`managed_root()`, `managed_get_json()`, `_state_endpoint()`（ownership 校验后读 server.json）、`LLAMACPP_ALIASES` |
| `estimator.py` | 195 | 逐层 KV/内存估算 + 物理检查 | `ModelProfile`, `HardwareBudget`, `LayerKind`, `profile_from_gguf(header)`, `ctx_bytes(profile,window)`, `footprint_bytes()`, `physics_check(profile,budget,floor)`→`PhysicsRefusal|None`, `kv_dtype_factor(fa)` |
| `gguf.py` | 239 | 纯 stdlib GGUF 头/张量表读取 | `read_gguf_header(path)`→`GGUFHeader`、`model_id_from_stem()`, `SPLIT_PART_RE`；头字段：`architecture/n_layer/n_ctx_train/head_counts_kv()/sliding_window_pattern/n_vocab/sampling_defaults/ffn_block_bytes` 等 |
| `context_policy.py` | 309 | 窗口阶梯策略（常量非旋钮） | `FLOOR=64K`, `TARGET_WINDOW=144K`, `RUNTIME_OVERHEAD_BYTES≈1.5GiB`, `ladder(native)`, `initial_window(profile,budget)`→`WindowDecision|PhysicsRefusal`, `plan_launch(profile,budget,mtp_capable,fixed_overhead,requested_window)`, `fit_to_free_memory()`, `growth_decision()`, `launch_args()`、`spill_overrides()`（-ot 专家/FFN→CPU）、`ub_logits_bytes()` |
| `presets.py` | 288 | 把策略写成 router 的 `--models-preset` INI | `generate_presets(models_dir,budget,preset_path,live=None)`, `plan_presets`, `preset_for_model(gguf,budget,mtp_capable,requested_window,live)`, `write_presets`, `render_presets`, `read_preset_decisions()`（INI 即启动决策记录）, `resident_footprint()`, `admitted_residency_count()`（驻留上限按字节不按个数） |
| `catalog.py` | 352 | 精选模型目录（预下载定价） | `CATALOG`（打包 `catalog.json` + 6h TTL GitHub 后台刷新）, `CatalogEntry/QuantVariant/AssetFile/VariantChoice`, `select_variant(entry,budget)`, `recommended_entry(budget,entries,backend)`（质量×预测 decode tok/s）, `predicted_decode_tok_s()`, `catalog_by_id()`, `find_entry_for_model()`, `entry_for_model()`, `refresh_catalog_soon()` |
| `hf_browse.py` | 134 | HF 搜索/仓库文件/粗 fit | `search_models(query,limit)`→`HFModelHit`, `repo_files(repo)`→`HFFileGroup`（split 折叠）, `priced_repo_files(repo,budget)`, `rough_fit()` |
| `growth.py` | 140 | 会话内窗口增长 | `maybe_grow_window(model_id,base_url,session_tokens,current_window,measured_decode_tok_s)`、`save/clear/load_window_overrides()`, `is_managed_endpoint(base_url)` |
| `load_progress.py` | 158 | 加载进度（router /models/sse） | `get_loading_progress()`、`get_prefill_progress(model)`；SSE watcher 自动重连，永不 raise |
| `capabilities.py` | 79 | 本地模型能力（视觉）真值 | `is_managed_provider(provider,base_url)`, `managed_model_supports_vision(model_id)`（live `/props?model=` modalities → 目录 mmproj 在盘判定）, `ACCEPTED_IMAGE_MIMES={png,jpeg}` |
| `processes.py` | 142 | Windows Job Object 包裹进程树 + 凭证环境剥离 | `spawn_server(cmd,**kwargs)`（CREATE_SUSPENDED→AssignProcessToJobObject(KILL_ON_JOB_CLOSE)→resume）、`server_child_env(env)`（剔除 `*_API_KEY/*_TOKEN/PASSWORD/...`——OpenMP 崩溃 #116109） |
| `recovery.py` | 182 | state file 孤儿进程的保守恢复 | `read_state()`, `is_modern(state)`, `recorded_process(state)`（pid+create_time+exe+owner 出生身份匹配，防 PID 复用）、`legacy_recorded_process()`、`stop_recorded_orphan()` |

### 1.2 引擎分发与后端（binaries.py + pm）

- 引擎二进制不在 hermes 包里，由 in-repo 包管理器 `pm` 按 `pm/lock.json` 的 SHA-256 pin 分发为**机器级包**：`BACKEND_PACKAGES = {"cuda":"llamacpp-cuda","vulkan":"llamacpp-vulkan","metal":"llamacpp-metal","hip":"llamacpp-hip","cpu":"llamacpp-cpu"}`。
- `ensure_engine()` = `pm.ensure(package, explicit=True, progress, pause_event, download_progress)`：下载→SHA-256 校验→解包进 PM store→记录 facts；`installed_engine()` 只查找从不下载；`adopt_legacy_engine()` 把 pre-PM 安装 `os.rename` 进 store（跨卷则留在原地）。
- `select_backend`：macOS→metal；NVIDIA→cuda；amd/intel/radeon/arc→vulkan；否则 cpu。`resolve_backend("auto")` 带兼容 pin 回退链（如 cuda 缺 pin→vulkan→cpu）。
- 不可用原因可查询：`unavailable_reason(backend,target)`（如 "llamacpp-hip is not pinned for windows-x64"）。
- 目录布局（HERMES_HOME 下）：`runtimes/llamacpp/`（server.json、presets.ini、boot.lock、.api_key、window_overrides.json）、`models/`（staged GGUF）与 `models/assets/`（mmproj/draft）、`logs/llama-server.log`；引擎本体在 PM store（`pm.paths.writable_store_root()`）。

## 2. `hermes_cli/web_routers/local_models.py` 完整端点面（999 行）

请求体模型：`RuntimeInstallBody{backend?}`, `ModelDownloadBody{model_id}`, `JobIdBody{job_id}`, `QuickstartBody{model_id?}`, `ServerActionBody{action}`, `ModelEjectBody{model_id}`, `ModelActivateBody{model_id}`, `BrowsedDownloadBody{repo,paths[]}`, `SideloadBody{path}`。

| 方法 | 路径 | 参数 | 返回（要点） | 行为 |
|---|---|---|---|---|
| GET | `/api/local-models/status` | — | `{enabled,tag,configured_tag,update_available,runtime_installed,runtime_backend,server_running,server_base_url,active_model_id,loaded_models{},loading{},placement{},models[{id,size_bytes,size_label}],models_dir}` | 廉价轮询；含 legacy 模型收养、驻留模型+placement（granted/granted window、spill）、加载中进度 |
| GET | `/api/local-models/hardware` | — | `{uma,vram_total_bytes,vram_usable_bytes,ram_total_bytes,ram_available_bytes,vram_label,gpu_name,gpu_util_percent,vram_used_bytes}` | `probe_budget()` + nvidia-smi 共享缓存（名称/利用率/已用显存，非 N 卡为 null） |
| GET | `/api/local-models/catalog` | — | `{models:[{id,display_name,description,native_context(_label),recommended,recommended_reason,downloaded,downloaded_model_id,downloaded_quant,mtp,vision,needs_engine,min_engine,fits,model_id,quant,quant_validated,size_bytes,size_label,variant_count,quant_reason,start_window(_label),spilled,fit_summary,fit_detail}]}` | 每行给出"这台机器上的最优量化 + 起始窗口 + 是否 spill + 装不下也要解释原因"；planning 预算定价；engine 过老 gate 下载/激活但行仍可见 |
| POST | `/api/local-models/runtime/install` | `{backend?}` + query `profile?` | `{job_id,backend,tag}` | job：`ensure_engine`（下载/解包/校验进度）→ 若引擎变化且 server 在跑则 `refresh_local_runtime()` 换新引擎 |
| POST | `/api/local-models/download` | `{model_id}`（family id 或精确 variant id） | `{job_id,model_id}` 或 `{job_id:null,already_downloaded:true}` | 下载 plan = split 分片 + mmproj/draft 资产；可暂停/恢复；完成后 bounce router |
| POST | `/api/local-models/download/pause` | `{job_id}` | `{ok,paused}` | 仅下载阶段可暂停（chunk 边界） |
| POST | `/api/local-models/download/resume` | `{job_id}` | `{ok,resumed}` | PM 复用已校验文件与 durable ranges |
| DELETE | `/api/local-models/models/{model_id}` | path | `{ok:true}` | 删全部分片+私有资产；清窗口 override；后台 bounce |
| POST | `/api/local-models/quickstart` | `{model_id?}` + `profile?` | `{job_id,model_id,display_name,needs_runtime,needs_download,download_bytes}` | 一键：装 runtime→（装完按引擎设备重新定价）→下载推荐模型→起 server→设默认；同步预检 409（无推荐/装不下/已在跑）；`_QUICKSTART_LOCK` 单飞 |
| POST | `/api/local-models/server` | `{action:"stop"|"start"}` | `{ok,action}` | stop：进程内 supervisor 停或 `recovery.stop_recorded_orphan()`（拒绝动别人的）+ `local_runtime.enabled=false`（持久关）；start：force boot + enabled=true |
| POST | `/api/local-models/eject` | `{model_id}` | `{ok}` | 卸载驻留模型释放显存（supervisor `/models/unload` 或持久端点直调）；demand 自动重载 |
| POST | `/api/local-models/activate` | `{model_id}` + `profile?` | `{job_id}` | 校验已 staged→确保 server 起→rescan bounce→`enabled=true`→写默认模型（**不加载**，residency v2 首次推理才加载） |
| GET | `/api/local-models/jobs` | — | `{jobs:[...]}`（running/paused 优先 + 最近 20 done/error） | job 视图：`{job_id,kind,target,model_id,status,phase,detail,total_bytes,done_bytes,percent,bytes_per_sec,eta_seconds,ranges,can_pause,can_resume,pause_requested,error,started_at}`；8s 平滑速率窗口 |
| GET | `/api/local-models/jobs/{job_id}` | path | job 视图 | 单 job 轮询 |
| GET | `/api/local-models/search` | `q`, `limit=20` | `{hits:[{repo,downloads,likes,updated,gated}]}` | HF 全文 GGUF 搜索（downloads 排序） |
| GET | `/api/local-models/search/files` | `repo` | `{files:[{label,paths[],total_bytes,fit:"fits-gpu"|"needs-ram"|"too-big"|"unknown"}]}` | 仓库内可服务 GGUF 分组（split 折叠、排除 mmproj/draft）+ 粗 fit |
| POST | `/api/local-models/download-browsed` | `{repo,paths[]}` | `{job_id,model_id}` 或 already_downloaded | 任意 HF GGUF 下载进 managed models dir，落地后与目录模型同等待遇（真实 header 生成 preset） |
| POST | `/api/local-models/sideload` | `{path}` | `{ok,model_id,already_present?}` | 本机已有 GGUF：硬链接（跨卷 symlink→copy 兜底）进 managed dir + bounce |

Job 骨架：`_job()/_spawn_job()/_job_view()/_step()/_finish()/_record_rate()`；下载用 `pm.downloader.Download`（同一 resumable 传输）。所有 payload 面向 UI 直显（预格式化事实，不给原始内部值）。

## 3. Supervisor 模型（supervisor.py + bootstrap.py + processes.py + recovery.py）

- **进程模型**：`LlamaServerSupervisor` 持有**一个** `llama-server` router 进程（`--host 127.0.0.1 --port 18434(或 ephemeral) --api-key --models-max N --models-autoload --metrics --slots --no-ui --jinja [dio flags] --models-preset presets.ini`）。router 的 model 子进程由 router 自己管；child 失败经 `GET /models` 的 exit_code 暴露，supervisor 不自动重试 child。
- **启动**：`ensure_local_runtime(config, force=False)` 幂等：disabled→None；已有进程内 supervisor→复用；无 staged 模型→不 boot 空服务器；跨进程 `boot.lock`（fcntl/msvcrt，130s 超时降级）串行化 state-check-then-spawn，输者收养赢者的 state（#116682）。boot 前生成 presets（capacity 定价 + `fit_to_free_memory` live 收窄），失败降级：旧 INI 继续用，首次无 INI 才 stock fit。`start(timeout_s=120)`：spawn→写 state（**spawn 时即写**，不是健康后）→`_wait_health`（/health 200，轮询 1s，进程退出立即报错并附 log 路径）→起 watchdog。
- **健康/崩溃恢复**：watchdog 线程每 2s `poll()`，崩溃按 `(1,5,15,60)s` 退避重启（`_reap_orphaned_children` 先杀孤儿子进程——Windows 上不做二进制匹配式收养，防误杀）；重启后若 `primary_model` 设定则重新 `ensure_model_ready`。`stop()`：进程树终止——Windows 用 Job Object 关闭句柄整体回收 + psutil 先枚举 children 再 terminate（TerminateProcess 不做清理，孤儿会占着 VRAM）。
- **日志**：append 到 `<HERMES_HOME>/logs/llama-server.log`，每次 spawn 写 `# spawn: <cmd>` 行；崩溃信息在异常文本里携带 log 路径。
- **状态文件（managed/shared 之别）**：`server.json` 记 `{base_url,api_key,pid,create_time,executable,owner_pid,owner_create_time}`（出生身份，防 PID 复用；`recovery.recorded_process` 校验）。stable port 18434 + `.api_key` 一次生成永久复用（base_url+api_key 作为整体跨重启稳定，session 恢复依赖）。
  - **managed server**：本进程 `bootstrap.get_supervisor()` 返回非 None——本进程生、本进程管（可 refit/sweep/grow）。
  - **shared server（another-process）**：本进程 supervisor 为 None 但 state file 有效——另一 Hermes/Atlas 进程在管。调用方经持久端点（`_state_endpoint()`/`managed_root()`）走 HTTP（eject/rescan 等都有 fallback 路径）；presets 过期（staged 集变化）时会 stop 旧实例换新（"sessions ride through"）。
- **Idle unload**：`IDLE_UNLOAD_S=15min`；daemon 线程每 30s `refit_idle_presets`（无模型驻留时按 free VRAM 重排窗口，步长 256MiB 防抖）+ 每 120s `sweep_idle()`；idle 判定= `/slots?model=`（`is_processing`）+ `/metrics?model=`（`llamacpp:requests_processing`）三态探针（True/False/None），probe 失败保留时钟不重置。

## 4. 激活/就绪判定（现状 vs 任务书要求）

- **现状**：
  - server 级：`/health` 200（`_wait_health`）；代码注释明确 "health-200 is NOT readiness"。
  - 模型级：`sup.ensure_model_ready(model_id)` = 需要时 `POST /models/load` → **`touch_generate(model_id)`**：真实 `POST /v1/chat/completions`（temp=0，`max_tokens=512`，"Reply with exactly one word: the capital of France."，扫描 `content`+`reasoning_content` 是否含 "paris"，300s 预算）。这是"readiness is a touch generation"契约（`tests/hermes_cli/test_local_runtime.py::test_touch_generate_is_the_readiness_proof`）。
  - 能力探测：`capabilities.py` 查 `/props?model=` 的 `modalities.vision`（视觉）；**没有专门的工具调用探测**——目录条目带 `validated` 标志 + 首载 touch 兜底，但"该模型能否完成一次真实工具调用"无运行时证明。
- **与任务书差距**：任务书要求"激活前必须 health + 一次真实工具调用 probe"。Hermes 已有 health+touch 生成（可视为最简完成度探针）；Atlas adapter 需在 touch 之上加一个 **tool-call probe**（参照 OpenClaw，见 §6.3）：带 `tools:[ping]` + `tool_choice:"required"` 发一次请求，要求返回 tool_call 块——放进 Atlas 的 activation 流程即可，local_runtime 本体不用改。

## 5. Atlas 集成方式评估（选项 A/B/C）

**前置事实**：
- Atlas core（`D:\Atlas\core\pyproject.toml`）**已**依赖 `"hermes-agent @ git+https://github.com/unicorn-Y/hermes-agent.git@7912500ffd..."`，且 `atlas/engine/hermes_runtime.py`/`hermes_policy.py` 已在进程内 import `run_agent`、`hermes_cli.plugins`、`tools.*`、`agent.*`、`gateway.*`，并自管 `HERMES_HOME`。→ 选项 A 的可安装形态**已存在且已验证**。
- 但 pin 是 `7912500ffd`，落后 fork HEAD `ef4571dec5` 整 9 个提交——全是 local-runtime GPU/backend 修复（Intel/AMD GPU 检测 8abd6dc、离散 Vulkan VRAM 4cb33b1、按引擎设备类型定容 2e6924bd、config 读 backend 889a469、CLI 显式 backend boot ffbecdc、共享 server 按调用方 profile 定价 23c1e6b、quickstart 装完引擎再定价 2e62565、Vulkan/HIP 减去他程序占用 c8301ea）。**集成前必须把 pin bump 到 ef4571dec5**。
- 打包形态：`setup.py` 禁止 wheel/sdist（仅 Nix 或 editable）；fork 以 git 依赖（pip/uv 从源码构建 editable）分发正是现状。Python 约束兼容（hermes `>=3.11,<3.15`，Atlas `>=3.14`）；`openai==2.26.0` pin 注释里已写明"Atlas 也装 browser-use==0.13.10，保持同 SDK 线"。
- `local_runtime` 依赖面：stdlib + `psutil` + in-repo `pm/hermes_constants/hermes_platform/agent/utils`——无 fastapi 依赖（只有 web router 层用）；psutil 是 hermes 必装依赖。

**选项 A：进程内 import（推荐）**
- 做法：Atlas 新增 `atlas/engine/local_runtime_adapter.py`（薄层）+ `atlas/api/local_models_router.py`（Atlas 自己的 FastAPI 子路由，直接调 local_runtime 函数）；引擎/模型/端点全走 `hermes_cli.local_runtime`；provider 衔接：启动成功后把 `sup.base_url` + state 里的 `api_key` 写进 Atlas 的 ModelManager（`hermes_provider:"custom"` 或 catalog 新增 `llamacpp` 条目 + `base_url`），`models/catalog.py` 已有 `hermes_provider` 映射机制。
- 优点：单进程、零 HTTP 胶水；`ensure_local_runtime` 幂等永不 raise，天然贴合 Atlas lifespan；supervisor 状态（idle sweep/refit/growth）直接可用；模型分配走 Atlas 自己的 ModelManager（不用 hermes 的 config.yaml `model.provider`）；Windows 部署零额外组件（Job Object/psutil 已在包内）；跨进程安全已内建（boot.lock + state ownership），将来若拆 sidecar 也兼容。
- 缺点/注意：HERMES_HOME 必须在**进程级**固定为一个稳定目录（`hermes_constants.get_default_hermes_root` 有 memo；建议 Atlas 用 `%LOCALAPPDATA%` 级机器目录而非 per-profile engine 目录，使 20GB 模型是机器资产）；不能与正在跑的 Hermes 桌面共享同一 HERMES_HOME 的 18434 端口时可设 `local_runtime.port`；fork 更新需同步 bump pin。

**选项 B：fork 作 sidecar 服务（Atlas 走 HTTP）**
- 做法：跑一个 hermes web_server（或精简 FastAPI 壳）挂 `local_models.router`，Atlas 经 HTTP 调。
- 缺点：多进程部署/守护/升级；hermes router 的"设默认"写的是 hermes config（Atlas 还要再改自己的配置，两份真相）；job 状态在 sidecar 内存里，Atlas 崩溃重启后要靠 `/jobs` 重新发现；Windows 下再开一个常驻 Python 进程徒增故障面。唯一好处是隔离（GIL/崩溃），但 local_runtime 的慢活都在子进程/线程里，Atlas 主进程承担的只是 supervisor 线程 + HTTP 轮询，隔离收益小。
- **仅当** Atlas 未来要把本地推理做成独立 Windows 服务时再考虑；state file + stable port + boot.lock 的设计恰好让 A→B 迁移无痛。

**选项 C：CLI 调用**：fork 的 CLI 面（`hermes`）没有覆盖 install/download/status 的结构化输出，job 进度/暂停恢复在 CLI 无对应命令；放弃。

**推荐**：A。并明确两条纪律：(1) Atlas 不 copy local_runtime 代码，只写 adapter/路由/探测；(2) Atlas 不挂 hermes 的 `local_models.router`（它 import `hermes_cli.web_deps/web_server_config/_CONFIG_MUTATION_LOCK` 且"设默认"写 hermes config），而是在 Atlas 路由里复用同一批 local_runtime 原语（job 骨架 `_job/_spawn_job/_job_view` 这类 UI 胶水需要在 Atlas 侧重写一份薄实现，约 150 行——这是胶水不是逻辑复制）。

## 6. OpenClaw 补强点核对（`extensions/llama-cpp/`，HEAD 3e5560873a4）

1. **Windows 缺 MSVC runtime 的本地补齐**（`src/llama-server-assets.ts` + `src/llama-server-vc-runtime.ts` + `src/llama-server-install.ts`）：
   - 锁定微软官方 VC_redist（x64 14.51.36247 / arm64），URL+SHA256+size+Burn 容器偏移全部 pin 死在 manifest（`WINDOWS_X64_VC_RUNTIME`）。
   - **不装机器级**：用系统自带 `%SystemRoot%\System32\expand.exe` 从 bundle 提取内嵌 CAB，再逐文件展开，只取 `msvcp140.dll / vcruntime140.dll / vcruntime140_1.dll` 放到 llama-server.exe 旁（app-local；注释说明 managed llama-server 跑在 MSIX 包图之外）。
   - 安装流程（`installLlamaServer`）：解压→先跑 `--version`（新解压 macOS 留 120s Gatekeeper 预算）→失败才 stage VC runtime→重试 `--version`→再失败抛 `formatVcRuntimeFallbackError`（"could not start with the installed Windows runtime, and its app-local Visual C++ runtime fallback did not restore it. Rerun setup or configure a compatible llama-server manually"）。发布采用 temp 目录验证→`rename` 到 installDir→最终路径再验一次。
   - 版本/驱动 gate：`validateServerVersionOutput` 要求 `version: ... (build N, commit xxxxxxxxx)` 精确匹配 pin；CUDA 额外 `--list-devices` 必须出现 `CUDA\d+: ...` 行，否则拒绝发布且**明确不静默回退 CPU**；`selectLlamaServerAsset` 预检 NVIDIA 驱动 ≥551.78 且 compute capability ≥5.0（CUDA 12.4 PTX 需要）；Linux 断言 glibc ≥2.34/2.38（musl 报错）。
2. **运行时事实/就绪面**（`src/managed-server.ts::inspectLlamaServerRuntime`）：`LlamaServerRuntimeFacts{state:"ready"|"failed", backend, buildInfo, model, capabilities:{vision,draft}, endpoints:{health,models,props,metrics 各 ready/unavailable}, loadError}` —— 四端点全通才算 ready；`/props` 的 `chat_template_caps.supports_tool_calls` 映射进模型 compat（`external-server/models.ts::buildCompat`）。
3. **激活前的真实工具调用承诺**：`setup.ts:319` 明示 "OpenClaw will check a real tool call before making this your default model"，`model-catalog.ts:276` "Runtime verification checks the actual model before activation"。实现样例在 `src/agents/model-scan.ts::probeModel`：`tools:[{name:"ping"}]` + `toolChoice:"required"`，提示 "Call the ping tool with {} and nothing else."，回复无 toolCall 块即 "No tool call returned" 失败；另有 nonce 双读回探针与拒绝话术分类（`src/gateway/live-tool-probe.test-helpers.ts::hasExpectedToolNonce/isLikelyToolNonceRefusal`）。
4. **Managed server 生命周期**：候选安装用 `isolated:true`（随机 preset 文件 + ephemeral port），**绝不改写活动 server 的重启配置**；preset 修订经 `reconcileManagedLlamaServer` → `GET /models?reload=1`（15s 预算）确认后才标记 applied（"failures stay dirty"）；每次聊天流前 `ensureManagedLlamaServerForChat` 幂等确保模型在缓存/preset 正确。

## 7. Atlas UI 需要的后端 API 清单建议

对照任务书 UI（硬件检测/安装/backend/搜索/下载/导入/fit/context/启停/idle unload/当前 server/错误诊断），建议 Atlas 暴露（路径挂 `/api/local-models/...`，全部为 Atlas 自己的路由，内部调 local_runtime）：

| 端点 | 对应 UI | 底层调用 |
|---|---|---|
| GET `/api/local-models/hardware` | 硬件检测卡片（GPU 名/显存/UMA/RAM/利用率） | `hardware.probe_budget()` + `_cached_nvidia_gpu_query()` + `devices.probe_devices()`（已装引擎时补 AMD/Intel 卡） |
| GET `/api/local-models/backends`（建议新增） | backend 选择器 + 各后端可安装性 | `binaries.resolve_backend/unavailable_reason/pinned_tag/installed_engine`；含 lockfile pin 是否存在 |
| POST `/api/local-models/runtime/install`、GET `/jobs/{id}`、pause/resume | 安装/更新按钮 + 进度 | `binaries.ensure_engine`；job 骨架抄 `local_models._job/_spawn_job` 模式 |
| GET `/api/local-models/catalog` | 目录（每行：尺寸/fit/起始窗口/spill/recommended/needs_engine） | `catalog.CATALOG/select_variant/recommended_entry` + `estimator.physics_check` |
| GET `/api/local-models/search`、`/search/files`；POST `/download-browsed` | HF 浏览/导入（网络侧） | `hf_browse.*` |
| POST `/api/local-models/sideload` | 本地 GGUF 导入 | `bootstrap.models_dir()` + 硬链接 |
| POST `/api/local-models/download` + pause/resume + DELETE `/models/{id}` | 下载/暂停/续传/删除 | `Download` plan（同 `_download_plan`）+ `growth.clear_window_override` |
| GET `/api/local-models/status` | 当前 server 面板（running/base_url/驻留模型/placement/加载进度/active model） | `_state_endpoint`/`get_supervisor`/`load_progress.get_loading_progress`/`presets.read_preset_decisions` |
| POST `/api/local-models/activate` | "启用为默认模型" | boot→`sup.ensure_model_ready`→**Atlas 侧 probe**（touch_generate + tool-call probe，见 §8）→写 ModelManager 默认 |
| POST `/api/local-models/eject` | 立即释放显存 | `sup.unload_model` / 端点直调 `/models/unload` |
| POST `/api/local-models/server {start|stop}` | 引擎总开关（持久） | `ensure_local_runtime(force=True)` / `shutdown_local_runtime()`+`stop_recorded_orphan`；Atlas 配置持久化 `local_runtime.enabled`（见 §8 配置归属） |
| GET `/api/local-models/diagnostics/{job_id 或 server}`（建议新增） | 错误诊断视图 | 读 `logs/llama-server.log` 尾部 + job error + `unavailable_reason`；分类：缺 VC runtime/驱动太旧/引擎过老/端口被占/显存不足 |
| （后台）idle unload | 无 UI，状态面板显示驻留变化 | supervisor 自带 `_start_idle_sweeper`（15min + refit 30s），adapter 无需实现 |

## 8. Atlas 落点建议

1. **Pin bump（前置阻塞项）**：`core/pyproject.toml` 的 `hermes-agent @ git+...@7912500ffd` → `ef4571dec5`（9 个 local-runtime 修复全在gap里）；uv.lock 重新生成，跑 hermes 的 `tests/hermes_cli/test_local_runtime.py` 做冒烟。
2. **HERMES_HOME 策略**：为 local runtime 固定一个**机器级**目录（如 `%LOCALAPPDATA%\Atlas\local-runtime`，内含 `models/`、`runtimes/llamacpp/`、`logs/`），在进程早期 `os.environ["HERMES_HOME"]` 写入并保持恒定（`get_default_hermes_root` 会 memo，切换必须发生在任何 local_runtime 调用前；与现有 `<data>/engine` 的 agent HERMES_HOME 不同值时要避免混用——要么同进程统一一个值，要么把 local runtime 放独立 worker 进程）。
3. **新文件（全部薄层）**：
   - `core/atlas/engine/local_runtime_adapter.py`：包装 `installed_engine/ensure_engine/probe_budget/catalog.*/staged_*/ensure_local_runtime/refresh/shutdown/get_supervisor/ensure_model_ready/touch_generate/sweep_idle/unload_model/resolve_llamacpp_endpoint/hf_browse.*/growth.*`，统一异常→Atlas 错误模型；新增 `probe_tool_call(model_id)`（参照 OpenClaw `probeModel`：`tools=[ping]` + `tool_choice:"required"`，超时 60s，判定 toolCall 块存在）。
   - `core/atlas/api/local_models_router.py`：§7 的端点；job 骨架参照 `local_models.py` 的 `_job/_spawn_job/_job_view/_record_rate`（约 150 行 UI 胶水）。
   - activation 流程（对齐任务书）：ensure server（health）→ `ensure_model_ready`（load+touch）→ `probe_tool_call` → 成功才把 `{provider:"custom"/llamacpp 条目, base_url, api_key, model}` 写入 ModelManager 并持久化默认；probe 失败→保持 server，返回诊断。
4. **Provider 衔接**：`core/atlas/models/catalog.py` 增加 `llamacpp`（`hermes_provider:"custom"`，注明 OpenAI 兼容、无凭据）；ModelManager 激活时从 adapter 取 `base_url/api_key`（state file），供 AIAgent 路由与 litellm（`openai` api_mode + base_url）共用；chat 走现有 hermes provider 机制时也可直接 `provider="llamacpp"` 交给 `resolve_llamacpp_endpoint`。
5. **配置归属**：`local_runtime.enabled/backend/port/detect_ports` 存 Atlas 配置，adapter 在每次调用前合成 `{"local_runtime": {...}}` dict 传给 `ensure_local_runtime`（它只读这一个 section，不依赖 hermes config 文件）；**不要**写 hermes 的 config.yaml，避免两份真相。
6. **Windows 补强（借鉴 OpenClaw，可选二期）**：PM 的 cuda/vulkan 引擎包目前不含 VC redist fallback；若实测 b-pin 引擎在干净 Windows 上因缺 `vcruntime140.dll` 启动失败，按 OpenClaw 方案补：pinned VC_redist 提取 3 个 DLL 放引擎目录旁 + `--version` 失败重试 + 明确诊断文案。现有诊断入口：`_wait_health` 的 rc+log、`unavailable_reason`、supervisor 日志。
7. **测试**：仿 `test_local_runtime.py` 的 stub HTTP server（/props /health /models /slots /metrics /v1/chat/completions + /models/load /models/unload）给 adapter 写契约测试；tool-call probe 用 stub 的 toolCall 响应验证成功/拒绝两路；job 生命周期用 `test_local_quickstart.py` 的 TestClient 模式。

### 风险与开放点
- 进程内共享 HERMES_HOME 与 Atlas 现有 engine home 的冲突（见 §8.2）需要在实现前定案。
- `local_models.py` 的 job 状态是模块级内存态；Atlas 重启后 running job 不可恢复（下载可续传，UI 需按 `already_downloaded` 幂等重发）。
- fork 侧 9 个修复提交未打 tag；建议 fork 上打 `atlas-local-runtime-1` 之类的 tag 再 pin，避免漂移。
- `local_models.py`（web 胶水层）内部名较多且被 quickstart 测试紧耦合引用；fork 上游继续演进时这层会有 API 漂移风险——Atlas adapter 只依赖 `local_runtime` 包的公开面（§1.1），可把漂移面收到最小。
