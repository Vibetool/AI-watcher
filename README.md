# ONVIF AI Watcher

**Turn any ONVIF IP camera into a conversational AI watcher.**

`ONVIF AI Watcher` 是一个面向 **OpenClaw** 生态的技能项目，用来把普通局域网 IP 摄像头升级为可通过自然语言配置、支持 **PTZ 控制**、**画面抓取**、**定时视觉巡检** 与 **证据闭环汇报** 的 AI 视觉节点。

它并不是一个“只会读流地址”的小脚本集合，而是一个更适合 Agent 工作流的摄像头能力层：让模型先连接设备、再拿到画面、再做巡检与异常分析，并且在汇报时强制附上原始截图，避免“看都没看就下结论”。

## Why this project is interesting

很多摄像头项目的问题不在于“连不上设备”，而在于即使连上以后，也很难把它接入一个可靠的 Agent 工作流。这个项目的价值在于，它把 **设备控制**、**定时调度**、**视觉分析** 与 **反幻觉约束** 串成了一条清晰链路。

| 维度 | 本项目提供的能力 | 对实际使用的意义 |
| --- | --- | --- |
| 接入方式 | 通过对话完成摄像头配置 | 不需要手改配置文件，适合 Agent 场景 |
| 设备能力 | 支持 ONVIF 信息读取、RTSP 流获取、PTZ 控制 | 既能“看”，也能“动” |
| 自动化 | 可结合 Heartbeat 做周期性巡检 | 适合办公室、仓库、宠物、老人看护 |
| 可信输出 | 强制基于真实抓拍画面汇报，并附原图 | 降低 AI 凭空描述场景的风险 |
| 可扩展性 | 可继续扩展陌生人识别、归位校验、夜视策略等 | 适合做更强的自主安防 Agent |

## Core capabilities

当前仓库已经具备一套可落地的基础能力，既能支撑演示，也能作为后续增强的底座。

| 能力 | 说明 |
| --- | --- |
| Conversational setup | 通过 `setup.sh` 和配置向导完成依赖安装与摄像头参数写入 |
| Camera info query | 读取摄像头厂商、型号、固件版本、序列号等信息 |
| Stream & snapshot URI | 获取 RTSP 视频流地址与快照地址，便于后续画面抓取 |
| PTZ control | 支持上下左右移动、缩放、停止与归位 |
| AI Watcher workflow | 可结合 OpenClaw Heartbeat 建立周期性巡检任务 |
| Anti-hallucination discipline | 分析结论必须基于真实截图，并要求附图返回 |

## Typical scenarios

这个项目最适合那些“不是只想接个摄像头，而是想让 Agent 真正持续看着现场”的场景。

### 1. 办公室或门店夜间看护

你可以让 Agent 在下班后定时查看办公区、前台或门店入口。如果发现有人活动、灯光异常或物体摆放明显变化，再把截图和简短分析推送出来。

### 2. 老人、宠物或家庭场景看护

对于家庭用户，这个项目很适合做“定时看一眼”的轻量看护。比如中午检查宠物活动情况，或者定点查看老人是否在固定区域内正常活动。

### 3. 自主巡检与安防原型

如果继续扩展调度、记忆和规则，这个仓库也可以作为一个自主安防 Agent 的雏形，包括自动扫描、异常追踪、归位校验与事件升级。

## Repository structure

| 路径 | 作用 |
| --- | --- |
| `README.md` | 面向项目使用者的说明文档 |
| `SKILL.md` | 面向 Agent 的技能说明，定义安装、巡检与输出纪律 |
| `SKILL.toml` | 技能元数据，用于包描述与发现 |
| `scripts/onvif_ctrl.py` | 核心摄像头控制脚本 |
| `scripts/setup.sh` | 依赖安装脚本 |
| `scripts/setup_wizard.py` | 本地配置向导，可写入 `scripts/config.ini` |
| `scripts/config.example.ini` | 示例配置模板 |

## Quick start

如果你希望把它作为 OpenClaw 技能使用，建议按下面的方式接入。

1. 将仓库放入技能目录。
2. 在对话中要求 Agent 安装并配置 `onvif-camera`。
3. Agent 会安装 Python 依赖，并引导填写摄像头的 IP、端口、用户名和密码。
4. 完成配置后，即可执行信息读取、RTSP 地址提取、PTZ 控制和后续巡检工作流。

### Example commands

```bash
python3 scripts/onvif_ctrl.py info
python3 scripts/onvif_ctrl.py stream_uri
python3 scripts/onvif_ctrl.py snapshot_uri
python3 scripts/onvif_ctrl.py ptz --act left --duration 1.0
```

## Design principles

这个项目最有特色的地方不是“多一个 ONVIF 控制脚本”，而是明确强调了 Agent 场景中的三个设计原则。

| 原则 | 含义 |
| --- | --- |
| Evidence first | 所有分析先有图，再有结论 |
| Control before intelligence | 先拿到稳定的设备控制能力，再叠加智能分析 |
| Workflow over demo | 不只展示单次调用，而是服务于可持续巡检任务 |

## What can be improved next

如果要把这个项目继续打磨成更强的公开仓库，接下来最值得继续投入的方向包括：更丰富的错误处理、更多厂商兼容性验证、夜视与移动侦测事件接入，以及面向真实部署的告警通道集成。

## Contributing

欢迎提交 Issue 或 Pull Request，尤其是以下方向：

| 方向 | 说明 |
| --- | --- |
| Camera compatibility | 增加不同品牌 ONVIF 摄像头的兼容性验证 |
| Patrol workflows | 增加更完整的巡检与告警自动化流程 |
| Event integration | 增加移动侦测、红外模式与外部通知能力 |
| Reliability | 改善错误提示、配置校验与运行稳定性 |

如果你想做的不只是“连上摄像头”，而是让摄像头变成一个能持续观察、按规则行动、并给出带证据结果的 Agent 视觉节点，这个项目的方向是对的。
