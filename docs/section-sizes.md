# Section sizes by model

CLI 2.1.220, native binary, macOS. Character counts of each `# ` section of the main system
prompt block, measured from captured requests. `-` means the section is absent for that model.

Environment-injected sections (`# Environment`, `# auto memory`, `# claudeMd`,
`# Session-specific guidance`) are excluded — they vary with your machine, not with the model.

| section | 4-1 | 4-7 | 4-5 | sonnet-5 | haiku-4-5 | 4-8 | opus-5 | fable-5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `# System` | 1,627 | 1,627 | 1,627 | 1,627 | 1,627 | - | - | - |
| `# Doing tasks` | 3,321 | 3,321 | 3,321 | 3,321 | 3,321 | - | - | - |
| `# Executing actions with care` | 3,585 | 3,585 | 3,585 | 3,585 | 3,585 | - | - | - |
| `# Using your tools` | 752 | 752 | 752 | 752 | 752 | - | - | - |
| `# Tone and style` | 557 | 557 | 557 | 557 | 557 | - | - | - |
| `# Text output (does not apply to tool calls)` | 1,701 | 1,701 | 1,701 | 1,701 | 1,701 | - | - | - |
| `# Harness` | - | - | - | - | - | 1,702 | 1,647 | 670 |
| `# Memory` | - | - | - | - | - | 2,238 | 2,238 | 2,238 |
| `# Delivering work` | - | - | - | - | - | - | 2,019 | - |
| `# Corrections` | - | - | - | - | - | - | 1,368 | - |
| `# Communicating with the user` | - | - | - | - | - | - | - | 4,122 |
| `# Context management` | 559 | 559 | 559 | 559 | 559 | 559 | 561 | 1,915 |
| **policy prose total** | **12,938** | **12,938** | **12,938** | **12,938** | **12,938** | **5,041** | **8,375** | **9,487** |

All eight captures carry the same 25 tool definitions. That count is inflated: these runs did not set
`ENABLE_TOOL_SEARCH=true`, so the CLI wrote every tool schema into the request. See the README section
"The observer effect". The system prompt text is unaffected.

## Reading the table

The legacy column is identical across five model ids, including two current-generation models
(Sonnet 5, Haiku 4.5). Six hand-written policy sections disappear on the new path and are replaced
by a smaller set.

What replaced them is not nothing. `# Harness` on the new path is descriptive — it says what the
environment is like (markdown renders in a terminal, a denied tool call means the user declined,
`file:line` is clickable), not what to do. But `# Communicating with the user` and the expanded
`# Context management` on Fable 5 are prescriptive in the same way the deleted sections were:
state the outcome first, put everything the user needs in the final message, don't compress prose
into arrow chains, confirm before irreversible actions, act when you have enough information.

So the trajectory reads less like a deletion and more like a rewrite that briefly overshot:

```
  12,938  ──▶  5,041  ──▶  8,375  ──▶  9,487
  legacy       4.8         opus-5      fable-5
               (trough)
```

`# Memory` is new-path only and has no legacy counterpart. It specifies a file-based long-term
memory: one fact per file, YAML frontmatter with a `type` of user/feedback/project/reference,
`[[wikilink]]` cross-references, and a `MEMORY.md` index that is loaded every session.
