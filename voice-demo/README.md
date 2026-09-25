# Atlas 语音对话 Web Demo

基于 **浏览器 STT + 本地双 TTS (IndexTTS-2.5 / F5-TTS) + 高速流式 LLM** 的实时语音对话极简验证方案。

---

## 🚀 极速启动

### 1. 确保 TTS 引擎运行 (二选一或全开)
- **推荐主引擎**：IndexTTS-2.5 (支持 7 位原神/星铁角色音色及细腻情感)
  ```bash
  python D:/AI-Plan-tools/aiplan_indextts_server.py --ensure
  ```
- **备用引擎**：F5-TTS
  ```bash
  python D:/AI-Plan-tools/aiplan_tts_server.py --ensure
  ```

### 2. 启动语音服务
双击运行 `run.bat` 或在终端执行：
```bash
python D:/Atlas/voice-demo/voice_server.py
```

### 3. 打开网页体验
浏览器访问：[http://127.0.0.1:8780](http://127.0.0.1:8780)

---

## 🌟 核心特性
1. **浏览器原生流式 STT**：基于 Web Speech API 实时识别中文语音，零额外本地 STT 显存与 CPU 开销。
2. **标点智能断句与并发合成**：LLM 流式输出根据标点（`。！？；` 及逗号）切分短句，后台异步并发提交 TTS，经音频队列平滑解码播放，首句延迟降低至毫秒级。
3. **双 TTS 自动容灾回退**：优先请求 8792 端口 IndexTTS-2.5，遇超时或离线秒级自动回退至 8791 F5-TTS。
4. **实时打断（Barge-in / Stop）**：说话或点击中止按钮立即清空播放队列并取消服务端正在生成的任务，彻底杜绝重叠自听。
5. **多音色与动态配置**：内置八重神子、雷电将军、夜兰、胡桃、宵宫、流萤、神里绫华等 7 种角色声线，支持前端设置面板实时切换。

---

## 📁 文件架构
```
D:\Atlas\voice-demo\
├── voice_server.py    # WebSocket 胶水层 + HTTP 静态服务 + LLM流式分句 + TTS调度
├── index.html         # 单文件前端：暗黑科技 UI + Web Speech + AudioContext 队列
├── config.json        # 端点端口、LLM 模型与 Prompt 配置
├── run.bat            # 一键启动脚本
└── README.md          # 架构说明与使用指南
```
