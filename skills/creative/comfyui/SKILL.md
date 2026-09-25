---
name: comfyui
description: "Generate images, video, audio via ComfyUI diffusion workflows."
version: 1.0.0
category: creative
triggers:
  - pattern: "comfyui|stable.?diffusion|flux|sdxl|生图|画图|AI.*图|txt2img|img2img"
  - pattern: "生成.*图片|图片.*生成|diffusion"
  - command: "/comfyui"
dependencies:
  commands:
    - python
author: Atlas
tags: [comfyui, image-generation, stable-diffusion, flux, sdxl, video-generation, creative, generative-ai]
related_skills: []
---

# ComfyUI

Generate images, video, audio, and 3D content through ComfyUI using `comfy-cli` for setup/lifecycle and REST/WebSocket API for workflow execution.

## When to Use

- 用 Stable Diffusion / SDXL / Flux / SD3 生成图片
- 运行 ComfyUI workflow 文件
- 链式生成：txt2img → upscale → face restore
- ControlNet、inpainting、img2img 等高级 pipeline
- 视频/音频/3D 生成（AnimateDiff, Hunyuan, Wan）
- NOT for: 在线 AI 图片生成服务（直接调 API）

## Architecture

```
┌─────────────────────────────────────────────────┐
│ Layer 1: comfy-cli (lifecycle)                  │
│   comfy install / launch / stop / node / model  │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│ Layer 2: REST/WS API + scripts                  │
│   POST /api/prompt, GET /api/view, WS /ws       │
│   run_workflow.py, run_batch.py, ws_monitor.py  │
└─────────────────────────────────────────────────┘
```

## Prerequisites

- NVIDIA GPU with 4GB+ VRAM (8GB+ recommended)
- Python 3.10+
- ComfyUI installed via `comfy install`
- `comfy-cli` installed via `pipx install comfy-cli` or `uvx comfy-cli`

## Instructions

### Quick Start

```bash
# Check hardware capability
python scripts/hardware_check.py

# Full setup (hardware check + install + launch + verify)
bash scripts/comfyui_setup.sh

# Health check
python scripts/health_check.py
```

### Running Workflows

```bash
# Extract controllable params from a workflow
python scripts/extract_schema.py workflow.json

# Check deps against running server
python scripts/check_deps.py workflow.json

# Auto-fix missing nodes/models
python scripts/auto_fix_deps.py workflow.json

# Run workflow with custom params
python scripts/run_workflow.py workflow.json --params '{"seed": 42, "prompt": "a cat"}'

# Batch run with parameter sweeps
python scripts/run_batch.py workflow.json --count 4 --sweep '{"seed": [1,2,3,4]}'

# Monitor execution in real-time
python scripts/ws_monitor.py
```

### Server Management

```bash
comfy launch --background    # start server
comfy stop                   # stop server
comfy node install <name>    # install custom nodes
comfy model download <url>   # download models
```

### Available Example Workflows

SD 1.5, SDXL, Flux Dev, SDXL img2img, SDXL inpaint, ESRGAN upscale, AnimateDiff video, Wan T2V.

## Script Reference

| Script | Purpose |
|--------|---------|
| `hardware_check.py` | GPU/VRAM/disk check → local vs cloud |
| `comfyui_setup.sh` | Full install + launch + verify |
| `extract_schema.py` | List controllable params + model deps |
| `check_deps.py` | Check workflow deps against server |
| `auto_fix_deps.py` | Auto-install missing nodes/models |
| `run_workflow.py` | Inject params, submit, monitor, download |
| `run_batch.py` | Batch runs with sweeps |
| `ws_monitor.py` | Real-time WebSocket progress viewer |
| `health_check.py` | Full verification checklist |
| `fetch_logs.py` | Pull traceback for a prompt_id |
