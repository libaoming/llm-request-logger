# claude-code-prompt-probe

[English](README.md) | [中文](README.zh-CN.md)

Point the Claude Code CLI at a local fake endpoint and read exactly what it sends.

Anthropic said they deleted 80% of Claude Code's system prompt for Opus 5. This repo is a
reproducible way to check claims like that yourself — no reverse engineering, no decompiling.
The system prompt is transmitted in full on every request, so a ~60-line HTTP server is enough
to see it.

## How it works

```
  claude -p "hi" --model <id>
           │
           │  ANTHROPIC_BASE_URL=http://127.0.0.1:8787
           ▼
  ┌─────────────────────────┐
  │  sniff.py  (fake API)   │   POST /v1/messages
  │                         │──▶ writes request body to cap/req-NNN.json
  │                         │◀── replies with a minimal valid SSE stream
  └─────────────────────────┘    so the CLI exits cleanly
           │
           ▼
  cap/req-NNN.json  ──▶  analyze.py   one model, section-by-section sizes
                    ──▶  compare.py   many models, side-by-side table
                    ──▶  export.py    system prompt body, scrubbed
```

The request never leaves your machine. It is not forwarded to Anthropic, so this costs no
quota and touches no credentials — the fake endpoint answers with a canned `ok`.

## Quick start

```bash
python3 sniff.py 8787 ./cap &          # 1. start the fake endpoint

mkdir -p /tmp/clean_cfg /tmp/workdir   # 2. run the CLI against it
cd /tmp/workdir
CLAUDE_CONFIG_DIR=/tmp/clean_cfg \
ANTHROPIC_BASE_URL=http://127.0.0.1:8787 \
ANTHROPIC_API_KEY=sk-dummy \
CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1 \
  claude -p "hi" --model claude-opus-5

python3 analyze.py cap/req-001.json    # 3. read it
```

`CLAUDE_CONFIG_DIR` pointing at an empty directory is what isolates the vendor prompt from
your own `CLAUDE.md`, MCP servers and skills. Without it you are measuring your own config.

## Findings

Measured on CLI **2.1.220** (native binary), macOS. "Policy prose" excludes environment-injected
sections (`# Environment`, `# auto memory`, `# claudeMd`, `# Session-specific guidance`).

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

Section-level breakdown is in [docs/section-sizes.md](docs/section-sizes.md).

Two things stand out. First, the cut happened at **4.8**, not at 5 — and it has been partially
walked back since (4.8 is the trough at 5,041; Opus 5 adds back `# Delivering work` and
`# Corrections`; Fable 5 carries a 4,122-character `# Communicating with the user`). Net deletion
across three generations is about 26%, not 80%.

Second, Sonnet 5 and Haiku 4.5 are current models that still get the *legacy* prompt. That is a
routing artifact, not a design statement — see below.

## The routing is substring matching

Which prompt you get is decided by matching substrings against the model id string, not by a
model registry. You can demonstrate this without reading any code — invent model ids that cannot
possibly exist and see which prompt comes back:

| `--model` value | prompt received |
|---|---|
| `opus-5-sonnet-probe` | legacy (`# Doing tasks`) |
| `zzz-haiku-zzz` | legacy |
| `claude-3-probe` | legacy |
| `totally-made-up-model` | new (`# Harness`) |

A pure fiction containing `sonnet` routes to the legacy prompt. The new prompt is the default;
the legacy one is opt-in by substring.

## Gotchas

**Legacy model remap.** The CLI silently rewrites old model ids to the newest Opus. Probe 4.1
without `CLAUDE_CODE_DISABLE_LEGACY_MODEL_REMAP=1` and you are measuring Opus 5.

**Native binaries are opaque.** If `claude` is the ~250MB single-file build, strings are
compressed — `strings | grep "Doing tasks"` returns nothing. Static analysis needs the npm build
where `cli.js` ships as readable JavaScript. Capturing the request works on either.

**Your own config inflates everything.** On the author's machine the first capture came to 27,883
characters, of which 12,978 was a personal memory index being injected. Always probe from a clean
`CLAUDE_CONFIG_DIR` and an empty working directory.

## Scrubbing

`metadata.user_id` in every request contains a `device_id` and `session_id`. **Do not publish raw
captures.** `export.py` extracts only the system prompt body, drops locally-injected sections, and
rewrites home paths, emails, UUIDs and long hex strings before writing anything out.

## Prompt bodies

`prompts/` is not populated in this repo. Generate it locally:

```bash
python3 export.py ./cap ./prompts
```

## License

MIT for the scripts. Captured prompt text is Anthropic's, reproduced here only as the output of
running these tools against your own client.
