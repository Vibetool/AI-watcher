# AI Watcher

**Turn any ONVIF camera into an AI watcher.**

Make an ordinary ONVIF camera into an **AI vision node** that can see, pan, run scheduled patrols, and report back with evidence images.

[简体中文](./README.zh-CN.md) · English

`AI Watcher` is built for the **OpenClaw** workflow. It chains camera connectivity, RTSP retrieval, PTZ control, scheduled patrols, and snapshot-based analysis into one executable pipeline — built for scenarios where you want an Agent to actually *keep an eye on* a place, not just produce a one-off demo.

**No app. No cloud dashboard. No heavy setup.**
If your camera speaks ONVIF, you can plug it in fast.

## Why people may want this

A lot of projects can "connect to a camera." Very few solve the next problem: **once you're connected, how do you turn that camera into a vision capability an Agent can call repeatedly — instead of a one-shot demo?**

The focus of this repo isn't a fancy UI. It's getting a few key capabilities right:

| What you need | What AI Watcher gives you |
| --- | --- |
| Let the Agent see the scene | Fetch RTSP / Snapshot URI, hand it off to your image analysis pipeline |
| Let the Agent change the view | PTZ control with stop and home-position support |
| Let the Agent run scheduled patrols | Plug into OpenClaw Heartbeat for periodic tasks |
| Make results trustworthy | Analysis must be grounded in real snapshots; image attachment is the default |
| Keep deployment painless | Install and configuration stay lightweight |

## What it does

| Capability | Description |
| --- | --- |
| Camera info | Read camera manufacturer, model, firmware version, serial number |
| Stream URI | Get the RTSP video stream URL |
| Snapshot URI | Get the snapshot URL |
| PTZ control | Up / down / left / right / zoom / stop / home, with serial-access protection and auto-stop |
| Conversational setup | An Agent can walk the user through configuration via chat |
| Watcher workflow | Extensible into scheduled patrols and exception monitoring |
| Safe capture | A first-class capture command that outputs a compressed JPG by default |

## Install with an agent

Hand this repo to your Agent and just say:

```text
Install and configure [AI-watcher](https://github.com/Vibetool/AI-watcher) for me.
```

The Agent will install dependencies and walk you through entering the camera's IP, port, username, and password.

If you already have OpenClaw running in your environment, this is usually the easiest way in.

## Manual setup

Manual install only takes a few steps.

> ⚠️ **Network prerequisite**: most consumer / entry-level ONVIF cameras only support **2.4 GHz** Wi-Fi, not 5 GHz. Make sure the device running the Agent (laptop, NAS, Raspberry Pi, etc.) is on the **same Layer-2 LAN** as the camera and can reach the camera's IP over the 2.4 GHz band.
>
> If your router splits 2.4 GHz and 5 GHz into separate SSIDs, or puts them on different VLANs, an Agent on 5 GHz / a guest network / a different VLAN **will not see the camera** — ONVIF discovery and SOAP calls will both fail.

### 1. Clone the repo

```bash
git clone https://github.com/Vibetool/AI-watcher.git
cd AI-watcher
```

### 2. Install dependencies

```bash
bash scripts/setup.sh
```

Use the same `python3` interpreter for both installation and runtime, so you don't end up with dependencies installed against one Python while the command runs against another.

### 3. Create your local camera config

Copy the example config and fill in your camera details.

```bash
cp scripts/config.example.ini scripts/config.ini
```

Then edit `scripts/config.ini`:

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
python3 scripts/onvif_ctrl.py capture --output /tmp/snapshot.jpg --max-width 1280 --quality 85
python3 scripts/onvif_ctrl.py ptz --act left --duration 1.0
```

If you get JSON back, the camera is wired up. For snapshots, prefer the new `capture` command rather than piping a raw RTSP frame straight into a message body. `capture` outputs a compressed JPG, which fits better with MCP, WeChat Work, or any channel with payload limits.

## How it feels in practice

Think of it as a "camera action layer" for your Agent.

```text
User: go check if anyone is at the office door
-> Agent reads the camera config
-> Fetches the video stream or a snapshot
-> Pans the camera if needed
-> Runs analysis grounded in the actual frame
-> Returns the conclusion, with the snapshot attached as evidence
```

That's more useful than just returning an RTSP URL, because it matches what an actual automated patrol flow looks like.

PTZ control now requires a positive `duration` by default, so every move is followed by an automatic `stop`. This noticeably reduces the chance of 500 errors or hangs that some cameras hit under back-to-back requests.

## Good use cases

| Scenario | What this repo helps you do |
| --- | --- |
| After-hours office watch | Periodic snapshots, alert on unusual activity |
| Warehouse or store patrol | Time-based checks of specific zones |
| Elderly / pet care | Check in on a fixed spot and produce a short summary |
| Security prototyping | A foundation for more complex Agent patrol systems |

## Current limitation, and what's next

The biggest current limitation: **image capture is still mostly cron-driven.** That makes today's version a good fit for periodic patrols, fixed-spot watching, and rule-based checks — but for truly real-time, proactive Watcher scenarios there's still room to grow.

Next, we'll roll in more capabilities that actually fit the **Watcher mode** of AI cameras.

| Next direction | What it changes |
| --- | --- |
| AI cameras with on-device object detection | The camera filters locally and only uploads key frames to the cloud for analysis — fewer wasted captures, better trigger latency |
| AI cameras running large models locally | Frames don't leave the device — faster recognition, better privacy, at higher hardware cost |

Long term, `AI Watcher` is more than "let any ONVIF camera talk to an Agent." It's about gradually being compatible with smarter edge devices, taking the system from "look every N minutes" toward "detect, report, and respond proactively."

## Project structure

| Path | Purpose |
| --- | --- |
| `README.md` | Project overview (English) |
| `README.zh-CN.md` | Project overview (Simplified Chinese) |
| `SKILL.md` | Skill description for Agents |
| `SKILL.toml` | Skill metadata |
| `scripts/onvif_ctrl.py` | Main ONVIF control script |
| `scripts/setup.sh` | Dependency install script |
| `scripts/setup_wizard.py` | Local configuration wizard |
| `scripts/config.example.ini` | Config template |

## Design principles

This project deliberately stays small. The goal isn't to build a big-and-everything surveillance platform — it's to be a clear, reliable capability layer for Agents.

| Principle | Meaning |
| --- | --- |
| Keep setup light | Install and onboarding stay minimal |
| Evidence first | Snapshot first, analysis second |
| Agent-ready | Designed for automated patrol, not manual operation |
| Build on open protocols | Built on ONVIF to avoid vendor lock-in |

## Contributing

The most valuable directions to expand this are: broader brand compatibility, event subscriptions, night-vision strategies, alert channels, and stronger patrol orchestration.

If what you want isn't "yet another camera script" but to make a camera actually function as an Agent's eyes, this repo is for you.

## Procurement and partnership

If you need to source compatible cameras, or if your team is interested in deeper collaboration, reach out: **team@vibetool.ai**.
