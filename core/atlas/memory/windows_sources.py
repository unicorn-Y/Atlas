"""WindowsSourceService — 被调 Agent 结果与本地文件导入的真实捕获（UM02 / T02.3）.

契约来源：docs/plan/UNIFIED-MEMORY/01_contracts.md §1.1 / §2 与
02_wave_tasks.md T02.3。**本期职责不是全系统后台监视器** —— 只提供显式入口：
文本文件导入（USER_IMPORT）与被调 Agent 结果记录
（ATLAS_AGENT_TOOL_RESULT / ATLAS_VERIFICATION），全部经
:mod:`atlas.memory.capture` 的既有 outbox 幂等管线入库。

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

import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any

import structlog

from atlas.memory.capture import (
    ContentTooLarge,
    build_observation,
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
                 registry_path: str | Path | None = None) -> None:
        if capture is None:
            from atlas.memory.capture import get_capture_service

            capture = get_capture_service()
        self._capture = capture
        if registry_path is None:
            from atlas.memory.outbox import default_outbox_path

            registry_path = default_outbox_path().parent / DEFAULT_REGISTRY_FILENAME
        self.registry = SourceImportRegistry(registry_path)

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
    "DEFAULT_REGISTRY_FILENAME",
    "MEDIA_EXTENSIONS",
    "MEDIA_LOCATOR_KIND_BY_MIME",
    "MEDIA_MIME_BY_EXTENSION",
    "MAX_IMPORT_SEGMENTS",
    "ImportTooManySegments",
    "ImportUnsupported",
    "SourceImportRegistry",
    "WindowsSourceService",
    "extract_pdf_text",
    "get_windows_source_service",
    "sha256_bytes",
    "slice_paragraphs",
]
