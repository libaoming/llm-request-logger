"""比较两份抓包的缓存前缀：从哪一段、哪个字符开始不一样。

缓存按 tools → system → messages 的顺序做前缀匹配，某处变了，它后面的缓存全部失效。
"""
from common import cache_breakpoints, load, prefix_segments


def first_divergence(a, b):
    """返回 (段序号, 段内字符偏移)；一方是另一方的完整前缀时返回 (较短方的段数, None)。"""
    for i, ((_, ta), (_, tb)) in enumerate(zip(a, b)):
        if ta != tb:
            k = next((j for j, (x, y) in enumerate(zip(ta, tb)) if x != y), min(len(ta), len(tb)))
            return i, k
    return min(len(a), len(b)), None


def usage_line(env):
    u = (env.get("response") or {}).get("usage") or {}
    return "  ".join(f"{k}={u[k]}" for k in ("input_tokens", "cache_creation_input_tokens",
                                             "cache_read_input_tokens", "output_tokens") if k in u) or "无"


def print_diff(path_a, path_b, context=70):
    ea, eb = load(path_a), load(path_b)
    for path, env in ((path_a, ea), (path_b, eb)):
        if not isinstance(env["request"], dict):
            raise SystemExit(f"{path} 不是一份可比较的请求")
    a, b = prefix_segments(ea["request"]), prefix_segments(eb["request"])
    i, k = first_divergence(a, b)
    same_chars = sum(len(t) for _, t in a[:i]) + (k or 0)
    print(f"A  {path_a}\n   {len(a)} 段，用量 {usage_line(ea)}")
    print(f"B  {path_b}\n   {len(b)} 段，用量 {usage_line(eb)}")
    print(f"\n前缀一致到：第 {i} 段之前，共 {same_chars:,} 字符")
    if k is None:
        if len(a) == len(b):
            print("结论：两份请求的可缓存内容完全一致。")
        else:
            short, long_, segs = ("A", "B", b) if len(a) < len(b) else ("B", "A", a)
            print(f"结论：{short} 是 {long_} 的完整前缀，内容上没有任何地方会让缓存失效。{long_} 多出的段：")
            for name, text in segs[i:]:
                print(f"  + {name}  ({len(text):,} 字符)")
    else:
        name_a, ta = a[i]
        name_b, tb = b[i]
        print(f"结论：从这一段开始不同，它和它后面的缓存全部失效。")
        print(f"  A 段名  {name_a}\n  B 段名  {name_b}\n  段内偏移 {k:,}")
        lo = max(0, k - context)
        show = lambda t: t.replace("\x00", " | ")
        print(f"  A: …{show(ta[lo:k])}【{show(ta[k:k + context])}】")
        print(f"  B: …{show(tb[lo:k])}【{show(tb[k:k + context])}】")
    print(f"\n缓存断点  A: {cache_breakpoints(ea['request']) or '无'}\n          B: {cache_breakpoints(eb['request']) or '无'}")
    print("断点标记本身不参与比较。实际命中多少还取决于缓存有效期（5 分钟或 1 小时）和断点位置，以用量里的 cache_read 为准。")
    return i, k
