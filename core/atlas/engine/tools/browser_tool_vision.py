# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd (MIT).
"""browser_vision helpers: Lightpanda pre-route, native provider vision, auxiliary-LLM screenshot analysis.

Split out of ``tools/browser_tool.py``. Facade-owned state is read through ``_bt`` (``tools.browser_tool``, resolved per call) — no import cycle.
"""

import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from atlas.engine.config import cfg_get
from atlas.engine.tools.browser_tool_origin import origin as _bt
from atlas.engine.tools import browser_tool_cloud as _cloud
from atlas.engine.tools import browser_tool_lightpanda_fallback as _lp


def _vision_mode_label() -> str:
    _cp = _cloud._get_cloud_provider()
    return "local" if _cp is None else f"cloud ({_cp.display_name})"


def _lightpanda_vision_preroute(
    effective_task_id: str, annotate: bool, screenshot_path: Path,
) -> tuple[bool, Optional[str], Path]:
    """Capture the vision screenshot via the Chrome fallback when Lightpanda is the engine
    (it has no graphical renderer). Returns ``(prerouted, fallback_warning, path)``;
    on fallback failure ``prerouted`` is False and the caller takes the normal
    screenshot path (forcing Chrome) so the standard fallback metadata still applies."""
    engine = _cloud._get_browser_engine()
    if engine != "lightpanda" or not _cloud._should_inject_engine(engine):
        return False, None, screenshot_path
    _bt.logger.debug("browser_vision: pre-routing screenshot to Chrome (engine=lightpanda)")
    screenshot_args = ["--annotate"] if annotate else []
    fb_result = _lp._chrome_fallback_screenshot(effective_task_id, screenshot_args, _bt._get_command_timeout())
    fb_result = _lp._annotate_lightpanda_fallback(fb_result, _bt._LP_VISION_FALLBACK_REASON)
    if not fb_result.get("success"):
        _bt.logger.warning("Lightpanda Chrome fallback vision screenshot failed: %s", fb_result.get("error"))
        return False, None, screenshot_path
    fb_path = fb_result.get("data", {}).get("path", "")
    if fb_path and os.path.exists(fb_path):
        import uuid as uuid_mod
        from atlas.engine.atlas_constants import get_atlas_dir

        screenshots_dir = get_atlas_dir("cache/screenshots", "browser_screenshots")
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        persistent_path = screenshots_dir / f"browser_screenshot_{uuid_mod.uuid4().hex}.png"
        shutil.copy2(fb_path, persistent_path)
        screenshot_path = persistent_path
    return True, fb_result.get("fallback_warning"), screenshot_path


def _native_vision_result(
    screenshot_path: Path, question: str, annotate: bool,
    result: dict[str, Any], lp_fallback_warning: Optional[str],
) -> dict[str, Any]:
    """Multimodal tool-result envelope: the main model inspects the pixels itself.

    The embed is baked into history and re-sent every later turn, so apply the same
    proactive resize as vision_analyze's native path (skipped when already under
    both caps; without Pillow it fails open to the raw bytes).
    """
    from atlas.engine.tools.vision_tools import (
        _EMBED_MAX_DIMENSION,
        _build_native_vision_tool_result,
        _resize_image_for_vision,
    )
    from atlas.engine.tools.vision_tools_history_budget import resolve_embed_target_bytes

    data_url = _resize_image_for_vision(screenshot_path, mime_type="image/png",
                                        max_base64_bytes=resolve_embed_target_bytes(),
                                        max_dimension=_EMBED_MAX_DIMENSION, force_jpeg=True)
    native_result = _build_native_vision_tool_result(image_url=str(screenshot_path), question=question,
                                                     image_data_url=data_url,
                                                     image_size_bytes=screenshot_path.stat().st_size)
    meta = native_result.setdefault("meta", {})
    meta["screenshot_path"] = str(screenshot_path)
    if lp_fallback_warning:
        meta["fallback_warning"] = lp_fallback_warning
    if annotate and result.get("data", {}).get("annotations"):
        meta["annotations"] = result["data"]["annotations"]
    native_result["text_summary"] = f"{native_result.get('text_summary', '')} Screenshot path: {screenshot_path}".strip()
    return native_result


def _analyze_screenshot_with_aux_llm(screenshot_path: Path, question: str) -> str:
    """Analyze a captured page with the configured auxiliary vision model.

    The selected conversation model is deliberately not retried for a vision
    request: an image-capability mismatch must use the configured vision route,
    and a missing route is returned as an actionable error.
    """
    import asyncio
    import base64
    import threading

    from atlas.config import get_config
    cfg = get_config()
    model_id = str(cfg.get("computer_use.aux_vision_model", "") or "").strip()
    if not model_id:
        return ('{"success":false,"error":"当前模型不支持图片输入，且没有配置视觉模型。请在设置 → 电脑操作中配置视觉模型后重试。"}')
    encoded = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
    prompt = ("Analyze this browser screenshot and answer the question. Describe visible controls and page state; "
              "do not infer or repeat passwords, authentication tokens, or other secret values.\n\nQuestion: " + question)
    messages = [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
    ]}]

    async def complete() -> str:
        from atlas.models import ModelManager
        manager = ModelManager()
        result = await manager.model_router.complete_for(
            model_id, "vision", messages, temperature=0.1, max_tokens=2048,
        )
        return result.text

    box: list[str] = []
    errors: list[BaseException] = []
    def run() -> None:
        try:
            box.append(asyncio.run(complete()))
        except BaseException as exc:  # hand the provider error back to the tool caller
            errors.append(exc)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        run()
    else:
        worker = threading.Thread(target=run, name="atlas-vision-model", daemon=True)
        worker.start()
        worker.join(timeout=150)
        if worker.is_alive():
            raise TimeoutError("视觉模型分析超时（150 秒）")
    if errors:
        raise RuntimeError(f"视觉模型 {model_id} 调用失败：{errors[0]}") from errors[0]
    from atlas.engine.agent.redact import redact_sensitive_text
    return redact_sensitive_text(box[0] if box else "视觉模型没有返回内容。")




