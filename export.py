#!/usr/bin/env python3
"""从抓到的请求体导出 system prompt 正文，剔除本机注入并做路径脱敏。

用法: export.py <capture_dir> <out_dir>
"""
import json, glob, os, re, sys

# 本机环境注入的整节，不属于官方 prompt，导出时整节剔除
DROP_SECTIONS = {"# auto memory", "# claudeMd"}

SCRUB = [
    (re.compile(r"/private/tmp/claude-\d+/[^\s`'\"]*"), "/tmp/workdir"),
    (re.compile(r"/Users/[A-Za-z0-9._-]+"), "/Users/USER"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "user@example.com"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{32,}\b"), "<hash>"),
]


def strip_sections(body):
    parts = re.split(r"^(# .+)$", body, flags=re.M)
    out = [parts[0]]
    for head, text in zip(parts[1::2], parts[2::2]):
        if head.strip() in DROP_SECTIONS:
            continue
        out.append(head + text)
    return "".join(out)


def scrub(text):
    for pat, rep in SCRUB:
        text = pat.sub(rep, text)
    return text


def main(cap_dir, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(cap_dir, "req-*.json"))):
        model = os.path.basename(f)[4:-5]
        d = json.load(open(f))
        body = max((b.get("text", "") for b in d["system"]), key=len)
        body = scrub(strip_sections(body))
        path = os.path.join(out_dir, f"{model}.md")
        with open(path, "w") as fh:
            fh.write(body)
        route = "new" if "# Harness" in body else "legacy"
        print(f"{model:<30} {len(body):>7,} 字符  [{route}]  -> {path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
