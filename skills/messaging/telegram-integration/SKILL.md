---
name: telegram-integration
description: "Telethon 接入 Telegram：代理/扫码/验证码/session 管理。"
version: 1.0.0
category: messaging
triggers:
  - pattern: "telegram|tg|telethon|电报"
  - command: "/telegram"
dependencies:
  python_packages:
    - telethon
    - pysocks
    - qrcode
author: Atlas
tags: [telegram, telethon, messaging, proxy]
related_skills: []
---

# Telegram / Telethon 集成

Telethon 脚本方式接入 Telegram。核心三件事：**连接必须挂代理、登录凭证要选对、session 一次登录永久复用**。

## When to Use

- 用户要用 Telegram 收发消息、爬群、捞图
- 需要 Telegram Bot 或用户 API 操作
- NOT for: 微信（用其他技能）

## Prerequisites

- Python 3.10+ with `telethon`, `pysocks`, `qrcode`
- Clash 或其他代理运行中（本机直连 Telegram 会超时）

## Instructions

### 环境与代理（必做，直连必超时）

本机在墙内，Telegram 服务器直连必 `TimeoutError`。Clash 混合端口 `127.0.0.1:7897`：

```python
import socks
from telethon import TelegramClient

client = TelegramClient(
    SESSION, API_ID, API_HASH,
    proxy=(socks.SOCKS5, "127.0.0.1", 7897),
    connection_retries=3, request_retries=3, timeout=30,
    device_model="Telegram Android", app_version="10.14.2",
    system_version="Android 14", lang_code="zh",
)
```

先验代理端口：`echo > /dev/tcp/127.0.0.1/7897`。连接超时 = 没走代理。

### 登录三路径（按优先级）

#### 路径 1：自有 api_id（最稳，推荐）
- 去 **https://my.telegram.org** → **API development tools** → Create application
- 登录可用扫码：用已登录的桌面 TG 确认——不需要短信验证码
- 拿到自己的 `api_id`/`api_hash` 后用路径 2/3 登录

#### 路径 2：QR 扫码登录
```python
qr_login = await client.qr_login()
await qr_login.wait_for_qr_ready()
token = qr_login.token
img = qrcode.make(token); img.save(QR_PATH)
await asyncio.wait_for(qr_login.wait(), timeout=300)
```

#### 路径 3：验证码登录（备选）
`client.send_code_request(phone)` → 验证码推到已登录设备 → `client.sign_in(phone, code)`

### 已知坑（实测）

1. **公共 api_id=6 扫码被风控**：手机扫出提示错误，重试无效。直接走路径 1 拿自有凭证。
2. **session 文件是金矿**：登录成功后 session 存本地，以后 `is_user_authorized()` 为真，免登录。别每次重登。
3. 公共凭证连验证码也可能收不到，路径 1 是长期方案。

### 验证

- 连接成功：脚本打 QR 码且 PNG 文件存在
- 登录成功：日志 `LOGIN SUCCESS!` 或标记文件存在
- 复用：`client.is_user_authorized()` 为 True
