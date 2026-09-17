# llm-request-logger

[English](README.md) | [中文](README.zh-CN.md)

See exactly what your AI coding agent sends to the model on every turn — and what each piece of
your own config costs you.

Formerly `claude-code-prompt-probe`. v1 was a fake endpoint for measuring Claude Code's system
prompt. v2 adds a real forwarding proxy and two analysis commands that no plain logger has:
**attribution** (which file, skill list or MCP server put those characters in your request) and
**cache-prefix diff** (where exactly two requests stop sharing a cache).

Python standard library only. No install step.

## Two ways to capture

```
  fake   claude ──▶ llmlog ──▶ (nothing)           free, no credentials, single turn
  proxy  claude ──▶ llmlog ──▶ api.anthropic.com   real sessions, replies, token usage
                       │
                       ▼
                 cap/*.json  ──▶  report   what is in one request, and where it came from
                             ──▶  diff     where two requests stop sharing a cache prefix
                             ──▶  compare  system prompt sections across models
                             ──▶  export   scrubbed copies you can publish
```

| | `fake` | `proxy` |
|---|---|---|
| Request leaves your machine | no | yes, forwarded untouched |
| Costs quota | no | yes |
| Credentials | a dummy key is enough | your real login passes through, never written to disk |
| You get | the request | the request, the reply, real token usage incl. cache reads and writes |
| Use it for | measuring the vendor's prompt from a clean config, comparing models | auditing your real setup, debugging cache misses |

## Quick start

```bash
git clone https://github.com/libaoming/llm-request-logger.git && cd llm-request-logger

./llmlog.py proxy                      # terminal A
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ENABLE_TOOL_SEARCH=true claude    # terminal B

./llmlog.py report cap/<file>.json     # read a capture
```

`llmlog.py fake` prints its own command, which adds a clean `CLAUDE_CONFIG_DIR` and a dummy key so
that you measure the vendor's prompt and not your own config.

When you are done, stop the proxy with Ctrl+C and start `claude` without `ANTHROPIC_BASE_URL`.

## report: what each piece of config costs

One `hello` on the author's machine (paths scrubbed):

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

Five characters typed; 26,372 characters of skill catalogue sent along with them. Sizes are character
counts, not bytes: the three top-level parts are measured after re-serialising them as JSON, the rows
under `messages` count the raw text, so they add up to less than the `messages` total. Token numbers are
only ever the ones the server returned — llmlog does not estimate tokens.

`--md out.md` writes a readable render of the whole request; add `--scrub` before sharing it.

## diff: where the cache breaks

Prompt caching matches a prefix in the order `tools → system → messages`. `diff` cuts two requests
into segments in that order and reports the first segment, and the first character inside it, that
differs.

Two fresh sessions, same directory, seconds apart. The second one read 12,260 tokens from cache
and re-wrote 26,499. Why not all of it?

```
前缀一致到：第 20 段之前，共 54,655 字符
结论：从这一段开始不同，它和它后面的缓存全部失效。
  A 段名  messages[1].content[0] system/text
  段内偏移 9,993
  A: …WebFetch\nWebSearch\nmcp__【mail__apply_label…】
  B: …WebFetch\nWebSearch\nmcp__【podcast__search…】
```

(MCP server names shortened.)

The list of deferred tool names is built from whichever MCP servers have finished connecting when
the first turn is sent, so it differs between sessions. Content after a changed point cannot be served
from cache.

What `diff` can and cannot tell you: it compares content. The `cache_control` marker is left out of the
comparison, because Claude Code moves it to the newest block every turn and that is a normal incremental
hit, not a break. In a follow-up run (`claude -p`, then `claude -p --continue`) `diff` found the first
request to be a complete prefix of the second, with identical parameters — and the server still read
only 12,261 tokens, the tools and system prompt. So content divergence is one cause of a miss, not the
only one. llmlog rules content in or out; it cannot see the server's cache decisions. Trust
`cache_read_input_tokens` for what actually hit.

## The observer effect

Claude Code trusts one host. Point it anywhere else and it turns tool search off, stops deferring
tools, and writes every tool schema into the request — so the capture is bigger than real traffic.
`ENABLE_TOOL_SEARCH=true` undoes that. Measured here with `fake`, clean config, CLI 2.1.274,
`claude -p "hi" --model claude-opus-5`:

| run | tools | request body |
|---|---:|---:|
| base URL only | 24 | 83,648 bytes |
| with `ENABLE_TOOL_SEARCH=true` | 12 | 45,197 bytes |

The system prompt is byte-identical in both (8,867 characters), so the v1 system prompt findings
below stand. The v1 remark that every capture carried "25 tool definitions" was this effect: it
described the inflated request, not real traffic.

## Every provider, copy and paste

Two terminals. Terminal A starts the proxy; terminal B starts Claude Code with the command below.
Replace `<your API key>` with the key from that provider. Model names are examples as of 2026-09 and
change often — check the provider's docs. The proxy also prints the terminal B command when it starts.

### Anthropic (subscription login or API key)

```bash
# terminal A
./llmlog.py proxy --provider anthropic

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ENABLE_TOOL_SEARCH=true claude
```

### Kimi / Moonshot — China site

```bash
# terminal A
./llmlog.py proxy --provider kimi

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=kimi-k3 ANTHROPIC_DEFAULT_OPUS_MODEL=kimi-k3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=kimi-k3 ANTHROPIC_DEFAULT_HAIKU_MODEL=kimi-k3 claude
```

Upstream `https://api.moonshot.cn/anthropic`. Official docs: https://platform.kimi.ai/docs/guide/claude-code-kimi

### Kimi / Moonshot — global site

```bash
# terminal A
./llmlog.py proxy --provider kimi-global

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=kimi-k3 ANTHROPIC_DEFAULT_OPUS_MODEL=kimi-k3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=kimi-k3 ANTHROPIC_DEFAULT_HAIKU_MODEL=kimi-k3 claude
```

Upstream `https://api.moonshot.ai/anthropic`. Official docs: https://platform.kimi.ai/docs/guide/claude-code-kimi

### Zhipu GLM — China site (bigmodel.cn)

```bash
# terminal A
./llmlog.py proxy --provider glm

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=glm-5.1 ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.1 ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.1 claude
```

Upstream `https://open.bigmodel.cn/api/anthropic`. Official docs: https://github.com/MetaGLM/glm-cookbook/blob/main/vibecoding/glm-4.5-claude-code-integration.md

### Zhipu GLM — global site (z.ai)

```bash
# terminal A
./llmlog.py proxy --provider glm-global

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=glm-5.1 ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5.1 ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-5.1 claude
```

Upstream `https://api.z.ai/api/anthropic`. Official docs: https://docs.z.ai/devpack/tool/claude

### DeepSeek

```bash
# terminal A
./llmlog.py proxy --provider deepseek

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=deepseek-v4-pro ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro \
  ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-pro ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-pro claude
```

Upstream `https://api.deepseek.com/anthropic`. Official docs: https://api-docs.deepseek.com/guides/anthropic_api

### MiniMax — China site

```bash
# terminal A
./llmlog.py proxy --provider minimax

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3 claude
```

Upstream `https://api.minimaxi.com/anthropic`. Official docs: https://platform.minimax.io/docs/guides/text-ai-coding-tools

### MiniMax — global site

```bash
# terminal A
./llmlog.py proxy --provider minimax-global

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3 \
  ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3 ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3 claude
```

Upstream `https://api.minimax.io/anthropic`. Official docs: https://platform.minimax.io/docs/guides/text-ai-coding-tools

### Alibaba Cloud Model Studio, Qwen (Coding Plan)

```bash
# terminal A
./llmlog.py proxy --provider qwen

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=qwen3.7-plus ANTHROPIC_DEFAULT_OPUS_MODEL=qwen3.7-plus \
  ANTHROPIC_DEFAULT_SONNET_MODEL=qwen3.7-plus ANTHROPIC_DEFAULT_HAIKU_MODEL=qwen3.7-plus claude
```

Upstream `https://coding.dashscope.aliyuncs.com/apps/anthropic`. Official docs: https://help.aliyun.com/zh/model-studio/claude-code

### Volcengine Ark, Doubao (Coding Plan)

```bash
# terminal A
./llmlog.py proxy --provider doubao

# terminal B
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 ANTHROPIC_AUTH_TOKEN=<your API key> \
  ANTHROPIC_MODEL=ark-code-latest ANTHROPIC_DEFAULT_OPUS_MODEL=ark-code-latest \
  ANTHROPIC_DEFAULT_SONNET_MODEL=ark-code-latest ANTHROPIC_DEFAULT_HAIKU_MODEL=ark-code-latest claude
```

Upstream `https://ark.cn-beijing.volces.com/api/coding`. Official docs: https://www.volcengine.com/docs/82379/2373740

### Anything not listed

Any service that speaks the Anthropic Messages format works through `--upstream`, path prefix included:

```bash
./llmlog.py proxy --upstream https://your-provider.example/anthropic
```

Alibaba Cloud pay-as-you-go endpoints carry your own WorkspaceId
(`https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic`); pass that with `--upstream`.

### Three notes

- **Already configured a provider in `~/.claude/settings.json`?** Skip the long command. Change
  `ANTHROPIC_BASE_URL` there to `http://127.0.0.1:8787`, run plain `claude` in terminal B, and change it
  back afterwards.
- **Only Anthropic needs `ENABLE_TOOL_SEARCH=true`.** With a third-party provider your base URL is never
  the official one, so Claude Code already writes every tool schema into every request. Leaving the flag
  off is what captures your real traffic.
- **How much this was tested.** Anthropic was driven end to end by the author. Every other upstream URL
  was checked against the provider's own documentation, and forwarding with a path prefix is covered by
  the test suite, but the author has no keys for those platforms and has not driven them end to end.
  Reports welcome. OpenAI-format and Gemini-format agents are forwarded and stored, but `report` only
  understands the Anthropic request shape.

## What is and is not written to disk

- Any header or query parameter whose name contains `key`, `token`, `secret`, `auth`, `cookie`,
  `signature`, `credential` or `password` is replaced with `[REDACTED]` before anything is written
  (`authorization`, `x-api-key`, `x-goog-api-key`, `?key=` …). In `proxy` mode they still reach the
  upstream, untouched. A secret under a header name with none of those words (for example one you set
  through `ANTHROPIC_CUSTOM_HEADERS`), or inside the request body, **is** written.
- Raw captures in `cap/` **do** contain `metadata.user_id` (device, account and session ids), your
  email, home paths and the full text of your rule files. `cap/` is gitignored. Do not publish it.
- `export` and `report --md --scrub` rewrite home paths, your username where it appears as a whole
  word, emails, UUIDs and long hex strings. `export` without `--full` writes only the system prompt
  body and drops the sections your machine injects.
- Scrubbing removes identifiers, not content. A `--full` export still holds the text of your rule
  files, git status and MCP server names. Read it before you publish it.

## Behaviour worth knowing

- Every POST is logged except token-counting calls, which are forwarded but not written. The console
  still shows them.
- If the upstream drops mid-stream, what arrived is still captured, with a `stream_error` field.
- Requests carrying an `Origin` header are refused: a CLI does not send one, a web page does.
- A turn is often more than one request. Claude Code also sends a small call that names the
  session; it is a real generation, so it is logged.
- WebSocket upgrade attempts get an immediate `426` so the agent falls back to HTTP instead of
  hanging.
- If the same method, path and status repeats more than 20 times in 2 seconds (an agent retrying a
  misconfigured endpoint with no backoff), llmlog stops writing a file per repeat and says so once.
  Forwarding continues.
- An `http://` proxy in `HTTPS_PROXY` is used for the upstream connection (CONNECT tunnel, basic auth,
  `NO_PROXY`). `https://` and `socks5://` proxies are not supported; llmlog connects directly instead.

## Findings from v1: the system prompt across models

Measured on CLI **2.1.220** (native binary), macOS, `fake` mode, clean config. "Policy prose"
excludes environment-injected sections (`# Environment`, `# auto memory`, `# claudeMd`,
`# Session-specific guidance`).

| model | policy prose | route |
|---|---:|---|
| `claude-opus-4-1-20250805` | 12,938 | legacy |
| `claude-opus-4-5-20251101` | 12,938 | legacy |
| `claude-opus-4-7` | 12,938 | legacy |
| `claude-sonnet-5` | 12,938 | **legacy** |
| `claude-haiku-4-5-20251001` | 12,938 | **legacy** |
| `claude-opus-4-8` | 5,041 | new |
| `claude-opus-5` | 8,375 | new |
| `claude-fable-5` | 9,487 | new |

Section-level breakdown is in [docs/section-sizes.md](docs/section-sizes.md). Reproduce with
`llmlog.py fake`, one `claude -p "hi" --model <id>` per model, then `llmlog.py compare cap`.

The cut happened at **4.8**, not at 5, and has been partly walked back since. Net deletion across
three generations is about 26%, not 80%. Which prompt you get is decided by substring matching on
the model id: `zzz-haiku-zzz` routes to the legacy prompt, `totally-made-up-model` to the new one.

**Legacy model remap.** The CLI silently rewrites old model ids to the newest Opus. Probe 4.1
without `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1` and you are measuring Opus 5.

## Tests

```bash
python3 -m unittest discover -s tests
```

The proxy is tested against the fake endpoint as its upstream, so the suite never leaves the
machine and costs nothing.

## Credits and license

The proxy mode was prompted by the request logger that ships with Matt Pocock's
[AI Coding Crash Course](https://www.aihero.dev/workshops/ai-coding-crash-course): the observer
effect, skipping token-counting calls, refusing WebSocket upgrades and the retry-burst guard are
ideas first seen there. No code is shared; this is an independent Python implementation.

MIT for the scripts. Captured prompt text is Anthropic's, reproduced only as the output of running
these tools against your own client.
