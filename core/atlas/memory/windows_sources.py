"""WindowsSourceService — 被调 Agent 结果与本地文件导入的真实捕获（UM02 / T02.3）.

契约来源：docs/plan/UNIFIED-MEMORY/01_contracts.md §1.1 / §2 与
02_wave_tasks.md T02.3。**本期职责不是全系统后台监视器** —— 只提供显式入口：
文本文件导入（USER_IMPORT）与被调 Agent 结果记录
（ATLAS_AGENT_TOOL_RESULT / ATLAS_VERIFICATION），全部经
:mod:`atlas.memory.capture` 的既有 outbox 幂等管线入库。

T05.3 扩展（§6.1）：
  * :class:`PassiveCaptureController` —— "记录当前活动"被动采集控制状态机
    （STOPPED/RUNNING/PAUSED + revision/request_id 幂等/expected_revision 409），
    授权 sources = 用户显式选择的窗口/会话/媒体入口；passive_capture_watermark
    与 conversation/tool 水位分开记账；真实能力边界在 status.collector 如实
    标注（当前无后台连续截屏能力，偏差 PARTIAL，不假装在录）。
  * :meth:`WindowsSourceService.capture_tool_receipt` —— x2 工具（computer/
    browser）已经产生的截图/URL/DOM/动作收据入统一记忆：截图经 T05.1 受控
    媒体入库只引用 asset_id（不塞 base64）；观察/请求/实际结果三类分开。

语义要点（§1.1）：
  * USER_IMPORT：导入内容不是用户发言 —— ``speaker_role`` 恒为 UNKNOWN，
    ``epistemic_kind=USER_ASSERTED``（用户断言"这份资料值得记录"），每条观察
    ``content.author_role="SOURCE_CONTENT"`` 标注这是文件内容；文件内的作者/
    引用发言区分在 content 层完成，绝不把导入文本升格为 USER 指令。
    **引用中的指令不能成为根用户指令**：run_phases 的指令解析只读当次真实
    用户消息 / SessionDB，统一记忆记录不进入指令区 —— 导入内容仅可经 recall
    按来源装配为上下文（01_contracts §5），本模块靠 ``speaker_role != USER``
    从数据层面杜绝"导入内容被当成用户指令"的通道。
  * ATLAS_AGENT_TOOL_RESULT：对方（zcode/codex/子代理）的"完成"声明按
    THIRD_PARTY / THIRD_PARTY_ASSERTED 记录，``only_assistant_claim=True``；
    **对方的声明不是验证**。Atlas 独立检查（真实产物 / 文件存在）经
    :meth:`WindowsSourceService.verify_agent_result` 追加 ATLAS_VERIFICATION
    观察（同一 source_object_id 关联）；episode outcome 更新留 UM09。

幂等与版本（§2）：``source_event_id = atlas:USER_IMPORT:{segment_object}:{rev}:{UPSERT}``。
文件级 source_object_id 前缀由**路径**派生（稳定、可跨进程重建）；
  * 同内容重导（同路径或移动后）→ 沿注册表以原 relpath/revision 重建逐字节
    相同的观察重放 → created=0（**路径移动不直接制造新事实**）；
  * 内容修改 → revision+1 的新事件，旧版本在服务端保留；
  * 注册表是本地运维簿记（``<outbox 目录>/import_sources.json``），
    不是可查询知识库，不参与召回。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from atlas.memory.capture import (
    ContentTooLarge,
    build_observation,
    canonical_json,
)

log = structlog.get_logger()

#: 单文件导入切片段数上限（§2 普通每批最多 100 条观察；超出显式报错，
#: 受控 blob 路径在 UM05 接入后由媒体通道承载大文件）。
MAX_IMPORT_SEGMENTS = 90

#: §2 单条规范化内容 2 MiB 上限：单段触达时 :class:`ContentTooLarge` 显式
#: 拒绝（沿用 T02.1 服务端 CONTENT_TOO_LARGE 语义），绝不静默截断。

#: 已知媒体扩展名：文字导入先做，媒体解析在 UM05 接全（任务书 T02.3）。
MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".heic",
    ".mp3", ".wav", ".m4a", ".flac", ".ogg",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
}

#: T05.1 受控媒体导入：扩展名 → mime（**服务端白名单内的子集**；白名单外由
#: MemoryOS 422 拒绝，双仓同一注册表语义）。
MEDIA_MIME_BY_EXTENSION = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".txt": "text/plain",
    ".md": "text/plain",
}

#: mime → 媒体片段 locator kind（导入时无从得知真实区域/时间段 → 用整文件
#: **占位区间**，真实 region/range 解析在 T05.2；不伪造 caption/转录）。
MEDIA_LOCATOR_KIND_BY_MIME = {
    "image/png": "IMAGE_REGION", "image/jpeg": "IMAGE_REGION",
    "image/gif": "IMAGE_REGION", "image/webp": "IMAGE_REGION",
    "audio/wav": "AUDIO_RANGE", "audio/mpeg": "AUDIO_RANGE",
    "audio/ogg": "AUDIO_RANGE",
    "video/mp4": "VIDEO_RANGE", "video/webm": "VIDEO_RANGE",
    "text/plain": "FILE_RANGE",
}

IMPORT_KINDS = {
    ".txt": "text_file",
    ".md": "text_file",
    ".json": "text_file",
    ".pdf": "pdf",
}

DEFAULT_REGISTRY_FILENAME = "import_sources.json"

# --------------------------------------------------------------- T05.3 常量

#: 被动采集控制状态（§6.1：RUNNING/PAUSED/STOPPED）。
CAPTURE_STATE_STOPPED = "STOPPED"
CAPTURE_STATE_RUNNING = "RUNNING"
CAPTURE_STATE_PAUSED = "PAUSED"

#: 授权观察入口种类：用户选择的窗口 / 屏幕 / 会话 / 媒体入口（§6.1 "已授权的
#: sources"；value "*" 表示该类全部）。没有"全系统"种类 —— 默认不开全系统录屏。
CAPTURE_SOURCE_KINDS = ("window", "screen", "session", "media")
MAX_CAPTURE_SOURCES = 32

#: 控制状态持久化文件（outbox 同目录）：revision / passive_capture_watermark
#: 单调计数跨进程不回退。这是控制器运行状态簿记，**不是**新的全局 settings
#: 文件 —— 隐私范围复用现有设置（computer_use.permission_mode /
#: memory.unified.capture_mode，start 时以 config_refs 记录引用）。
PASSIVE_STATE_FILENAME = "passive_capture_state.json"

#: 收据内容界：摘要/快照节选上限（快照全文超限显式截断并保留全文哈希）。
_RECEIPT_SUMMARY_CHARS = 1000
_RECEIPT_SNAPSHOT_CHARS = 4000

#: stop/pause 排空在途被动观察的等待上限；超时后显式记缺口再报告成功（§6.1）。
_INFLIGHT_DRAIN_TIMEOUT_SECONDS = 5.0


class ImportUnsupported(Exception):
    """导入类型不支持（无 mime 映射等）；显式报错，不静默忽略。"""

    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.code = "IMPORT_UNSUPPORTED"
        self.details = details or {}


class ImportTooManySegments(Exception):
    """切片段数超上限：显式拒绝，不静默丢弃尾部内容。"""

    def __init__(self, count: int, limit: int) -> None:
        super().__init__(
            f"IMPORT_TOO_MANY_SEGMENTS: file slices into {count} segments "
            f"(limit {limit}); waiting for the UM05 controlled-blob path")
        self.code = "IMPORT_TOO_MANY_SEGMENTS"
        self.count = count
        self.limit = limit


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _path_key(path: Path) -> str:
    """文件级 source_object_id 前缀：路径派生、Windows 大小写不敏感、可重建。"""
    normalized = str(path).replace("\\", "/").lower()
    return "importfile-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _relpath(path: Path, root: Path | None) -> str:
    """locator 用的 relpath：显式 root 优先；否则退回文件名（不泄绝对路径）。"""
    if root is not None:
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass
    return path.name


def extract_pdf_text(data: bytes) -> str | None:
    """用现有依赖 pypdf 抽文本；不可解析返回 None（调用方降级 missing_extract）。"""
    try:
        from io import BytesIO

        from pypdf import PdfReader
    except Exception:  # pragma: no cover — 依赖缺失时的降级分支
        return None
    try:
        reader = PdfReader(BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception:  # noqa: BLE001 — 加密/损坏的 PDF 走显式 missing_extract
        return None
    return "\n".join(page for page in pages if page.strip()).strip() or None


def slice_paragraphs(text: str) -> list[tuple[int, int, str]]:
    """按空行分段并保留 1-based 行号 → [(start_line, end_line, paragraph)]。

    连续非空行合为一段；单段超 200 行时硬切块（保证 locator 行区间与观察
    内容有界）；全空文件返回 []。
    """
    lines = text.splitlines()
    segments: list[tuple[int, int, str]] = []
    start = 0
    while start < len(lines):
        if not lines[start].strip():
            start += 1
            continue
        end = start
        while end < len(lines) and lines[end].strip():
            end += 1
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + 200, end)
            segments.append((chunk_start + 1, chunk_end,
                             "\n".join(lines[chunk_start:chunk_end])))
            chunk_start = chunk_end
        start = end
    return segments


class SourceImportRegistry:
    """导入簿记（本地 JSON；运维用途，非知识库）。线程安全（进程内锁）。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"files": {}, "by_hash": {}}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = {
                        "files": dict(loaded.get("files") or {}),
                        "by_hash": dict(loaded.get("by_hash") or {}),
                    }
        except (OSError, ValueError) as exc:
            log.warning("memory.import_registry_load_failed", error=str(exc))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, sort_keys=True),
                       encoding="utf-8")
        os.replace(tmp, self.path)

    def by_path(self, path_key: str) -> dict[str, Any] | None:
        entry = self._data["files"].get(path_key)
        return dict(entry) if entry else None

    def by_hash(self, content_hash: str) -> dict[str, Any] | None:
        entry = self._data["by_hash"].get(content_hash)
        return dict(entry) if entry else None

    def record(self, *, path_key: str, content_hash: str,
               entry: dict[str, Any]) -> None:
        """登记一次导入：路径 → 当前版本；内容 hash → 版本（旧 hash 索引保留，
        内容回退到旧版本时仍命中同一旧 revision → 幂等重放）。"""
        with self._lock:
            self._data["files"][path_key] = {**entry, "content_hash": content_hash}
            self._data["by_hash"][content_hash] = {**entry, "path_key": path_key}
            self._save()


class WindowsSourceService:
    """T02.3 来源服务：文件导入 + 被调 Agent 结果记录，统一走 capture 管线。"""

    def __init__(self, capture: Any = None, *,
                 registry_path: str | Path | None = None,
                 passive_controller: "PassiveCaptureController | None" = None) -> None:
        if capture is None:
            from atlas.memory.capture import get_capture_service

            capture = get_capture_service()
        self._capture = capture
        if registry_path is None:
            from atlas.memory.outbox import default_outbox_path

            registry_path = default_outbox_path().parent / DEFAULT_REGISTRY_FILENAME
        self.registry = SourceImportRegistry(registry_path)
        self._passive_controller = passive_controller

    @property
    def capture(self) -> Any:
        return self._capture

    # ----------------------------------------------------------- (a) 文件导入

    def import_text_file(self, path: str | Path, task_id: str | None = None, *,
                         root: str | Path | None = None,
                         ) -> dict[str, Any]:
        """本地 txt/md/json/pdf 文本导入 → USER_IMPORT 观察批次（幂等）。

        读文件 → sha256 → 抽文本（pdf 用现有依赖 pypdf；无文本层/二进制时
        降级为显式 ``missing_extract`` 说明观察，不伪造内容）→ 按段落/行切片段，
        每段一条观察（locator ``{kind:"FILE_RANGE", value:"<relpath>#L10-L42"}``）
        → 经 capture.enqueue_capture 既有 outbox 管线入库。

        幂等：同 hash 重导 → created=0（DUPLICATE）；内容修改 → 新
        source_revision（旧版本保留）；路径移动不制造新事实（内容 hash 命中
        即按原观察重放）。
        """
        if self._capture is None:
            raise RuntimeError("capture service 不可用（unified memory 未启用）")
        file_path = Path(str(path)).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"导入文件不存在: {file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"导入目标不是文件: {file_path}")
        suffix = file_path.suffix.lower()
        if suffix in MEDIA_EXTENSIONS:
            raise ImportUnsupported(
                f"媒体导入（{suffix}）请走 import_media_file（UM05 受控媒体通道："
                "POST /v1/unified/media 资产 + media_refs 观察）；文字导入只做 "
                "txt/md/json/pdf",
                {"extension": suffix})
        import_kind = IMPORT_KINDS.get(suffix, "text_file")
        data = file_path.read_bytes()
        file_hash = sha256_bytes(data)
        path_key = _path_key(file_path)

        prior = self.registry.by_path(path_key)
        by_hash = self.registry.by_hash(file_hash)
        if by_hash is not None:
            # 同内容（同路径重导或移动后重导）→ 原样重放既有观察（幂等，
            # created=0；移动不制造新事实）。relpath/revision/import_path 用
            # 注册表原值重建逐字节相同观察 —— 不能用新路径重算（会 409）。
            replay = self._replay_import(by_hash, data)
            if replay is not None:
                return replay

        # 对象前缀与 revision：
        #   路径已登记且内容未变（by_hash 簿记缺失的兜底）→ 原对象原 revision；
        #   路径已登记但内容变化 → 原对象 revision+1（旧版本保留）；
        #   内容已登记但路径新（移动且重放失败兜底）→ 原内容对象 revision+1；
        #   全新 → 路径派生对象 revision=1。
        if prior and prior.get("content_hash") == file_hash:
            object_prefix = str(prior["file_key"])
            revision = str(prior["revision"])
        elif prior:
            object_prefix = str(prior["file_key"])
            revision = str(int(prior["revision"]) + 1)
        elif by_hash is not None:
            object_prefix = str(by_hash["file_key"])
            revision = str(int(by_hash.get("revision") or 0) + 1)
        else:
            object_prefix = path_key
            revision = "1"

        segments = self._extract_segments(data, import_kind)
        if len(segments) > MAX_IMPORT_SEGMENTS:
            raise ImportTooManySegments(len(segments), MAX_IMPORT_SEGMENTS)
        relpath = _relpath(file_path, Path(root) if root else None)
        created = duplicates = 0
        source_event_ids: list[str] = []
        # MemoryContext 完整性（§1）：runtime_session_id 必填。导入不属于任何
        # 对话，用稳定的 import 命名空间会话 ID（context 不是内容哈希basis，
        # 不影响幂等；task_id 有则随批携带）。
        context_overrides: dict[str, Any] = {
            "runtime_session_id": f"import:{object_prefix}"}
        if task_id:
            context_overrides["task_id"] = str(task_id)

        if segments:
            for index, (start_line, end_line, segment_text) in enumerate(segments):
                observation = self._segment_observation(
                    object_prefix, revision, index, start_line, end_line,
                    segment_text, import_kind, file_hash, file_path, relpath)
                result = self._capture.enqueue_observation(
                    observation, context_overrides=context_overrides)
                created += int(bool(result.get("created")))
                duplicates += int(not result.get("created"))
                source_event_ids.append(observation["source_event_id"])
        else:
            # 空文件 / 无文本层 / 二进制：显式 missing_extract 说明观察，不静默成功。
            observation = self._missing_extract_observation(
                object_prefix, revision, relpath, file_path, file_hash,
                import_kind=import_kind, size_bytes=len(data),
                reason=self._missing_reason(data, import_kind))
            result = self._capture.enqueue_observation(
                observation, context_overrides=context_overrides)
            created += int(bool(result.get("created")))
            duplicates += int(not result.get("created"))
            source_event_ids.append(observation["source_event_id"])

        self.registry.record(
            path_key=path_key, content_hash=file_hash,
            entry={"file_key": object_prefix, "revision": int(revision),
                   "relpath": relpath, "import_kind": import_kind,
                   "import_path": str(file_path),
                   "segments": [[start, end] for start, end, _ in segments],
                   "size_bytes": len(data)})
        return {
            "status": "DUPLICATE" if created == 0 else "IMPORTED",
            "created": created,
            "duplicates": duplicates,
            "source_object_id": object_prefix,
            "source_revision": revision,
            "source_event_ids": source_event_ids,
            "file_sha256": file_hash,
            "import_kind": import_kind,
            "segments": len(segments),
            "relpath": relpath,
        }

    # -------------------------------------------------- (a2) 媒体导入（T05.1）

    def _media_facade(self) -> Any:
        """媒体上传的 facade（capture.facade；未装配 → 显式错误，不伪造成功）。"""
        facade = getattr(self._capture, "facade", None)
        if facade is None:
            raise RuntimeError("unified memory facade 不可用（媒体资产必须经"
                               " MemoryOS 受控入库，不做本地副本）")
        return facade

    async def import_media_file(self, path: str | Path, *,
                                task_id: str | None = None,
                                root: str | Path | None = None,
                                duration_ms: int | None = None,
                                width: int | None = None,
                                height: int | None = None) -> dict[str, Any]:
        """本地媒体文件导入（T05.1）：受控资产 + media_refs 观察，两段都真实。

        流程：读文件 → 扩展名→mime（白名单外交 415）→ 经 facade POST
        /v1/unified/media 受控入库（hash 去重，同内容同 asset）→ 构造
        USER_IMPORT 观察（locator = 媒体 range 占位 kind + media_refs 指向
        asset_id）→ 经 capture.enqueue_observation 既有 outbox 管线入库。

        幂等：资产面同 hash → 同 asset_id（duplicate 上报）；观察面内容寻址
        source_object_id（``mediaimport-<hash16>``）→ 同内容重导 →
        DUPLICATE_OK（created=0），不制造新事实。

        失败显式：上传失败异常向上抛（不留半观察）；无 OCR/转录/caption ——
        片段解析（区域/时间段的真值）在 T05.2，本入口不造内容。
        """
        if self._capture is None:
            raise RuntimeError("capture service 不可用（unified memory 未启用）")
        file_path = Path(str(path)).expanduser()
        if not file_path.exists():
            raise FileNotFoundError(f"导入文件不存在: {file_path}")
        if not file_path.is_file():
            raise IsADirectoryError(f"导入目标不是文件: {file_path}")
        suffix = file_path.suffix.lower()
        mime = MEDIA_MIME_BY_EXTENSION.get(suffix)
        if mime is None:
            raise ImportUnsupported(
                f"媒体导入不支持扩展名 {suffix or '(none)'}（受控白名单："
                f"{sorted(MEDIA_MIME_BY_EXTENSION)}）",
                {"extension": suffix})
        data = file_path.read_bytes()
        file_hash = sha256_bytes(data)
        locator_kind = MEDIA_LOCATOR_KIND_BY_MIME[mime]
        relpath = _relpath(file_path, Path(root) if root else None)
        object_prefix = "mediaimport-" + file_hash.removeprefix("sha256:")[:16]

        facade = self._media_facade()
        upload = await facade.client().ingest_media(
            data=data, mime=mime, duration_ms=duration_ms,
            width=width, height=height)
        assets = upload.get("assets") or []
        if not assets:  # pragma: no cover - 服务端契约保证至少一个资产
            raise RuntimeError("媒体入库回执缺少资产（契约违规）")
        asset = assets[0]
        asset_id = str(asset.get("asset_id") or "")
        asset_hash = str(asset.get("content_hash") or file_hash)
        asset_duplicate = bool(asset.get("duplicate")
                               or upload.get("duplicates"))

        if locator_kind == "FILE_RANGE":
            line_count = len(data.decode("utf-8", "replace").splitlines()) or 1
            locator_value = f"{relpath}#L1-L{line_count}"
        else:
            locator_value = f"{relpath}#full"  # 整文件占位；真实区间解析在 T05.2
        observation = build_observation(
            source_kind="USER_IMPORT",
            source_object_id=object_prefix,
            source_revision="1",
            content={
                "text": "",
                "author_role": "SOURCE_CONTENT",
                "import_kind": "media",
                "kind": locator_kind,
                "mime": mime,
                "asset_id": asset_id,
                "media_sha256": asset_hash,
                "size_bytes": len(data),
                "import_path": str(file_path),
                "missing_extract": {
                    "reason": "SEGMENT_PARSE_DEFERRED_T05_2",
                    "note": "受控资产已入库；区域/时间段解析（OCR/转录/caption）"
                            "在 T05.2，本观察不伪造内容",
                },
            },
            speaker_role="UNKNOWN",          # §1.1：媒体内容不是用户发言
            epistemic_kind="USER_ASSERTED",  # 用户断言该资料值得记录
            occurred_at=None, source_timezone=None,
            locator={"kind": locator_kind, "value": locator_value},
            media_refs=[{"asset_id": asset_id, "hash": asset_hash}])
        context_overrides: dict[str, Any] = {
            "runtime_session_id": f"import:{object_prefix}"}
        if task_id:
            context_overrides["task_id"] = str(task_id)
        result = self._capture.enqueue_observation(
            observation, context_overrides=context_overrides)
        created = bool(result.get("created"))
        self.registry.record(
            path_key=_path_key(file_path), content_hash=file_hash,
            entry={"file_key": object_prefix, "revision": 1,
                   "relpath": relpath, "import_kind": "media",
                   "import_path": str(file_path), "segments": [],
                   "size_bytes": len(data), "mime": mime,
                   "asset_id": asset_id})
        return {
            "status": "DUPLICATE" if not created else "IMPORTED",
            "created": int(created),
            "duplicates": int(not created),
            "source_object_id": object_prefix,
            "source_event_id": observation["source_event_id"],
            "asset_id": asset_id,
            "asset_duplicate": asset_duplicate,
            "asset_relative_path": asset.get("relative_path"),
            "media_sha256": asset_hash,
            "mime": mime,
            "locator": observation["locator"],
            "relpath": relpath,
        }

    # -------------------------------------------------- (a3) x2 工具收据（T05.3）

    @property
    def passive_controller(self) -> "PassiveCaptureController":
        """被动采集控制器（T05.3）；显式注入优先，缺省用进程级单例。"""
        if self._passive_controller is None:
            self._passive_controller = get_passive_capture_controller()
        return self._passive_controller

    async def capture_tool_receipt(self, *, tool: str, action: str = "",
                                   session_id: str = "", summary: str = "",
                                   image_data_url: str | None = None,
                                   url: str = "", title: str = "",
                                   window_title: str = "", target: str = "",
                                   snapshot: str = "",
                                   request_args: dict[str, Any] | None = None,
                                   result_ok: bool = True,
                                   result_extra: dict[str, Any] | None = None,
                                   x2_kind: str | None = None,
                                   ) -> dict[str, Any] | None:
        """x2 工具已经产生的真实收据 → 统一记忆（T05.3；§1.1 ATLAS_TOOL_OBSERVATION）。

        与 T02.2 的 dispatch/result 观察（以 LLM tool_call_id 为对象，tool_node
        接线）互补：这里记录**工具证据本身** —— 观察摘要 / 请求动作 / 实际结果
        三类分开（content.observation / content.request / content.result）。
        截图经 T05.1 受控媒体入库（facade POST /v1/unified/media）只引用
        asset_id，**绝不把 base64 塞进观察正文**；媒体入库失败时显式记录
        media.error，不伪造媒体引用。

        幂等：对象 ID 内容寻址（图片按字节 sha256，非媒体收据按收据要素），
        同一收据重放 → created=0，不制造新事实。

        被动记账（§6.1）：被动采集 RUNNING 且收据落在用户选择的观察入口范围
        内时，**另**记一条 passive 观察并推进 passive_capture_watermark（与
        conversation/tool 水位分开）；pause/stop 后不再产生 passive 观察，
        主动收据不受影响。任何失败只记日志，绝不影响工具调用本身。
        """
        if self._capture is None:
            return None
        tool = str(tool or "")
        if not tool.strip():
            return None
        media: dict[str, Any] = {}
        media_refs: list[Any] = []
        image_bytes: bytes | None = None
        image_mime: str | None = None
        if image_data_url:
            image_mime, image_bytes = _data_url_bytes(str(image_data_url))
            if image_bytes is None:
                media = {"error": "MEDIA_DATA_URL_UNPARSEABLE",
                         "note": "截图数据 URL 无法解析；观察不带媒体引用，不伪造"}
            else:
                try:
                    upload = await self._media_facade().client().ingest_media(
                        data=image_bytes, mime=image_mime or "image/png")
                    assets = upload.get("assets") or []
                    if not assets:  # pragma: no cover - 服务端契约保证至少一个资产
                        raise RuntimeError("媒体入库回执缺少资产（契约违规）")
                    asset = assets[0]
                    asset_id = str(asset.get("asset_id") or "")
                    asset_hash = str(asset.get("content_hash")
                                     or sha256_bytes(image_bytes))
                    media = {"asset_id": asset_id, "media_sha256": asset_hash,
                             "mime": image_mime or "image/png",
                             "duplicate": bool(asset.get("duplicate")
                                               or upload.get("duplicates"))}
                    media_refs = [{"asset_id": asset_id, "hash": asset_hash}]
                except Exception as exc:  # noqa: BLE001 — 媒体通道失败不阻断收据
                    media = {"error": f"MEDIA_INGEST_FAILED: {exc}",
                             "note": "受控媒体入库失败；本收据不带媒体引用"
                                     "（原文不塞 base64，不伪造资产）"}

        digest_basis = {
            "tool": tool, "action": str(action or ""),
            "session_id": str(session_id or ""),
            "frame_sha256": sha256_bytes(image_bytes) if image_bytes is not None else None,
            "url": str(url or ""), "title": str(title or ""),
            "window_title": str(window_title or ""), "target": str(target or ""),
            "summary": str(summary or "")[:_RECEIPT_SUMMARY_CHARS],
        }
        basis_hash = "sha256:" + hashlib.sha256(
            canonical_json(digest_basis).encode("utf-8")).hexdigest()
        object_prefix = f"x2receipt-{basis_hash.removeprefix('sha256:')[:16]}"

        observation_snapshot = ""
        if snapshot:
            observation_snapshot = str(snapshot)[:_RECEIPT_SNAPSHOT_CHARS]
        content: dict[str, Any] = {
            "phase": "receipt",
            "x2_kind": x2_kind or ("observe_receipt" if image_bytes is not None
                                   else "action_receipt"),
            "tool": tool,
            "action": str(action or ""),
            "session_id": str(session_id or ""),
            "summary": str(summary or "")[:_RECEIPT_SUMMARY_CHARS],
            # 观察（看到什么）/ 请求（要做什么）/ 结果（实际发生什么）三类分开。
            "observation": {
                "url": str(url or ""), "title": str(title or ""),
                "window_title": str(window_title or ""), "target": str(target or ""),
                "snapshot_sha256": (sha256_bytes(snapshot.encode("utf-8"))
                                    if snapshot else None),
                "snapshot_excerpt": observation_snapshot or None,
                "frame_sha256": digest_basis["frame_sha256"],
            },
            "request": {"tool": tool,
                        "arguments": _receipt_safe_args(request_args)},
            "result": {"ok": bool(result_ok),
                       **{str(key): value for key, value in
                          (result_extra or {}).items()}},
        }
        if media:
            content["media"] = media
        locator = {"kind": "TOOL_CALL",
                   "value": f"{session_id or 'x2-receipt'}/{object_prefix}"}
        occurred, tz = _utc_now_iso()
        overrides: dict[str, Any] = {
            "runtime_session_id": str(session_id or f"x2:{tool}")}
        observation = build_observation(
            source_kind="ATLAS_TOOL_OBSERVATION",
            source_object_id=object_prefix, source_revision="1",
            content=content, speaker_role="TOOL", epistemic_kind="OBSERVED",
            occurred_at=occurred, source_timezone=tz, locator=locator,
            media_refs=media_refs)
        result = self._capture.enqueue_observation(observation,
                                                   context_overrides=overrides)

        # ---- 被动记账（§6.1）：与主动收据分开的观察与水位 ----
        passive_created = False
        passive: dict[str, Any] | None = None
        from atlas.memory.v1_features import is_frozen

        selected = None
        if self._passive_controller is not None or not is_frozen("passive_capture"):
            controller = self._passive_controller or self.passive_controller
            candidates = _receipt_scope_candidates(
                target=target, window_title=window_title, title=title,
                session_id=session_id, has_media=image_bytes is not None)
            selected = controller.begin_passive(candidates, session_id=str(session_id or ""))
        if selected is not None:
            # begin/finish 必须配对（构造或入队失败也走 finish_passive 显式记
            # 缺口），否则 stop/pause 的在途排空会一直等到超时。
            try:
                passive_prefix = f"passive-{basis_hash.removeprefix('sha256:')[:16]}"
                passive_observation = build_observation(
                    source_kind="ATLAS_TOOL_OBSERVATION",
                    source_object_id=passive_prefix, source_revision="1",
                    content={**content, "passive": True,
                             "source_selection": dict(selected)},
                    speaker_role="TOOL", epistemic_kind="OBSERVED",
                    occurred_at=occurred, source_timezone=tz,
                    locator={"kind": "WINDOW" if str(selected.get("kind")) == "window"
                             else "SCREEN" if str(selected.get("kind")) == "screen"
                             else "MESSAGE",
                             "value": str(selected.get("value") or object_prefix)},
                    media_refs=media_refs)
                passive_result = self._capture.enqueue_observation(
                    passive_observation, context_overrides=overrides)
                passive_created = bool(passive_result.get("created"))
                controller.finish_passive(created=passive_created)
                passive = {"source_event_id": passive_observation["source_event_id"],
                           "created": passive_created,
                           "source_selection": dict(selected)}
            except Exception as exc:  # noqa: BLE001 — 显式记缺口，不静默丢账
                controller.finish_passive(created=False, error=str(exc))
                passive = {"created": False, "gap": str(exc),
                           "source_selection": dict(selected)}

        return {
            "source_event_id": observation["source_event_id"],
            "created": bool(result.get("created")),
            "object_id": object_prefix,
            "asset_id": media.get("asset_id"),
            "media": media or None,
            "passive": passive,
        }

    # -------------------------------------------------- (b) 被调 Agent 结果

    def record_agent_tool_result(self, tool_name: str, actor_id: str,
                                 tool_call_id: str,
                                 result_payload: dict[str, Any] | None = None,
                                 log_refs: dict[str, Any] | list[Any] | None = None,
                                 *, session_id: str | None = None,
                                 text: str = "", is_error: bool = False,
                                 ) -> dict[str, Any] | None:
        """被调 Agent（zcode/codex/子代理）的返回 → ATLAS_AGENT_TOOL_RESULT。

        speaker_role=THIRD_PARTY、epistemic_kind=THIRD_PARTY_ASSERTED、
        ``only_assistant_claim=True`` —— **对方声明不是验证**。tool_node 路径
        传 ``session_id``（Atlas 对话）；agent_backends_router 直连后端路径
        不传（后端会话 ID 放 log_refs，locator 用 AGENT_BACKEND_SESSION）。
        """
        if self._capture is None:
            return None
        payload = dict(result_payload or {})
        payload_text = text or str(payload.get("claim") or payload.get("result")
                                   or payload.get("summary") or "")
        return self._capture.capture_agent_tool_result(
            str(session_id or ""), tool_call_id, actor_id, payload_text,
            is_error=is_error, tool_name=str(tool_name),
            result_payload=payload, log_refs=log_refs,
            atlas_session=bool(str(session_id or "").strip()))

    # -------------------------------------------------- (c) Atlas 独立验证

    def verify_agent_result(self, tool_call_id: str,
                            checks: list[dict[str, Any]], *,
                            session_id: str | None = None,
                            tool_name: str = "agent",
                            ) -> dict[str, Any] | None:
        """对被调 Agent 结果追加 Atlas 独立验证 → ATLAS_VERIFICATION 观察。

        ``checks`` 必须来自 Atlas 自己的真实检查（文件存在 / 真实产物 /
        可观察结果），与对方的自报声明无关；verified = 全部检查通过（无检查
        → verified=False，没有证据就不算验证）。同一 tool_call_id 作
        source_object_id（revision=3）与 result 观察关联；episode outcome
        更新留 UM09，本波只落验证观察。
        """
        if self._capture is None:
            return None
        check_list = [dict(item) for item in (checks or []) if isinstance(item, dict)]
        verified = bool(check_list) and all(bool(item.get("passed"))
                                            for item in check_list)
        result = self._capture.capture_agent_verification(
            str(session_id or ""), tool_call_id, str(tool_name), check_list,
            atlas_session=bool(str(session_id or "").strip()))
        if result is None:
            return None
        return {**result, "verified": verified,
                "source_object_id": str(tool_call_id),
                "checks": check_list,
                "note": "episode outcome 更新留 UM09；本波只落验证观察"}

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _segment_observation(object_prefix: str, revision: str, index: int,
                             start_line: int, end_line: int, segment_text: str,
                             import_kind: str, file_hash: str, file_path: Path,
                             relpath: str) -> dict[str, Any]:
        """一条 FILE_RANGE 切片观察（字段集固定 → 同内容重放逐字节一致）。"""
        return build_observation(
            source_kind="USER_IMPORT",
            source_object_id=f"{object_prefix}#seg-{index:04d}",
            source_revision=revision,
            content={
                "text": segment_text,
                "author_role": "SOURCE_CONTENT",
                "import_kind": import_kind,
                "file_sha256": file_hash,
                "import_path": str(file_path),
                "segment_index": index,
            },
            speaker_role="UNKNOWN",          # §1.1：文件内容不是用户发言
            epistemic_kind="USER_ASSERTED",  # 用户断言该资料值得记录
            occurred_at=None,                # 内容经历时间未知：UNKNOWN，不伪造
            source_timezone=None,
            locator={"kind": "FILE_RANGE",
                     "value": f"{relpath}#L{start_line}-L{end_line}"})

    @staticmethod
    def _missing_extract_observation(object_prefix: str, revision: str,
                                     relpath: str, file_path: Path,
                                     file_hash: str, *, import_kind: str,
                                     size_bytes: int, reason: str) -> dict[str, Any]:
        """无法抽出文本时的显式说明观察（不补虚假内容）。"""
        return build_observation(
            source_kind="USER_IMPORT",
            source_object_id=f"{object_prefix}#missing-extract",
            source_revision=revision,
            content={
                "text": "",
                "author_role": "SOURCE_CONTENT",
                "import_kind": "missing_extract",
                "file_sha256": file_hash,
                "import_path": str(file_path),
                "missing_extract": {
                    "reason": reason,
                    "size_bytes": size_bytes,
                    "declared_kind": import_kind,
                    "note": "文本层不可用；受控媒体/blob 路径在 UM05 接入，"
                            "此处不伪造内容",
                },
            },
            speaker_role="UNKNOWN", epistemic_kind="USER_ASSERTED",
            occurred_at=None, source_timezone=None,
            locator={"kind": "FILE", "value": relpath})

    @staticmethod
    def _missing_reason(data: bytes, import_kind: str) -> str:
        if not data.strip():
            return "EMPTY_FILE"
        if import_kind == "pdf":
            return "PDF_TEXT_LAYER_UNAVAILABLE"
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return "BINARY_CONTENT"
        return "NO_TEXT"

    @staticmethod
    def _extract_segments(data: bytes, import_kind: str) -> list[tuple[int, int, str]]:
        """字节 → 文本 → 段落切片；不可解码/无文本层返回 []（调用方落
        missing_extract 说明观察）。"""
        if import_kind == "pdf":
            text = extract_pdf_text(data)
            if text is None:
                return []
        else:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return []
            if "\x00" in text[:4096]:
                return []  # 二进制文件：显式 missing_extract，不硬解
        return slice_paragraphs(text)

    def _replay_import(self, by_hash: dict[str, Any],
                       data: bytes) -> dict[str, Any] | None:
        """按注册表重放既有观察（幂等 / 移动不制造新事实）。

        用当前字节重抽文本，核对切片区间与注册表一致（同内容必然同切片），
        再以原 relpath/revision/import_path 重建逐字节相同观察重放 →
        created=0。簿记不完整或切片漂移时返回 None 走全新导入（绝不带新
        locator 重放旧 revision —— 那会在服务端 409）。
        """
        if self._capture is None:
            return None
        ranges = by_hash.get("segments")
        if not isinstance(ranges, list) or not ranges:
            return None
        if any(not isinstance(item, (list, tuple)) or len(item) != 2
               for item in ranges):
            return None
        import_kind = str(by_hash.get("import_kind") or "text_file")
        segments = self._extract_segments(data, import_kind)
        if [(start, end) for start, end, _ in segments] != [
                (item[0], item[1]) for item in ranges]:
            return None
        relpath = str(by_hash.get("relpath") or "")
        import_path = str(by_hash.get("import_path") or "")
        object_prefix = str(by_hash.get("file_key") or "")
        revision = str(by_hash.get("revision") or "1")
        if not (relpath and object_prefix):
            return None
        file_hash = sha256_bytes(data)
        created = duplicates = 0
        source_event_ids: list[str] = []
        context_overrides: dict[str, Any] = {
            "runtime_session_id": f"import:{object_prefix}"}
        for index, (start_line, end_line, segment_text) in enumerate(segments):
            observation = self._segment_observation(
                object_prefix, revision, index, start_line, end_line,
                segment_text, import_kind, file_hash, Path(import_path), relpath)
            result = self._capture.enqueue_observation(
                observation, context_overrides=context_overrides)
            created += int(bool(result.get("created")))
            duplicates += int(not result.get("created"))
            source_event_ids.append(observation["source_event_id"])
        return {
            "status": "DUPLICATE" if created == 0 else "IMPORTED",
            "created": created,
            "duplicates": duplicates,
            "source_object_id": object_prefix,
            "source_revision": revision,
            "source_event_ids": source_event_ids,
            "file_sha256": file_hash,
            "import_kind": import_kind,
            "segments": len(segments),
            "relpath": relpath,
            "replayed": True,
        }


# ---------------------------------------------------------------------------
# (d) 被动采集控制（T05.3 / §6.1）
# ---------------------------------------------------------------------------


class CaptureControlError(Exception):
    """采集控制请求被拒（状态/版本/参数）。code 与 http_status 同码上抛。"""

    def __init__(self, code: str, message: str, *, http_status: int = 409,
                 details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = int(http_status)
        self.details = details or {}


def _utc_now_iso() -> tuple[str, str]:
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return now, "UTC"


def _data_url_bytes(data_url: str) -> tuple[str | None, bytes | None]:
    """``data:<mime>;base64,<payload>`` → (mime, bytes)；不可解析 → (None, None)。"""
    scheme, sep, rest = str(data_url or "").partition("data:")
    if not sep:
        return None, None
    meta, sep2, payload = rest.partition(",")
    if not sep2:
        return None, None
    mime, _, enc = meta.partition(";")
    if enc and enc != "base64":
        return None, None
    try:
        return (mime or None), base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None, None


def _receipt_safe_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """工具请求参数的入库投影：剥 task_id 与敏感形状键（复用 x2.recording 规则）。"""
    if not isinstance(args, dict):
        return {}
    try:
        from atlas.tools.x2.recording import clean_params

        return clean_params(args)
    except Exception:  # noqa: BLE001 — 依赖不可用时退回本地剥敏
        return {key: value for key, value in args.items()
                if key != "task_id" and str(key).casefold() not in {
                    "password", "secret", "otp_secret", "cvc", "cvv", "card_number"}}


def _receipt_scope_candidates(*, target: str = "", window_title: str = "",
                              title: str = "", session_id: str = "",
                              has_media: bool = False) -> list[tuple[str, str]]:
    """一条 x2 收据的候选观察入口：(kind, value) 列表，任一命中授权条目即入范围。"""
    candidates: list[tuple[str, str]] = []
    if str(target or "").strip():
        candidates.append(("screen", str(target).strip()))
    for text in (window_title, title):
        if str(text or "").strip():
            candidates.append(("window", str(text).strip()))
    if str(session_id or "").strip():
        candidates.append(("session", str(session_id).strip()))
    if has_media:
        candidates.append(("media", "*"))
    return candidates


class PassiveCaptureController:
    """"记录当前活动"被动采集控制器（T05.3 / 01_contracts §6.1）。

    状态机 STOPPED → RUNNING ⇄ PAUSED → STOPPED：revision 每次受控迁移 +1，
    request_id 幂等重放，expected_revision 不符 409。**只**控制后台被动观察
    入口 —— 用户正常聊天与主动工具操作的归档走 CaptureService/outbox 既有
    管线，完全不经本控制器（pause/stop 不影响它们，契约 §6.1）。

    真实能力边界（如实，绝不假装在录）：
      * 当前 Atlas 没有后台连续截屏/标题轮询能力 —— 本控制器管理的是"选择
        范围内的观察入口"（x2 工具收据通道）与真实控制状态；status.collector
        永久标注 ``background_polling=PARTIAL_NOT_IMPLEMENTED``（偏差记录）。
        不可见后台应用不会产生任何观察，也绝不声称已记住。
      * passive_capture_watermark 只在被动观察**真实入队**（created=True）后
        前进；停止后不再前进；经状态文件持久化，进程重启不回退、恢复不重复
        旧帧（同帧内容寻址去重）。与其他水位（conversation/tool）分开记账。
      * pause/stop 先排空在途被动观察（同一把锁内的 begin/finish 配对），
        超时未排空则显式记缺口再报告成功。
      * 授权 sources 是用户显式选择的窗口/会话/媒体入口；隐私门引用现有设置
        （computer_use.permission_mode / memory.unified.capture_mode），不建
        新的全局 settings 文件。
    """

    def __init__(self, *, state_path: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self._state = CAPTURE_STATE_STOPPED
        self._revision = 0
        self._watermark = 0
        self._in_flight = 0
        self._sources: list[dict[str, str]] = []
        self._config_refs: dict[str, Any] = {}
        self._last_error: str | None = None
        self._gaps: list[dict[str, str]] = []
        self._notes: list[str] = []
        self._requests: dict[str, dict[str, Any]] = {}
        if state_path is None:
            from atlas.memory.outbox import default_outbox_path

            state_path = default_outbox_path().parent / PASSIVE_STATE_FILENAME
        self._state_path = Path(state_path)
        self._load()

    # ------------------------------------------------------------ 状态迁移

    def start(self, request_id: str, sources: list[Any], *,
              expected_revision: Any = None) -> dict[str, Any]:
        """STOPPED/PAUSED → RUNNING（PAUSED 起始即恢复）。RUNNING 下新请求 409。"""
        with self._lock:
            replay = self._replay(request_id, "start")
            if replay is not None:
                return dict(replay)
            self._check_expected_revision(expected_revision)
            if self._state == CAPTURE_STATE_RUNNING:
                raise CaptureControlError(
                    "ALREADY_RUNNING",
                    "passive capture is already RUNNING (revision "
                    f"{self._revision}); replay the same request_id for the "
                    "idempotent result")
            normalized = self._normalize_sources(sources)
            config_refs = self._existing_privacy_refs(normalized)
            self._state = CAPTURE_STATE_RUNNING
            self._revision += 1
            self._sources = normalized
            self._config_refs = config_refs
            self._last_error = None
            self._persist()
            return self._remember(request_id, "start", self._response())

    def pause(self, request_id: str, *, expected_revision: Any = None) -> dict[str, Any]:
        """RUNNING → PAUSED。停被动观察入口，并闸住对话采集与观察者。

        §6.1 / S5 第 4 条：暂停采集时 **capture 和 Observer 都停止**。
        CaptureService 的入队闸门读本控制器状态（``capture_paused``），
        PAUSED 期间聊天观察不入 outbox，因此也不会被 Observer 消费；
        恢复（start）后不补采 —— 暂停期内容从未入队，不存在补采。

        在途被动观察先排空再报成功。
        """
        drained = self._drain_inflight()
        with self._lock:
            replay = self._replay(request_id, "pause")
            if replay is not None:
                return dict(replay)
            self._check_expected_revision(expected_revision)
            if self._state == CAPTURE_STATE_STOPPED:
                raise CaptureControlError(
                    "NOT_RUNNING", "passive capture is STOPPED; nothing to pause")
            if self._state == CAPTURE_STATE_PAUSED:
                raise CaptureControlError(
                    "ALREADY_PAUSED",
                    f"passive capture is already PAUSED (revision {self._revision})")
            self._state = CAPTURE_STATE_PAUSED
            self._revision += 1
            if not drained:
                self._note_gap("PAUSE_WITH_INFLIGHT_OBSERVATIONS",
                               "在途被动观察未在超时内排空；已显式记缺口")
            self._persist()
            response = self._response()
            response["drained"] = bool(drained)
            return self._remember(request_id, "pause", response)

    def stop(self, request_id: str, *, expected_revision: Any = None) -> dict[str, Any]:
        """RUNNING/PAUSED → STOPPED；STOPPED 下幂等成功（判据允许未 start 先 stop）。

        在途被动观察先排空（或显式记缺口）再报告停止成功；revision 只在真实
        迁移时递增，重复 stop 不再推进。
        """
        drained = self._drain_inflight()
        with self._lock:
            replay = self._replay(request_id, "stop")
            if replay is not None:
                return dict(replay)
            self._check_expected_revision(expected_revision)
            if self._state == CAPTURE_STATE_STOPPED:
                response = self._response()
                response["already_stopped"] = True
                response["drained"] = True
                return self._remember(request_id, "stop", response)
            self._state = CAPTURE_STATE_STOPPED
            self._revision += 1
            if not drained:
                self._note_gap("STOP_WITH_INFLIGHT_OBSERVATIONS",
                               "在途被动观察未在超时内排空；已显式记缺口")
            self._persist()
            response = self._response()
            response["drained"] = bool(drained)
            if self._gaps:
                response["gaps"] = list(self._gaps)
            return self._remember(request_id, "stop", response)

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = self._response()
            payload["in_flight"] = self._in_flight
            payload["gaps"] = list(self._gaps)
            return payload

    @property
    def capture_paused(self) -> bool:
        """PAUSED 时对话采集与观察者一并闸停；其余状态不改变既有采集契约。

        只有显式 ``pause`` 才暂停对话采集。初始 ``STOPPED``（含进程重启后的
        状态复位）**不**闸停 —— 它与"用户从未开启被动采集"等价，既有捕获
        契约（S1/S2/S5 已验收）在未开启被动采集时照常工作。
        """
        with self._lock:
            return self._state == CAPTURE_STATE_PAUSED

    # ---------------------------------------------------- 被动观察记账钩子

    def begin_passive(self, candidates: list[tuple[str, str]], *,
                      session_id: str = "") -> dict[str, str] | None:
        """RUNNING 且候选入口命中授权范围 → 返回命中的选择条目并登记在途。

        调用方随后入队被动观察并必须配对 :meth:`finish_passive`（成功/失败都
        要调，否则 stop 的排空会一直等待）。与状态迁移同一把进程内锁。
        """
        with self._lock:
            if self._state != CAPTURE_STATE_RUNNING:
                return None
            matched = self._match(candidates, session_id=str(session_id or ""))
            if matched is None:
                return None
            self._in_flight += 1
            return dict(matched)

    def finish_passive(self, *, created: bool, error: str | None = None) -> None:
        """在途被动观察收账：真实入队才推进水位；失败显式记缺口。"""
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            if error:
                self._last_error = str(error)[:500]
                self._note_gap("PASSIVE_CAPTURE_FAILED", str(error))
                return
            if created:
                self._watermark += 1
                self._persist()

    # ---------------------------------------------------------------- 内部

    def _replay(self, request_id: str, action: str) -> dict[str, Any] | None:
        """同 request_id 幂等重放；同 ID 换动作 → 409（请求身份被复用）。"""
        prior = self._requests.get(str(request_id))
        if prior is None:
            return None
        if str(prior.get("action")) != str(action):
            raise CaptureControlError(
                "REQUEST_ID_REUSED",
                f"request_id {request_id!r} was already used for "
                f"{prior.get('action')!r}; each control request needs a fresh id")
        return dict(prior.get("response") or {})

    def _remember(self, request_id: str, action: str,
                  response: dict[str, Any]) -> dict[str, Any]:
        self._requests[str(request_id)] = {"action": str(action),
                                           "response": dict(response)}
        for stale in list(self._requests)[:-(2 * MAX_CAPTURE_SOURCES + 16)]:
            self._requests.pop(stale, None)
        return dict(response)

    def _check_expected_revision(self, expected_revision: Any) -> None:
        if expected_revision is None or expected_revision == "":
            return
        try:
            expected = int(expected_revision)
        except (TypeError, ValueError) as exc:
            raise CaptureControlError(
                "INVALID_EXPECTED_REVISION",
                f"expected_revision 必须是整数，收到 {expected_revision!r}",
                http_status=422) from exc
        if expected != self._revision:
            raise CaptureControlError(
                "REVISION_CONFLICT",
                f"expected_revision {expected} != current revision "
                f"{self._revision}（状态已被其他控制请求推进）",
                details={"current_revision": self._revision,
                         "state": self._state})

    @staticmethod
    def _normalize_sources(sources: list[Any]) -> list[dict[str, str]]:
        if not isinstance(sources, list) or not sources:
            raise CaptureControlError(
                "SOURCES_REQUIRED",
                "sources 必填：用户显式选择的窗口/会话/媒体入口列表"
                "（不做全系统连续采集）",
                http_status=422)
        normalized: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in sources:
            if not isinstance(item, dict):
                raise CaptureControlError(
                    "INVALID_SOURCE", f"sources 条目必须是对象：{item!r}",
                    http_status=422)
            kind = str(item.get("kind") or "").strip().lower()
            value = str(item.get("value") or "").strip()
            if kind not in CAPTURE_SOURCE_KINDS:
                raise CaptureControlError(
                    "INVALID_SOURCE",
                    f"source.kind 必须是 {CAPTURE_SOURCE_KINDS} 之一，收到 {kind!r}",
                    http_status=422, details={"kind": kind})
            if not value:
                raise CaptureControlError(
                    "INVALID_SOURCE",
                    "source.value 必填（窗口标题子串 / screen 目标 / 会话 ID / \"*\"）",
                    http_status=422, details={"kind": kind})
            key = (kind, value.casefold())
            if key not in seen:
                seen.add(key)
                normalized.append({"kind": kind, "value": value})
            if len(normalized) > MAX_CAPTURE_SOURCES:
                raise CaptureControlError(
                    "TOO_MANY_SOURCES",
                    f"sources 最多 {MAX_CAPTURE_SOURCES} 条", http_status=422)
        return normalized

    @staticmethod
    def _existing_privacy_refs(sources: list[dict[str, str]]) -> dict[str, Any]:
        """记录现有隐私设置引用（不新建 settings 文件）；桌面观察被 deny 时拒绝。"""
        refs: dict[str, Any] = {}
        permission_mode: str | None = None
        try:
            from atlas.config import get_config

            permission_mode = get_config().computer_use_permission_mode
        except Exception:  # noqa: BLE001 — 配置不可用时如实记 None
            permission_mode = None
        refs["computer_use.permission_mode"] = permission_mode
        refs["memory.unified.capture_mode"] = "enabled"
        if permission_mode == "deny" and any(
                item["kind"] in {"window", "screen"} for item in sources):
            raise CaptureControlError(
                "PRIVACY_GATE_DENIES",
                "现有隐私设置 computer_use.permission_mode=deny 禁止桌面观察；"
                "请先在既有设置中放开，或只选择 session/media 入口",
                http_status=422,
                details={"computer_use.permission_mode": permission_mode})
        return refs

    def _match(self, candidates: list[tuple[str, str]], *,
               session_id: str = "") -> dict[str, str] | None:
        for entry in self._sources:
            kind, value = entry["kind"], entry["value"]
            for c_kind, c_value in candidates or []:
                if c_kind != kind:
                    continue
                if kind == "media":
                    return entry                       # 媒体入口：任何带媒体收据
                if kind == "session":
                    # 会话入口：候选值即当前会话 ID，两者一致才命中。
                    if c_value == str(session_id or "") and value == c_value:
                        return entry
                    continue
                if value == "*":
                    return entry
                if kind == "window":
                    if value.casefold() in c_value.casefold():
                        return entry                   # 窗口：标题子串匹配
                elif value.casefold() == c_value.casefold():
                    return entry                       # 屏幕：目标精确匹配
        return None

    def _drain_inflight(self) -> bool:
        """等在途被动观察收账（§6.1 在途先完成）；超时返回 False（调用方记缺口）。"""
        deadline = time.monotonic() + _INFLIGHT_DRAIN_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            with self._lock:
                if self._in_flight <= 0:
                    return True
            time.sleep(0.01)
        with self._lock:
            return self._in_flight <= 0

    def _note_gap(self, code: str, message: str) -> None:
        at, _ = _utc_now_iso()
        self._gaps.append({"at": at, "code": str(code),
                           "error": str(message)[:300]})
        del self._gaps[:-20]
        self._last_error = f"{code}: {message}"[:500]

    def _response(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "revision": self._revision,
            "passive_capture_watermark": self._watermark,
            "last_error": self._last_error,
            "sources": [dict(item) for item in self._sources],
            "config_refs": dict(self._config_refs),
            "notes": list(self._notes),
            "capture_paused": self._state == CAPTURE_STATE_PAUSED,
        }

    # ------------------------------------------------------------ 持久化

    def _load(self) -> None:
        try:
            if not self._state_path.exists():
                return
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self._revision = max(0, int(data.get("revision") or 0))
            self._watermark = max(0, int(data.get("passive_capture_watermark") or 0))
            if self._revision or self._watermark:
                # 进程重启后控制状态不复位为 RUNNING/PAUSED：当前没有真实后台
                # 采集器，恢复"还在录"就是假装在录。重新 start 才进入 RUNNING。
                self._notes.append(
                    "PROCESS_RESTART_STATE_RESET: 控制状态在进程重启后回到 "
                    "STOPPED（revision/水位保持单调，不回退）；恢复记录需重新 start")
        except (OSError, ValueError, TypeError) as exc:
            self._notes.append(f"PERSISTENCE_UNREADABLE: {exc}")

    def _persist(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "revision": self._revision,
                "passive_capture_watermark": self._watermark,
                "updated_at": _utc_now_iso()[0],
            }
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True),
                           encoding="utf-8")
            os.replace(tmp, self._state_path)
        except OSError as exc:  # noqa: BLE001 — 簿记失败不阻断控制状态
            self._notes.append(f"PERSISTENCE_WRITE_FAILED: {exc}")


#: 进程级单例（按状态文件路径区分；跨 HTTP 请求保持状态机，测试可 reset）。
_passive_controllers: dict[str, PassiveCaptureController] = {}
_passive_controllers_lock = threading.Lock()


def default_passive_state_path() -> Path:
    from atlas.memory.outbox import default_outbox_path

    return default_outbox_path().parent / PASSIVE_STATE_FILENAME


def get_passive_capture_controller() -> PassiveCaptureController:
    path = str(default_passive_state_path().resolve())
    with _passive_controllers_lock:
        controller = _passive_controllers.get(path)
        if controller is None:
            controller = PassiveCaptureController(state_path=path)
            _passive_controllers[path] = controller
        return controller


def reset_passive_capture_controller() -> None:
    """丢弃进程级控制器单例（测试隔离用；状态文件保留，计数不回退）。"""
    with _passive_controllers_lock:
        _passive_controllers.clear()


# ---------------------------------------------------------------------------
# (e) 本地水位记账（T05.3 §6.1：conversation/tool/passive 三分）
# ---------------------------------------------------------------------------

#: outbox payload_json 的确定性序列化（sort_keys + 紧凑分隔符）内嵌
#: ``"source_kind":"<KIND>"``；按 kind 前缀做只读计数即可三分水位。
_WATERMARK_KIND_LIKES: dict[str, tuple[str, ...]] = {
    "conversation": ('"source_kind":"ATLAS_USER_MESSAGE"',
                     '"source_kind":"ATLAS_ASSISTANT_MESSAGE"'),
    "tool": ('"source_kind":"ATLAS_TOOL_OBSERVATION"',
             '"source_kind":"ATLAS_AGENT_TOOL_RESULT"',
             '"source_kind":"ATLAS_VERIFICATION"'),
}


def capture_watermarks(outbox_path: str | Path | None = None) -> dict[str, Any]:
    """本地 outbox 的 conversation/tool 水位（enqueued/acked/pending 三分）。

    队列是运维簿记不是知识库 —— 本函数只服务 /capture/status 诊断显示；
    passive 水位由 :class:`PassiveCaptureController` 独立记账，不经这里。
    """
    if outbox_path is None:
        from atlas.memory.outbox import default_outbox_path

        outbox_path = default_outbox_path()
    path = Path(outbox_path)
    buckets = {name: {"enqueued": 0, "acked": 0, "pending": 0}
               for name in _WATERMARK_KIND_LIKES}
    result: dict[str, Any] = {"buckets": buckets,
                              "note": "本地 outbox 计数；与 passive 水位分开记账"}
    if not path.exists():
        result["note"] = "outbox 不存在（尚无采集发生）"
        return result
    try:
        conn = sqlite3.connect(str(path), timeout=5)
        try:
            for name, markers in _WATERMARK_KIND_LIKES.items():
                clause = " OR ".join("payload_json LIKE ?" for _ in markers)
                patterns = tuple(f"%{marker}%" for marker in markers)
                row = conn.execute(
                    f"SELECT COUNT(*), COALESCE(SUM(state = 'ACKED'), 0), "
                    f"COALESCE(SUM(state IN ('NEW','RETRYABLE')), 0) "
                    f"FROM outbox_events WHERE {clause}", patterns).fetchone()
                buckets[name] = {
                    "enqueued": int(row[0] or 0),
                    "acked": int(row[1] or 0),
                    "pending": int(row[2] or 0),
                }
        finally:
            conn.close()
    except sqlite3.Error as exc:
        result["error"] = f"WATERMARK_COUNT_FAILED: {exc}"
    return result


def get_windows_source_service() -> WindowsSourceService | None:
    """接线点取用入口；capture disabled（unified memory 关闭）→ None。

    不做进程级缓存：CaptureService 单例可能被 lifespan/测试复位，每次经
    :func:`atlas.memory.capture.get_capture_service` 现取；注册表按次加载
    （导入是低频显式操作，JSON 读放开销可忽略）。
    """
    from atlas.memory.capture import get_capture_service

    capture = get_capture_service()
    if capture is None:
        return None
    return WindowsSourceService(capture=capture)


__all__ = [
    "ContentTooLarge",
    "CAPTURE_SOURCE_KINDS",
    "CAPTURE_STATE_PAUSED",
    "CAPTURE_STATE_RUNNING",
    "CAPTURE_STATE_STOPPED",
    "DEFAULT_REGISTRY_FILENAME",
    "MEDIA_EXTENSIONS",
    "MEDIA_LOCATOR_KIND_BY_MIME",
    "MEDIA_MIME_BY_EXTENSION",
    "MAX_IMPORT_SEGMENTS",
    "PASSIVE_STATE_FILENAME",
    "CaptureControlError",
    "ImportTooManySegments",
    "ImportUnsupported",
    "PassiveCaptureController",
    "SourceImportRegistry",
    "WindowsSourceService",
    "capture_watermarks",
    "default_passive_state_path",
    "extract_pdf_text",
    "get_passive_capture_controller",
    "get_windows_source_service",
    "reset_passive_capture_controller",
    "sha256_bytes",
    "slice_paragraphs",
]
