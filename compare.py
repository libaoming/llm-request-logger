#!/usr/bin/env python3
"""对比多个 model 的 system prompt 分节。排除环境注入节（memory/环境/session），只数手写策略正文。"""
import json, glob, re, os, sys

# 这些节是本机环境注入的，不属于官方手写策略正文
ENV_SECS = {"# auto memory", "# Environment", "# claudeMd", "# Session-specific guidance"}

rows = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], "req-*.json"))):
    m = os.path.basename(f)[4:-5]
    d = json.load(open(f))
    blocks = d["system"]
    body = max((b.get("text", "") for b in blocks), key=len)
    parts = re.split(r"^(# .+)$", body, flags=re.M)
    secs, pre = {}, parts[0]
    for h, t in zip(parts[1::2], parts[2::2]):
        secs[h.strip()] = len(h) + len(t)
    hand = sum(v for k, v in secs.items() if k not in ENV_SECS) + len(pre)
    rows[m] = {"total": len(body), "hand": hand, "secs": secs, "pre": len(pre),
               "tools": len(d.get("tools", []))}

order = ["claude-opus-4-1-20250805", "claude-opus-4-7", "claude-opus-4-5-20251101",
         "claude-sonnet-5", "claude-haiku-4-5-20251001",
         "claude-opus-4-8", "claude-opus-5", "claude-fable-5"]
order = [m for m in order if m in rows] + [m for m in rows if m not in order]

print(f"{'model':<28} {'system总':>9} {'手写正文':>9} {'tools':>6}")
for m in order:
    r = rows[m]
    print(f"{m:<28} {r['total']:>9,} {r['hand']:>9,} {r['tools']:>6}")

allsecs = []
for m in order:
    for k in rows[m]["secs"]:
        if k not in allsecs:
            allsecs.append(k)

print(f"\n{'节':<46}" + "".join(f"{m.replace('claude-','')[:11]:>13}" for m in order))
for s in allsecs:
    if s in ENV_SECS:
        continue
    print(f"{s:<46}" + "".join(f"{rows[m]['secs'].get(s, 0) or '-':>13}" for m in order))
