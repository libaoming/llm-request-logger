# claude-code-prompt-probe

[English](README.md) | [中文](README.zh-CN.md)

把 Claude Code CLI 指向本地一个假端点，读它真正发出去的东西。

Anthropic 说他们为 Opus 5 删掉了 Claude Code 80% 的系统提示词。这个仓库是一套可复现的验证方法
——不需要反编译，也不需要读任何源码。系统提示词每次请求都要完整发出去，一个约 60 行的 HTTP
server 就够看全了。

## 原理

```
  claude -p "hi" --model <id>
           │
           │  ANTHROPIC_BASE_URL=http://127.0.0.1:8787
           ▼
  ┌─────────────────────────┐
  │  sniff.py（假 API 端点） │   POST /v1/messages
  │                         │──▶ 请求体落盘到 cap/req-NNN.json
  │                         │◀── 回一段最小的合法 SSE 流
  └─────────────────────────┘    让 CLI 正常收场、不报错
           │
           ▼
  cap/req-NNN.json  ──▶  analyze.py   单个 model，逐节字数
                    ──▶  compare.py   多个 model，并排对比表
                    ──▶  export.py    导出提示词正文（已脱敏）
```

请求根本没出本机，不转发给 Anthropic，所以既不消耗额度也不碰账号凭据——假端点直接回一句
`ok` 就完事。

## 快速开始

```bash
python3 sniff.py 8787 ./cap &          # 1. 起假端点

mkdir -p /tmp/clean_cfg /tmp/workdir   # 2. 让 CLI 打过来
cd /tmp/workdir
CLAUDE_CONFIG_DIR=/tmp/clean_cfg \
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 \
ANTHROPIC_API_KEY=sk-dummy \
CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1 \
  claude -p "hi" --model claude-opus-5

python3 analyze.py cap/req-001.json    # 3. 读它
```

`CLAUDE_CONFIG_DIR` 指向一个空目录，是把官方提示词和你自己的 `CLAUDE.md`、MCP、skills 隔离开的
关键。不这么做，你量的是自己的配置。

## 实测结果

CLI **2.1.220**（原生二进制版）、macOS 实测。「策略正文」= 排除环境注入的那些节
（`# Environment`、`# auto memory`、`# claudeMd`、`# Session-specific guidance`）。

| model | 策略正文 | 走哪套 |
|---|---:|---|
| `claude-opus-4-1-20250805` | 12,938 | 旧 |
| `claude-opus-4-5-20251101` | 12,938 | 旧 |
| `claude-opus-4-7` | 12,938 | 旧 |
| `claude-sonnet-5` | 12,938 | **旧** |
| `claude-haiku-4-5-20251001` | 12,938 | **旧** |
| `claude-opus-4-8` | 5,041 | 新 |
| `claude-opus-5` | 8,375 | 新 |
| `claude-fable-5` | 9,487 | 新 |

逐节明细见 [docs/section-sizes.md](docs/section-sizes.md)。

两点值得注意。第一，**那一刀砍在 4.8，不在 5**，而且之后一直在往回加：4.8 是谷底 5,041，
Opus 5 加回了 `# Delivering work` 和 `# Corrections`，Fable 5 带着一节 4,122 字符的
`# Communicating with the user`。三代下来净删掉的大约是 26%，不是 80%。

第二，Sonnet 5 和 Haiku 4.5 是当代模型，但拿到的是**旧**提示词。这是路由实现的产物，不是什么
设计取舍——见下。

## 路由是子串匹配

发哪套提示词，取决于拿 model id 字符串去匹配子串，而不是查模型注册表。不用读任何代码就能证明
——编一个根本不可能存在的 model id，看它回哪套：

| `--model` 传的值 | 收到的提示词 |
|---|---|
| `opus-5-sonnet-probe` | 旧（`# Doing tasks`） |
| `zzz-haiku-zzz` | 旧 |
| `claude-3-probe` | 旧 |
| `totally-made-up-model` | 新（`# Harness`） |

一个纯虚构的 id，只因为字符串里含 `sonnet` 就路由到了旧提示词。新提示词是默认，旧的靠子串命中
才走。

## 三个坑

**旧 model 会被自动 remap。** CLI 会静默地把旧 model id 改写成最新的 Opus。不加
`CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1` 就去测 4.1，你量到的其实是 Opus 5。

**原生二进制里字符串是压缩的。** 如果你的 `claude` 是约 250MB 的单文件版，
`strings | grep "Doing tasks"` 一条都搜不到。静态分析得用 npm 版——那里 `cli.js` 是明文
JavaScript。抓请求这条路两种版本都通。

**你自己的配置会把数字撑大。** 作者机器上第一次抓到 27,883 字符，其中 12,978 是个人记忆索引被
注入进去的。一定要从干净的 `CLAUDE_CONFIG_DIR` 和空工作目录去测。

## 脱敏

每个请求的 `metadata.user_id` 里都带着 `device_id` 和 `session_id`。**不要公开原始抓包文件。**
`export.py` 只提取系统提示词正文，剔除本机注入的节，并在写出前把家目录路径、邮箱、UUID 和长
十六进制串统统替换掉。

## 提示词正文

本仓库的 `prompts/` 目录是空的。自己在本地生成：

```bash
python3 export.py ./cap ./prompts
```

## 许可

脚本部分 MIT。抓到的提示词文本版权属于 Anthropic，此处仅作为「用这套工具跑你自己的客户端」的
输出结果而存在。
