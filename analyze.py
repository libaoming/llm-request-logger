#!/usr/bin/env python3
import json, sys, re

d = json.load(open(sys.argv[1]))
sysblocks = d["system"] if isinstance(d.get("system"), list) else [{"text": d.get("system", "")}]
print(f"model      : {d.get('model')}")
print(f"system 块数: {len(sysblocks)}")
total = 0
for i, b in enumerate(sysblocks):
    t = b.get("text", "")
    total += len(t)
    print(f"  [{i}] {len(t):>7,} 字符  cache={'Y' if b.get('cache_control') else 'n'}  首行: {t.splitlines()[0][:70] if t.splitlines() else ''}")
print(f"system 合计: {total:,} 字符")
print(f"tools      : {len(d.get('tools', []))} 个, {len(json.dumps(d.get('tools', []))):,} 字符")

body = sysblocks[-1].get("text", "")
secs = re.split(r"^(# .+)$", body, flags=re.M)
print("\n--- 主 system 块分节 ---")
if len(secs) > 1:
    pre = secs[0]
    if pre.strip():
        print(f"  (前言) {len(pre):>6,}")
    for h, t in zip(secs[1::2], secs[2::2]):
        print(f"  {h:<45} {len(h)+len(t):>6,}")
if len(sys.argv) > 2:
    open(sys.argv[2], "w").write(body)
    print(f"\n主块已写出 -> {sys.argv[2]}")
