# AI Watcher

**Turn any ONVIF camera into an AI watcher.**

让一个普通的 ONVIF 摄像头，变成一个会看、会转、会定时巡检、还能带图汇报的 **AI 视觉节点**。

`AI Watcher` 面向 **OpenClaw** 工作流设计。它把摄像头连接、RTSP 获取、PTZ 控制、定时巡检和基于截图的分析串成一条可执行链路，适合那些想让 Agent 真正“持续盯现场”的场景。

**No app. No cloud dashboard. No heavy setup.**  
只要你的摄像头支持 ONVIF，就可以很快接入。

## Why people may want this

很多项目都能“连上摄像头”，但很少项目真正解决下面这个问题：**连上之后，怎样把摄像头变成 Agent 可持续调用的视觉能力，而不是一次性 demo。**

这个仓库的重点不是花哨 UI，而是把几个关键能力做好：

| 你需要的结果 | AI Watcher 提供什么 |
| --- | --- |
| 让 Agent 看现场 | 获取 RTSP / Snapshot URI，接入图像分析链路 |
| 让 Agent 改变视角 | 支持 PTZ 控制、停止与归位 |
| 让 Agent 定时巡检 | 可接入 OpenClaw Heartbeat 做周期任务 |
| 让结果可信 | 分析必须基于真实截图，强调附图返回 |
| 让部署不折腾 | 安装和配置都尽量保持轻量 |

## What it does

| 能力 | 说明 |
| --- | --- |
| Camera info | 读取摄像头厂商、型号、固件版本、序列号 |
| Stream URI | 获取 RTSP 视频流地址 |
| Snapshot URI | 获取快照地址 |
| PTZ control | 上下左右、缩放、停止、归位 |
| Conversational setup | 可由 Agent 通过对话引导完成配置 |
| Watcher workflow | 可扩展成定时巡检和异常看护任务 |

## Install with an agent

把这个仓库交给你的 Agent，然后说一句：

> 帮我安装并配置 AI-watcher

Agent 会完成依赖安装，并引导你填写摄像头的 IP、端口、用户名和密码。

如果你的环境已经接好了 OpenClaw，这通常就是最简单的接入方式。

## Manual setup

如果你想手动安装，也只需要几步。

### 1. Clone the repo

```bash
git clone https://github.com/Vibetool/AI-watcher.git
cd AI-watcher
```

### 2. Install dependencies

```bash
bash scripts/setup.sh
```

### 3. Create your local camera config

复制示例配置，并填入你的摄像头信息。

```bash
cp scripts/config.example.ini scripts/config.ini
```

然后编辑 `scripts/config.ini`：

```ini
[camera]
ip = 192.168.1.100
port = 80
username = your_username
password = your_password
```

### 4. Test the connection

```bash
python3 scripts/onvif_ctrl.py info
python3 scripts/onvif_ctrl.py stream_uri
python3 scripts/onvif_ctrl.py snapshot_uri
python3 scripts/onvif_ctrl.py ptz --act left --duration 1.0
```

如果能正常返回 JSON，说明摄像头已经接好了。

## How it feels in practice

你可以把它理解成一个给 Agent 使用的“摄像头动作层”。

```text
用户说：去看一下办公室门口有没有人
-> Agent 读取摄像头配置
-> 获取视频流或截图
-> 如有需要，控制 PTZ 转向
-> 基于真实画面做分析
-> 返回结论，并附上截图证据
```

这比单纯返回一个 RTSP 地址更有用，因为它更接近真实的自动巡检流程。

## Good use cases

| 场景 | 这个仓库能帮你做什么 |
| --- | --- |
| 办公室夜间看护 | 定时抓拍，发现异常活动时汇报 |
| 仓库或门店巡检 | 按时间检查特定区域状态 |
| 老人 / 宠物看护 | 定点查看并输出简短结论 |
| 安防原型验证 | 作为更复杂 Agent 巡检系统的底座 |

## Project structure

| 路径 | 作用 |
| --- | --- |
| `README.md` | 项目说明 |
| `SKILL.md` | 面向 Agent 的技能说明 |
| `SKILL.toml` | 技能元数据 |
| `scripts/onvif_ctrl.py` | ONVIF 控制主脚本 |
| `scripts/setup.sh` | 依赖安装脚本 |
| `scripts/setup_wizard.py` | 本地配置向导 |
| `scripts/config.example.ini` | 配置模板 |

## Design principles

这个项目刻意保持简单，因为它的目标不是做一个“大而全”的监控平台，而是做一个足够清晰、足够可靠的 Agent 能力层。

| 原则 | 含义 |
| --- | --- |
| Keep setup light | 安装和接入尽量简单 |
| Evidence first | 先有截图，再有分析 |
| Agent-ready | 设计上服务于自动化巡检，而不是手工操作为主 |
| Build on open protocols | 基于 ONVIF，减少私有设备锁定 |

## Contributing

如果你想继续把它做强，最值得补充的方向包括更多品牌兼容性、事件订阅、夜视策略、告警通道以及更强的巡检编排。

如果你想做的不是“再写一个摄像头脚本”，而是让摄像头真正成为 Agent 的眼睛，这个仓库就是为这个方向准备的。
