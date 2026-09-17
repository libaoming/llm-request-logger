# llm-request-logger

[English](README.md) | [中文](README.zh-CN.md)

看清 AI 编程工具每一轮到底给模型发了什么，以及你自己的每一项配置各占多少。

原名 `claude-code-prompt-probe`。v1 是一个假端点，用来测 Claude Code 的系统提示词。v2 加了真代理模式，
还有两个普通抓包工具没有的分析命令：**来源归因**（请求里那些字符是哪个文件、哪份 skill 目录、哪个 MCP
服务带进来的）和**缓存前缀对比**（两次请求的缓存从哪个字符开始对不上）。

只用 Python 标准库，不用安装。

## 两种抓法

```
  fake   claude ──▶ llmlog ──▶ （不转发）            不花额度，不碰凭证，单轮
  proxy  claude ──▶ llmlog ──▶ api.anthropic.com   真实会话，有回复和 token 用量
                       │
                       ▼
                 cap/*.json  ──▶  report   一次请求里有什么，分别从哪来
                             ──▶  diff     两次请求的缓存前缀从哪里开始不同
                             ──▶  compare  多个模型的系统提示词逐节对比
                             ──▶  export   脱敏后可以公开的版本
```

| | `fake` 假端点 | `proxy` 真代理 |
|---|---|---|
| 请求是否离开本机 | 否 | 是，原样转发 |
| 是否花额度 | 否 | 是 |
| 凭证 | 随便填一个假 key | 真实登录原样透传，不落盘 |
| 能拿到 | 请求 | 请求、回复、真实 token 用量（含缓存读写） |
| 适合 | 在干净配置下测厂商原始提示词，做跨模型对比 | 体检自己的真实配置，排查缓存没命中 |

## 快速上手

```bash
git clone https://github.com/libaoming/llm-request-logger.git && cd llm-request-logger

./llmlog.py proxy                      # 终端 A
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ENABLE_TOOL_SEARCH=true claude    # 终端 B

./llmlog.py report cap/<文件>.json      # 读一份抓包
```

`llmlog.py fake` 启动后会打印它自己的命令，里面多了干净的 `CLAUDE_CONFIG_DIR` 和一个假 key，这样测到的是
厂商的提示词，不是你自己的配置。

用完按 Ctrl+C 停掉代理，之后启动 `claude` 时去掉 `ANTHROPIC_BASE_URL`。

## report：每一项配置占多少

作者机器上的一句 `hello`（路径已脱敏）：

```
== 三大块（按缓存前缀顺序）==
  tools        67,697 字符  50.4%
  system       10,693 字符   8.0%
  messages     55,948 字符  41.6%

== tools：18 个，最大的 5 个 ==
    29,185  Artifact
     5,587  SendFeedback
     ...

== messages：2 条，按来源归并 ==
    26,372  skill 目录
     6,812  MCP 使用说明
     5,468  子 agent 类型介绍
     4,892  延迟加载的工具名单
     2,653  规则文件 /Users/USER/.claude/CLAUDE.md
     2,081  规则文件 /Users/USER/.claude/rules/context7.md
     ...
         5  你输入的内容

== token 用量（服务器返回的真实值）==
  cache_creation_input_tokens        54,512
  output_tokens                          65
```

打了 5 个字符，跟着发出去的 skill 目录有 26,372 个字符。表里的大小是字符数，不是字节数：三大块是重新序列化
成 JSON 之后量的，`messages` 下面各行按原文计数，所以加起来比 `messages` 的总数小。token 数只用服务器返回的
真实值，llmlog 不做 token 估算。

加 `--md out.md` 会另存一份能直接读的完整请求；要分享的话再加 `--scrub`。

## diff：缓存从哪里断的

提示词缓存按 `tools → system → messages` 的顺序做前缀匹配。`diff` 按这个顺序把两次请求切成段，报出第一个
不同的段，以及段内第一个不同的字符。

同一个目录，前后隔几秒开两次新会话。第二次只从缓存读到 12,260 个 token，另外 26,499 个重新写入。为什么
没有全部命中？

```
前缀一致到：第 20 段之前，共 54,655 字符
结论：从这一段开始不同，它和它后面的缓存全部失效。
  A 段名  messages[1].content[0] system/text
  段内偏移 9,993
  A: …WebFetch\nWebSearch\nmcp__【mail__apply_label…】
  B: …WebFetch\nWebSearch\nmcp__【podcast__search…】
```

（MCP 服务名做了简化。）

「延迟加载的工具名单」是按第一轮发出时已经连上的 MCP 服务生成的，所以每次会话都可能不一样。内容变了的
位置之后，缓存不可能命中。

`diff` 能说明什么、不能说明什么：它比的是内容。`cache_control` 标记不参与比较，因为 Claude Code 每一轮都把
它挪到最新的块上，那是正常的增量命中，不是失效。后来又测了一次（先 `claude -p`，再 `claude -p --continue`），
`diff` 判定第一次请求是第二次的完整前缀，请求参数也完全一致，但服务器仍然只读了 12,261 个 token，也就是工具
和系统提示词那部分。所以内容不一致是缓存没命中的原因之一，不是唯一原因。llmlog 能判断是不是内容的问题，
看不到服务器端的缓存决定。实际命中多少，以 `cache_read_input_tokens` 为准。

## 观察者效应

Claude Code 只信任一个服务器地址。把它指向别处，它就关掉工具按需加载，把全部工具定义写进请求，抓到的包比
真实流量大。`ENABLE_TOOL_SEARCH=true` 可以抵消这个效应。下面是用 `fake` 模式、干净配置、CLI 2.1.274、
`claude -p "hi" --model claude-opus-5` 实测的：

| 运行方式 | 工具数 | 请求体 |
|---|---:|---:|
| 只改服务器地址 | 24 | 83,648 字节 |
| 加 `ENABLE_TOOL_SEARCH=true` | 12 | 45,197 字节 |

两次的系统提示词逐字节相同（8,867 字符），所以下面 v1 的提示词结论仍然成立。v1 里说每份抓包都带
「25 个工具定义」，那句描述的是被放大的请求，不是真实流量。

## 各家模型怎么用（复制粘贴即可）

两个终端。终端 A 启动代理，终端 B 用下面的命令启动 Claude Code。`<你的 API key>` 换成你在那家平台申请的 key。
模型名是 2026-09 的示例，各家更新得快，以官方文档为准。代理启动时也会把终端 B 的命令打印出来。

### Anthropic 官方

```bash
# 终端 A
./llmlog.py proxy --provider anthropic

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ENABLE_TOOL_SEARCH=true claude
```

### Kimi 月之暗面（国内站）

```bash
# 终端 A
./llmlog.py proxy --provider kimi

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=kimi-k3 ANTHROPIC_DEFAULT_OPUS_MODEL=kimi-k3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=kimi-k3 ANTHROPIC_DEFAULT_HAIKU_MODEL=kimi-k3 claude
```

上游地址 `https://api.moonshot.cn/anthropic`，官方文档 https://platform.kimi.ai/docs/guide/claude-code-kimi

### Kimi Moonshot（国际站）

```bash
# 终端 A
./llmlog.py proxy --provider kimi-global

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=kimi-k3 ANTHROPIC_DEFAULT_OPUS_MODEL=kimi-k3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=kimi-k3 ANTHROPIC_DEFAULT_HAIKU_MODEL=kimi-k3 claude
```

上游地址 `https://api.moonshot.ai/anthropic`，官方文档 https://platform.kimi.ai/docs/guide/claude-code-kimi

### 智谱 GLM（国内站 bigmodel.cn）

```bash
# 终端 A
./llmlog.py proxy --provider glm

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=glm-5.1 ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.1 ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.1 claude
```

上游地址 `https://open.bigmodel.cn/api/anthropic`，官方文档 https://github.com/MetaGLM/glm-cookbook/blob/main/vibecoding/glm-4.5-claude-code-integration.md

### 智谱 GLM（国际站 z.ai）

```bash
# 终端 A
./llmlog.py proxy --provider glm-global

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=glm-5.1 ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.1 ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.1 claude
```

上游地址 `https://api.z.ai/api/anthropic`，官方文档 https://docs.z.ai/devpack/tool/claude

### DeepSeek

```bash
# 终端 A
./llmlog.py proxy --provider deepseek

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=deepseek-v4-pro ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro \
  ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-pro claude
```

上游地址 `https://api.deepseek.com/anthropic`，官方文档 https://api-docs.deepseek.com/guides/anthropic_api

### MiniMax（国内站）

```bash
# 终端 A
./llmlog.py proxy --provider minimax

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3 claude
```

上游地址 `https://api.minimaxi.com/anthropic`，官方文档 https://platform.minimax.io/docs/guides/text-ai-coding-tools

### MiniMax（国际站）

```bash
# 终端 A
./llmlog.py proxy --provider minimax-global

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3 claude
```

上游地址 `https://api.minimax.io/anthropic`，官方文档 https://platform.minimax.io/docs/guides/text-ai-coding-tools

### 阿里云百炼 Qwen（Coding Plan）

```bash
# 终端 A
./llmlog.py proxy --provider qwen

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=qwen3.7-plus ANTHROPIC_DEFAULT_OPUS_MODEL=qwen3.7-plus \
  ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3.7-plus ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3.7-plus claude
```

上游地址 `https://coding.dashscope.aliyuncs.com/apps/anthropic`，官方文档 https://help.aliyun.com/zh/model-studio/claude-code

### 火山方舟 豆包（Coding Plan）

```bash
# 终端 A
./llmlog.py proxy --provider doubao

# 终端 B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<你的 API key> \
  ANTHROPIC_MODEL=ark-code-latest ANTHROPIC_DEFAULT_OPUS_MODEL=ark-code-latest \
  ANTHROPIC_DEFAULT_SONNET_MODEL=ark-code-latest ANTHROPIC_DEFAULT_HAIKU_MODEL=ark-code-latest claude
```

上游地址 `https://ark.cn-beijing.volces.com/api/coding`，官方文档 https://www.volcengine.com/docs/82379/2373740

### 表里没有的服务

只要兼容 Anthropic Messages 格式，就能用 `--upstream` 接入，地址里带路径前缀也可以：

```bash
./llmlog.py proxy --upstream https://你的服务地址/anthropic
```

阿里云百炼按量付费的地址带你自己的 WorkspaceId（形如 `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic`），
也用 `--upstream` 填。

### 三点说明

- **已经在 `~/.claude/settings.json` 里配好了某家服务的人：** 不用敲上面那一长串。把 settings 里的
  `ANTHROPIC_BASE_URL` 改成 `http://127.0.0.1:8787`，终端 B 直接运行 `claude`，抓完再改回去。
- **只有 Anthropic 官方要加 `ENABLE_TOOL_SEARCH=true`。** 用第三方服务的人，平时的地址本来就不是官方的，
  Claude Code 平时就把全部工具定义写进请求，所以不加开关抓到的才是真实流量。
- **测试程度：** Anthropic 官方作者端到端实测过。其余各家的地址逐个对照了官方文档，带路径前缀的转发有自动化
  测试覆盖，但作者没有这些平台的 key，没做端到端实测，欢迎反馈。OpenAI 格式和 Gemini 格式的请求，`proxy`
  照样转发和存盘，但 `report` 目前只认 Anthropic 的请求结构。

## 什么会写到磁盘，什么不会

- 名字里带 `key`、`token`、`secret`、`auth`、`cookie`、`signature`、`credential`、`password` 的请求头和
  网址参数，落盘前一律替换成 `[REDACTED]`（比如 `authorization`、`x-api-key`、`x-goog-api-key`、`?key=`）。
  `proxy` 模式下它们仍然原样发给上游。名字里不带这些词的请求头（比如你通过 `ANTHROPIC_CUSTOM_HEADERS`
  自己加的），或者写在请求体里的凭证，**会**被写进磁盘。
- `cap/` 里的原始抓包**包含** `metadata.user_id`（设备、账号、会话标识）、你的邮箱、home 路径和规则文件
  全文。`cap/` 已经加进 gitignore，不要公开。
- `export` 和 `report --md --scrub` 会改写 home 路径、作为完整单词出现的用户名、邮箱、UUID 和长十六进制串。
  `export` 不加 `--full` 时只导出系统提示词正文，并剔除本机注入的节。
- 脱敏抹掉的是标识，不是内容。`--full` 导出的文件里，规则文件正文、git 状态、MCP 服务名都还在，公开前自己
  再看一遍。

## 几个值得知道的行为

- 除了数 token 的请求，所有 POST 都会记录。数 token 的请求照常转发但不落盘，终端里仍然能看到。
- 上游中途断流时，已经收到的部分照常落盘，并带一个 `stream_error` 字段。
- 带 `Origin` 头的请求会被拒绝：命令行工具不带这个头，网页才带。
- 一轮对话往往不止一次请求。Claude Code 还会发一条给会话起标题的小请求，它确实产出了回复，所以会被记录。
- WebSocket 升级请求会立刻收到 `426`，agent 会马上退回 HTTP，不会一直挂着。
- 同一个方法、路径和状态码 2 秒内重复超过 20 次（agent 配错后无间隔重试），llmlog 就不再逐条写文件，
  只提示一次。转发不受影响。
- 环境变量 `HTTPS_PROXY` 里的 `http://` 代理会用于连上游（CONNECT 隧道，支持用户名密码和 `NO_PROXY`）。
  `https://` 和 `socks5://` 类型的代理不支持，遇到时 llmlog 改为直连。

## v1 的发现：各模型的系统提示词

测量环境：CLI **2.1.220**（原生二进制）、macOS、`fake` 模式、干净配置。「手写正文」不含环境注入的节
（`# Environment`、`# auto memory`、`# claudeMd`、`# Session-specific guidance`）。

| 模型 | 手写正文 | 路由 |
|---|---:|---|
| `claude-opus-4-1-20250805` | 12,938 | legacy |
| `claude-opus-4-5-20251101` | 12,938 | legacy |
| `claude-opus-4-7` | 12,938 | legacy |
| `claude-sonnet-5` | 12,938 | **legacy** |
| `claude-haiku-4-5-20251001` | 12,938 | **legacy** |
| `claude-opus-4-8` | 5,041 | new |
| `claude-opus-5` | 8,375 | new |
| `claude-fable-5` | 9,487 | new |

逐节数据见 [docs/section-sizes.md](docs/section-sizes.md)。复现方法：`llmlog.py fake`，每个模型跑一次
`claude -p "hi" --model <id>`，然后 `llmlog.py compare cap`。

删减发生在 **4.8**，不在 5，而且之后又加回来一部分。三代下来净删约 26%，不是 80%。拿到哪份提示词，由模型
名里的子串决定：`zzz-haiku-zzz` 会拿到旧版，`totally-made-up-model` 拿到新版。

**旧模型名会被改写。** CLI 会悄悄把旧模型名改成最新的 Opus。测 4.1 时不加
`CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1`，测到的其实是 Opus 5。

## 测试

```bash
python3 -m unittest discover -s tests
```

测试里代理的上游就是假端点，整套测试不出本机，不花额度。

## 致谢与协议

代理模式的想法来自 Matt Pocock 的 [AI Coding Crash Course](https://www.aihero.dev/workshops/ai-coding-crash-course)
随课附带的 request logger：观察者效应、跳过数 token 的请求、拒绝 WebSocket 升级、重试防刷屏，这几个思路
最早见于它。本项目没有使用它的任何代码，是独立的 Python 实现。

脚本采用 MIT 协议。抓到的提示词文本归 Anthropic 所有，这里只作为你对自己的客户端运行这些工具的输出而出现。
