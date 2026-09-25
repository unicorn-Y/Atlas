# -*- coding: utf-8 -*-
"""
Atlas Voice Web Demo - Backend Server
Integrates:
- WebSocket & HTTP server (aiohttp)
- LLM streaming with punctuation-based sentence accumulation
- TTS dual routing (8792 IndexTTS-2.5 -> fallback 8791 F5-TTS)
- Voice management (voices.json)
- Barge-in / Interrupt handling
"""

import asyncio
import base64
import json
import os
import re
import sys
import time
import traceback
from typing import Dict, List, Optional, Tuple, Any, cast
import aiohttp
from aiohttp import web
from openai import AsyncOpenAI

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
INDEX_HTML_PATH = os.path.join(os.path.dirname(__file__), "index.html")

# Load configuration
def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] Error reading {CONFIG_PATH}: {e}")
    return {
        "server": {"host": "0.0.0.0", "port": 8780},
        "llm": {
            "api_base": "http://127.0.0.1:8045/v1",
            "api_key": "sk-antigravity",
            "model": "gemini-3.8-flash-low",
            "temperature": 0.7,
            "system_prompt": "你是 Atlas 语音对话助手。口吻温柔自然、口语化，适合语音朗读。回答精炼生动，多用简短句子，避免复杂格式。"
        },
        "tts": {
            "primary_url": "http://127.0.0.1:8792",
            "fallback_url": "http://127.0.0.1:8791",
            "default_voice": "yae_miko",
            "voices_config": "D:/AI-Plan-tools/voices.json"
        }
    }

CONFIG = load_config()

# Load voices metadata
def load_voices() -> dict:
    v_path = CONFIG.get("tts", {}).get("voices_config", "D:/AI-Plan-tools/voices.json")
    if os.path.exists(v_path):
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Voices] Error loading voices from {v_path}: {e}")
    return {
        "yae_miko": {"name": "八重神子", "style": "魅惑骚狐狸·戏谑挑逗", "default_emo": "撒娇", "default_alpha": 0.85},
        "raiden_shogun": {"name": "雷电将军", "style": "高冷女王·威严反差萌", "default_emo": "傲娇", "default_alpha": 0.8},
        "yelan": {"name": "夜兰", "style": "成熟御姐·掌控魅惑", "default_emo": "害羞", "default_alpha": 0.85},
        "hu_tao": {"name": "胡桃", "style": "古灵精怪·俏皮小恶魔", "default_emo": "撒娇", "default_alpha": 0.8},
        "yoimiya": {"name": "宵宫", "style": "元气甜妹·暖床小娇妻", "default_emo": "撒娇", "default_alpha": 0.85},
        "firefly": {"name": "流萤", "style": "纯情软糯·黏人小女友", "default_emo": "撒娇", "default_alpha": 0.8},
        "ayaka": {"name": "神里绫华", "style": "端庄温婉·害羞大小姐", "default_emo": "害羞", "default_alpha": 0.9}
    }

VOICES = load_voices()

def clean_for_tts(text: str) -> str:
    """Strip markdown, actions, emojis and punctuation clutter for smooth TTS speech."""
    t = text
    # Strip markdown bold, italics, code
    t = re.sub(r'[*_#`~]', '', t)
    # Strip links [text](url) -> text
    t = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', t)
    # Strip action descriptions in parentheses e.g. (轻笑) or （脸红）
    t = re.sub(r'[\(（][^\)）]{1,10}[\)）]', '', t)
    # Strip common emojis and symbols
    t = re.sub(r'[\U00010000-\U0010ffff]', '', t)
    t = t.strip()
    return t


class TTSService:
    def __init__(self, primary_url: str, fallback_url: str):
        self.primary_url = primary_url.rstrip("/")
        self.fallback_url = fallback_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def check_health(self) -> dict:
        sess = await self.get_session()
        res = {"primary": False, "fallback": False}

        async def check_one(url, key):
            try:
                async with sess.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=0.6)) as r:
                    res[key] = (r.status == 200)
            except Exception:
                pass

        await asyncio.gather(
            check_one(self.primary_url, "primary"),
            check_one(self.fallback_url, "fallback")
        )
        return res

    async def synthesize(self, text: str, voice_key: str) -> Optional[bytes]:
        clean_text = clean_for_tts(text)
        if not clean_text:
            return None

        sess = await self.get_session()
        voice_info = VOICES.get(voice_key, {})
        
        # 1. Try Primary (8792 IndexTTS-2.5)
        try:
            payload = {
                "text": clean_text,
                "spk": voice_info.get("seed_path", ""),
                "emo_text": voice_info.get("default_emo", "撒娇"),
                "use_emo_text": True,
                "emo_alpha": voice_info.get("default_alpha", 0.85)
            }
            async with sess.post(f"{self.primary_url}/say", json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    data = await r.read()
                    if len(data) > 100:
                        return data
                print(f"[TTS] Primary 8792 returned status {r.status}")
        except Exception as e:
            print(f"[TTS] Primary 8792 call failed: {e}")

        # 2. Fallback to 8791 (F5-TTS)
        try:
            payload = {"text": clean_text, "speed": 1.0}
            async with sess.post(f"{self.fallback_url}/say", json=payload, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 200:
                    data = await r.read()
                    if len(data) > 100:
                        print(f"[TTS] Fallback 8791 synthesized successfully for: {clean_text[:12]}")
                        return data
                print(f"[TTS] Fallback 8791 returned status {r.status}")
        except Exception as e:
            print(f"[TTS] Fallback 8791 call failed: {e}")

        return None


tts_service = TTSService(
    CONFIG.get("tts", {}).get("primary_url", "http://127.0.0.1:8792"),
    CONFIG.get("tts", {}).get("fallback_url", "http://127.0.0.1:8791")
)


class VoiceSession:
    def __init__(self, ws: web.WebSocketResponse):
        self.ws = ws
        self.active_voice = CONFIG.get("tts", {}).get("default_voice", "yae_miko")
        self.llm_model = CONFIG.get("llm", {}).get("model", "gemini-3.8-flash-low")
        self.system_prompt = CONFIG.get("llm", {}).get("system_prompt", "")
        self.temperature = CONFIG.get("llm", {}).get("temperature", 0.7)
        self.history: List[Dict[str, str]] = []
        self.current_generation_task: Optional[asyncio.Task] = None
        self.is_interrupted = False

    async def send_json(self, data: dict):
        if not self.ws.closed:
            try:
                await self.ws.send_str(json.dumps(data, ensure_ascii=False))
            except Exception as e:
                print(f"[WS] Send error: {e}")

    async def stop(self):
        """Handle interrupt / barge-in."""
        self.is_interrupted = True
        if self.current_generation_task and not self.current_generation_task.done():
            self.current_generation_task.cancel()
            try:
                await self.current_generation_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[Session] Error canceling task: {e}")
        self.current_generation_task = None
        await self.send_json({"type": "status", "status": "idle"})

    def cut_sentences(self, buffer: str) -> Tuple[List[str], str]:
        """Split text stream into sentences on punctuation boundaries."""
        sentences = []
        # Punctuation set
        major_puncts = set("。！？；!?;\n")
        minor_puncts = set("，,")
        
        start = 0
        n = len(buffer)
        for i, ch in enumerate(buffer):
            segment_len = i - start + 1
            if ch in major_puncts and segment_len >= 4:
                sentences.append(buffer[start:i+1].strip())
                start = i + 1
            elif ch in minor_puncts and segment_len >= 10:
                sentences.append(buffer[start:i+1].strip())
                start = i + 1
            elif segment_len >= 26:
                # Force cut long sentence if exceeding threshold
                sentences.append(buffer[start:i+1].strip())
                start = i + 1
        
        remaining = buffer[start:]
        return sentences, remaining

    async def handle_user_text(self, text: str):
        text = text.strip()
        if not text:
            return

        # Interrupt any ongoing playback/generation first
        await self.stop()
        self.is_interrupted = False

        self.history.append({"role": "user", "content": text})
        # Keep history bounded
        if len(self.history) > 16:
            self.history = self.history[-16:]

        self.current_generation_task = asyncio.create_task(self._generate_and_speak(text))

    async def _generate_and_speak(self, user_text: str):
        await self.send_json({"type": "status", "status": "thinking"})
        
        client = AsyncOpenAI(
            base_url=CONFIG.get("llm", {}).get("api_base", "http://127.0.0.1:8045/v1"),
            api_key=CONFIG.get("llm", {}).get("api_key", "sk-antigravity")
        )

        messages = cast(Any, [{"role": "system", "content": self.system_prompt}] + self.history)

        # Audio sequencing queue
        audio_queue = asyncio.Queue()
        
        async def audio_dispatcher():
            """Ensures audio chunks are sent sequentially over WS to the client."""
            while True:
                item = await audio_queue.get()
                if item is None:
                    break
                future_audio, chunk_text, is_final = item
                try:
                    wav_bytes = await future_audio
                    if self.is_interrupted:
                        break
                    if wav_bytes:
                        b64_audio = base64.b64encode(wav_bytes).decode("ascii")
                        await self.send_json({
                            "type": "ai_audio",
                            "data": b64_audio,
                            "text": chunk_text,
                            "voice": self.active_voice
                        })
                        await self.send_json({"type": "status", "status": "speaking"})
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Dispatcher] Audio synthesis error: {e}")
                finally:
                    audio_queue.task_done()

        dispatcher_task = asyncio.create_task(audio_dispatcher())

        full_ai_response = []
        raw_buffer = ""

        try:
            response = await client.chat.completions.create(
                model=self.llm_model,
                messages=messages,
                stream=True,
                temperature=self.temperature
            )

            async for chunk in response:
                if self.is_interrupted:
                    break
                content = chunk.choices[0].delta.content if chunk.choices else ""
                if not content:
                    continue

                full_ai_response.append(content)
                raw_buffer += content

                # Check if we have complete sentences
                sentences, raw_buffer = self.cut_sentences(raw_buffer)
                for sentence in sentences:
                    if self.is_interrupted:
                        break
                    # Send partial text to frontend UI
                    await self.send_json({"type": "ai_text", "text": sentence, "final": False})
                    # Schedule TTS synthesis concurrently, preserve order via queue
                    synth_task = asyncio.create_task(tts_service.synthesize(sentence, self.active_voice))
                    await audio_queue.put((synth_task, sentence, False))

            # Process remainder buffer
            if not self.is_interrupted and raw_buffer.strip():
                rem = raw_buffer.strip()
                await self.send_json({"type": "ai_text", "text": rem, "final": True})
                synth_task = asyncio.create_task(tts_service.synthesize(rem, self.active_voice))
                await audio_queue.put((synth_task, rem, True))
            else:
                await self.send_json({"type": "ai_text", "text": "", "final": True})

            # Signal end of audio queue
            await audio_queue.put(None)
            await dispatcher_task

            # Save to history
            complete_ai_text = "".join(full_ai_response).strip()
            if complete_ai_text:
                self.history.append({"role": "assistant", "content": complete_ai_text})

        except asyncio.CancelledError:
            pass
        except Exception as e:
            traceback.print_exc()
            await self.send_json({"type": "error", "message": f"LLM/TTS Error: {str(e)}"})
        finally:
            if not dispatcher_task.done():
                dispatcher_task.cancel()
            if not self.is_interrupted:
                await self.send_json({"type": "status", "status": "idle"})


# HTTP Handlers
async def index_handler(request: web.Request) -> web.Response:
    if os.path.exists(INDEX_HTML_PATH):
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            return web.Response(text=f.read(), content_type="text/html")
    return web.Response(text="<h1>Atlas Voice Demo: index.html not found.</h1>", content_type="text/html")

async def health_handler(request: web.Request) -> web.Response:
    tts_status = await tts_service.check_health()
    return web.json_response({
        "status": "ok",
        "tts": tts_status,
        "voices_count": len(VOICES)
    })

async def voices_handler(request: web.Request) -> web.Response:
    return web.json_response(VOICES)

async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    session = VoiceSession(ws)
    print(f"[WS] Client connected from {request.remote}")

    # Send initial state
    tts_health = await tts_service.check_health()
    await session.send_json({
        "type": "init",
        "voices": VOICES,
        "current_voice": session.active_voice,
        "model": session.llm_model,
        "tts_status": tts_health,
        "system_prompt": session.system_prompt
    })

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                except Exception:
                    continue

                msg_type = data.get("type")
                if msg_type == "user_text":
                    await session.handle_user_text(data.get("text", ""))
                elif msg_type == "stop":
                    await session.stop()
                elif msg_type == "config":
                    if "voice" in data and data["voice"] in VOICES:
                        session.active_voice = data["voice"]
                    if "model" in data:
                        session.llm_model = data["model"]
                    if "system_prompt" in data:
                        session.system_prompt = data["system_prompt"]
                    if "temperature" in data:
                        session.temperature = float(data["temperature"])
                    await session.send_json({"type": "config_updated", "voice": session.active_voice, "model": session.llm_model})
                elif msg_type == "clear_history":
                    session.history.clear()
                    await session.send_json({"type": "history_cleared"})

            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.ERROR):
                break
    finally:
        await session.stop()
        print(f"[WS] Client disconnected {request.remote}")

    return ws


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/api/health", health_handler)
    app.router.add_get("/api/voices", voices_handler)
    app.router.add_get("/ws", websocket_handler)
    return app


if __name__ == "__main__":
    host = CONFIG.get("server", {}).get("host", "0.0.0.0")
    port = CONFIG.get("server", {}).get("port", 8780)
    print(f"=================================================")
    print(f"  Atlas Voice Web Demo Server")
    print(f"  Web UI:    http://127.0.0.1:{port}/")
    print(f"  WebSocket: ws://127.0.0.1:{port}/ws")
    print(f"  TTS Pri:   {CONFIG.get('tts', {}).get('primary_url')}")
    print(f"  TTS Fall:  {CONFIG.get('tts', {}).get('fallback_url')}")
    print(f"=================================================")
    app = create_app()
    web.run_app(app, host=host, port=port)
