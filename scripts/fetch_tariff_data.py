#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TariffLens 数据管线（构建期预取）

三个子命令：
    hts   下载 USITC HTS 整表 → 重建 Chapter 99 祖先链 → 按章切 gzip 分片
    fr    抓取 Federal Register 关税/反倾销文档 → 快照 + 抽取 HS 码映射
    all   依次执行上面两步

产出目录（默认 data，相对仓库根；改回 --out 可指向别处）：
    hts-<tag>-index.json.gz     4 位 heading 索引（首屏用）
    hts-<tag>-chNN.json.gz      按章分片（按需加载）
    hts-<tag>-ch99.json.gz      Chapter 99 附加措施（含重建后的祖先链）
    hts-<tag>-ch99refs.json.gz  被引子目 → Ch99 条目 反查索引
    fr-tariff-<stamp>.json      关税类联邦公报文档
    fr-adcvd-<stamp>.json       反倾销/反补贴文档 + HS 码映射
    manifest.json               版本、抓取时间、各分片体积与 sha256

设计约束（对应规格书三条红线）：
  - 只做「取数 + 结构化」，不做任何税率计算或归类推断。
  - 税率字段一律保留原文，另存 rk 形态码；文本引用形态（rk=t）由前端拒绝输出数字。
  - Chapter 99 的产品名不在关税行上，必须按 indent 回溯祖先链还原，否则检索 0 命中。

用法：
    python3 scripts/fetch_tariff_data.py all
    python3 scripts/fetch_tariff_data.py hts --rev 9 --year 2026
    python3 scripts/fetch_tariff_data.py fr  --days 90
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

UA = "TariffLens-build/0.1 (static research site; contact: repo owner)"
HTS_URL = ("https://www.usitc.gov/sites/default/files/tata/hts/"
           "hts_{year}_revision_{rev}_json.json")
FR_API = "https://www.federalregister.gov/api/v1/documents.json"

DEFAULT_OUT = "data"
DEFAULT_CACHE = "cache"

# 联邦公报字段（尽量少，够用即可）
FR_FIELDS = [
    "document_number", "title", "type", "publication_date",
    "effective_on", "comments_close_on", "agencies", "abstract",
    "html_url", "citation", "action",
]

# HTS 码形态：4.2 / 4.2.2 / 4.2.2.2，均带点，避免误匹配日期与文号
HS_RE = re.compile(r"\b(\d{4}\.\d{2}(?:\.\d{2}){0,2})\b")


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def http_get(url, timeout=120, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:               # noqa: BLE001
            last = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"下载失败 {url} -> {last}")


def write_gzip(path, obj):
    """确定性 gzip（mtime=0），便于复现与 diff。返回 (裸字节数, gzip字节数)。"""
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as f:
        f.write(raw)
    data = buf.getvalue()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return len(raw), len(data)


def write_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def kb(n):
    return f"{n/1024:.1f} KB"


def digits(code):
    """'0201.10.50' -> '02011050'（匹配用，两端前缀比较）"""
    return re.sub(r"[^0-9]", "", code or "")


# --------------------------------------------------------------------------
# 税率形态分类（对应红线 02：文本引用形态不得换算）
# --------------------------------------------------------------------------

def classify_rate(s):
    """返回形态码：p=从价%  s=从量  c=复合  f=Free  t=文本引用(禁止换算)  e=空"""
    t = (s or "").strip()
    if not t:
        return "e"
    low = t.lower()
    if low == "free":
        return "f"
    # 复合：同时出现 % 与每单位金额（如 '2.5% + 5¢/kg'）
    if "%" in t and ("¢" in t or "$" in t):
        return "c"
    if re.fullmatch(r"[\d.,]+\s*%.*", t) or re.match(r"^\d+(\.\d+)?\s*%", t):
        return "p"
    if "¢" in t or re.search(r"\$\s*[\d.,]+\s*(per|/)\s*\w+", low):
        return "s"
    # 其余一律视为文本引用：如 "The duty provided in the applicable subheading"
    return "t"


def product_name(title):
    """从 'Tin Mill Products From China, Taiwan, and Turkey; Scheduling...'
    抽出 'Tin Mill Products'。用于无 HS 码时的模糊命中提示。"""
    head = re.split(r"\s+From\s+", title or "", maxsplit=1)[0]
    head = re.split(r"\s*[;:]\s*", head, maxsplit=1)[0]
    return head.strip()


# --------------------------------------------------------------------------
# HTS：下载 → 祖先链重建 → 按章分片
# --------------------------------------------------------------------------

def load_hts(year, rev, cache_dir, force):
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, f"hts_{year}_revision_{rev}_json.json")
    if os.path.exists(cached) and not force:
        log(f"使用缓存 {cached} ({kb(os.path.getsize(cached))})")
    else:
        url = HTS_URL.format(year=year, rev=rev)
        log(f"下载 {url}")
        data = http_get(url, timeout=180)
        if len(data) < 1_000_000:
            raise RuntimeError(f"响应过小（{len(data)} 字节），疑似不是整表：{url}")
        with open(cached, "wb") as f:
            f.write(data)
        log(f"已缓存 {cached} ({kb(len(data))})")
    with open(cached, encoding="utf-8") as f:
        return json.load(f)


def build_all_ancestors(rows):
    """一次性用单调栈为所有行算出品名祖先链，O(n)。

    HTS 是缩进编码的树：一行的祖先 = 上方最近的一串 indent 严格递减的行。
    叶子自身的 description 常常不可读（'Other'、'Of a thickness of 0.5 mm
    or more'），真正的品名在祖先链里。

    踩过的坑：不能只取 superior=true 的标题行。Ch1–98 里大量父级是**带
    htsno 的编码行**（如 0201.10 'Carcasses and half-carcasses:'），只取
    superior 会跳过它们，把 0201.10.50 误挂到更早的 'Insects:' 上。
    判据只有 indent，跟 superior / htsno 无关。
    """
    out = [None] * len(rows)
    stack = []  # [(indent, description)]，栈底 = 章根
    for i, r in enumerate(rows):
        ind = int(r["indent"])
        while stack and stack[-1][0] >= ind:
            stack.pop()
        out[i] = [d for _, d in stack]
        stack.append((ind, r["description"].strip()))
    return out


def cmd_hts(args):
    rows = load_hts(args.year, args.rev, args.cache, args.force)
    log(f"HTS 整表载入：{len(rows)} 行")

    tag = f"{args.year}rev{args.rev}"
    out = args.out
    os.makedirs(out, exist_ok=True)
    manifest_files = []

    def record(path, raw_n, gz_n, note=""):
        manifest_files.append({
            "file": os.path.basename(path),
            "raw": raw_n, "gzip": gz_n, "sha256": sha256(path), "note": note,
        })
        log(f"  {os.path.basename(path):34s} {kb(gz_n):>10s}  {note}")

    # ---- 1) 4 位 heading 索引（首屏） ----
    heads = []
    for r in rows:
        h = r["htsno"]
        if h and len(digits(h)) == 4 and not h.startswith("99"):
            heads.append({"h": h, "d": r["description"].strip()})
    p = os.path.join(out, f"hts-{tag}-index.json.gz")
    record(p, *write_gzip(p, {"tag": tag, "kind": "heading-index", "rows": heads}),
           note=f"{len(heads)} 个 4 位 heading")

    # ---- 2) 按章分片（Ch1–98，8 位 + 10 位） ----
    # 税率挂在 8 位层级，10 位统计后缀约 59% 为空 -> 建立继承表，逐位前缀回退
    rate_map = {}
    for r in rows:
        h = r["htsno"]
        if not h or h.startswith("99"):
            continue
        if not (r["general"] or "").strip():
            continue
        rate_map[digits(h)] = (r["general"], r["special"] or "", r["other"] or "")

    def inherit(dd):
        for n in range(len(dd) - 1, 1, -1):
            if dd[:n] in rate_map:
                return rate_map[dd[:n]], dd[:n]
        return None, None

    # 祖先链：叶子描述常为 'Other' / 'Of a thickness of 0.5 mm or more'，
    # 单独看不可读，必须带上从章根下来的完整品名路径（也为关键词检索提供词源）
    ancestors = build_all_ancestors(rows)

    by_ch = {}
    inherited = 0
    for i, r in enumerate(rows):
        h = r["htsno"]
        if not h or h.startswith("99"):
            continue
        dd = digits(h)
        if len(dd) not in (8, 10):
            continue
        g = (r["general"] or "").strip()
        src = None
        if g:
            s_o = r["special"] or ""
            o_o = r["other"] or ""
        else:
            inh, src = inherit(dd)
            if inh:
                g, s_o, o_o = inh
                inherited += 1
            else:
                s_o, o_o = r["special"] or "", r["other"] or ""
        row = {"h": h, "d": r["description"].strip(), "p": ancestors[i],
               "g": g, "s": s_o, "o": o_o, "rk": classify_rate(g)}
        if src:
            row["gi"] = src          # 税率继承自哪个子目（透明度）
        by_ch.setdefault(h[:2], []).append(row)
    leaf_total = 0
    for ch in sorted(by_ch):
        shard = by_ch[ch]
        p = os.path.join(out, f"hts-{tag}-ch{ch}.json.gz")
        record(p, *write_gzip(p, {"tag": tag, "chapter": ch, "rows": shard}),
               note=f"{len(shard)} 条")
        leaf_total += len(shard)
    log(f"  按章分片共 {len(by_ch)} 个，条目 {leaf_total} 条"
        f"（其中 {inherited} 条税率由 8 位父级继承）")

    # ---- 3) Chapter 99 附加措施（含祖先链 + 被引用子目） ----
    ch99 = []
    for i, r in enumerate(rows):
        h = r["htsno"]
        if not h or not h.startswith("99"):
            continue
        path = ancestors[i]
        blob = " ".join(path) + " " + r["description"]
        # refs = 被引用的产品子目（用于反查）；xr = Chapter 99 内部交叉引用，
        # 形如 9903.01.26，是措施之间的跳转，不是商品编码，不能进反查索引
        found = sorted({digits(x) for x in HS_RE.findall(blob)})
        refs = [x for x in found if not x.startswith("99")]
        xr = [x for x in found if x.startswith("99")]
        g = r["general"] or ""
        ch99.append({
            "h": h,
            "d": r["description"].strip(),
            "p": path,
            "g": g,
            "s": r["special"] or "",
            "o": r["other"] or "",
            "a": r.get("additionalDuties") or "",
            "rk": classify_rate(g or (r.get("additionalDuties") or "")),
            "refs": refs,
            "xr": xr,
        })
    p = os.path.join(out, f"hts-{tag}-ch99.json.gz")
    record(p, *write_gzip(p, {"tag": tag, "chapter": "99", "rows": ch99}),
           note=f"{len(ch99)} 条（含祖先链）")

    # ---- 4) 反查索引：被引子目 → Ch99 条目下标 ----
    ref_index = {}
    for i, row in enumerate(ch99):
        for ref in row["refs"]:
            ref_index.setdefault(ref, []).append(i)
    covered = sum(1 for row in ch99 if row["refs"])
    p = os.path.join(out, f"hts-{tag}-ch99refs.json.gz")
    record(p, *write_gzip(p, {"tag": tag, "kind": "ch99-ref-index",
                              "refs": {k: v for k, v in sorted(ref_index.items())}}),
           note=f"{len(ref_index)} 个被引子目（{covered}/{len(ch99)} 条可反查）")

    stats = {
        "total_rows": len(rows),
        "leaf_rows": leaf_total,
        "rate_inherited": inherited,
        "chapters": len(by_ch),
        "ch99_rows": len(ch99),
        "ch99_with_refs": covered,
        "ch99_ref_keys": len(ref_index),
        "heading_index": len(heads),
    }
    return {"tag": tag, "stats": stats, "files": manifest_files}


# --------------------------------------------------------------------------
# Federal Register：关税文档 + 反倾销/反补贴映射
# --------------------------------------------------------------------------

def fr_query(term, since, extra=None, max_pages=20):
    """分页拉取。conditions[term] 为关键词串；since 为 ISO 日期。"""
    out, page = [], 1
    while page <= max_pages:
        params = [
            ("per_page", "1000"), ("page", str(page)), ("order", "newest"),
            ("conditions[term]", term),
            ("conditions[publication_date][gte]", since),
        ]
        for f in FR_FIELDS:
            params.append(("fields[]", f))
        for k, v in (extra or {}).items():
            params.append((k, v))
        url = FR_API + "?" + urllib.parse.urlencode(params)
        try:
            data = json.loads(http_get(url, timeout=60).decode("utf-8"))
        except Exception as e:                        # noqa: BLE001
            log(f"  ! 第 {page} 页失败：{e}")
            break
        results = data.get("results") or []
        out.extend(results)
        if len(out) >= (data.get("count") or 0) or not results:
            break
        page += 1
        time.sleep(0.4)
    return out


def slim_doc(r):
    return {
        "no": r.get("document_number"),
        "t": r.get("title", "").strip(),
        "ty": r.get("type"),
        "pub": r.get("publication_date"),
        "eff": r.get("effective_on"),
        "close": r.get("comments_close_on"),
        "ag": [a.get("name") for a in (r.get("agencies") or [])],
        "ab": (r.get("abstract") or "").strip(),
        "url": r.get("html_url"),
        "cite": r.get("citation"),
        "act": r.get("action"),
    }


def cmd_fr(args):
    out = args.out
    os.makedirs(out, exist_ok=True)
    since = (date.today() - timedelta(days=args.days)).isoformat()
    stamp = date.today().isoformat().replace("-", "")
    res = {"since": since, "days": args.days, "files": []}

    def record(path, raw_n, gz_n, note=""):
        res["files"].append({"file": os.path.basename(path), "raw": raw_n,
                             "gzip": gz_n, "sha256": sha256(path), "note": note})
        log(f"  {os.path.basename(path):34s} {kb(gz_n):>10s}  {note}")

    # ---- 1) 关税类（政策流，窗口较短） ----
    log(f"拉取关税类文档（'Harmonized Tariff Schedule'，自 {since} 起）")
    seen, docs = set(), []
    for r in fr_query("Harmonized Tariff Schedule", since):
        k = r.get("document_number")
        if k in seen:
            continue
        seen.add(k)
        docs.append(slim_doc(r))
    docs.sort(key=lambda x: (x["pub"] or ""), reverse=True)
    p = os.path.join(out, f"fr-tariff-{stamp}.json.gz")
    record(p, *write_gzip(p, {"fetched_at": datetime.now().isoformat(timespec="seconds"),
                              "since": since, "term": "Harmonized Tariff Schedule",
                              "count": len(docs), "docs": docs}),
           note=f"{len(docs)} 条")
    res["tariff_count"] = len(docs)

    # ---- 2) 反倾销 / 反补贴（措施存续多年，窗口要长） ----
    since_ad = (date.today() - timedelta(days=args.adcvd_days)).isoformat()
    log(f"拉取反倾销/反补贴文档（自 {since_ad} 起，约 {args.adcvd_days} 天）")
    seen, adcvd = set(), []
    for term in ("antidumping", "countervailing duty"):
        for r in fr_query(term, since_ad, max_pages=40):
            k = r.get("document_number")
            if k in seen:
                continue
            seen.add(k)
            d = slim_doc(r)
            d["hs"] = sorted({digits(x) for x in HS_RE.findall(d["t"] + " " + d["ab"])})
            d["pn"] = product_name(d["t"])   # 用于无 HS 码时的模糊提示
            adcvd.append(d)
    adcvd.sort(key=lambda x: (x["pub"] or ""), reverse=True)

    hs_index = {}
    for d in adcvd:
        for code in d["hs"]:
            hs_index.setdefault(code, []).append(d["no"])
    matched = sum(1 for d in adcvd if d["hs"])
    # 摘要只保留「抽到 HS 码」的条目：那是能被精确命中的证据文本，
    # 其余条目留标题即可，避免 3 年窗口把体积撑爆
    shipped = []
    for d in adcvd:
        if d["hs"]:
            shipped.append(d)
        else:
            shipped.append({k: v for k, v in d.items() if k != "ab"})
    p = os.path.join(out, f"fr-adcvd-{stamp}.json.gz")
    record(p, *write_gzip(p, {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "since": since_ad, "window_days": args.adcvd_days,
        "terms": ["antidumping", "countervailing duty"],
        "count": len(adcvd), "with_hs": matched,
        "hs_index": {k: v for k, v in sorted(hs_index.items())},
        "note": ("hs 由标题/摘要文本抽取，覆盖率有限（多数 Commerce 公告不列子目号）；"
                 "命中仅作风险提示，不代表措施仍在效，也不用于计算金额"),
        "docs": shipped}),
           note=f"{len(adcvd)} 条，{matched} 条含 HS 码，{len(hs_index)} 个码")
    res["adcvd_count"] = len(adcvd)
    res["adcvd_with_hs"] = matched
    res["adcvd_hs_keys"] = len(hs_index)
    res["adcvd_since"] = since_ad
    return res


# --------------------------------------------------------------------------

def write_manifest(out, parts):
    path = os.path.join(out, "manifest.json")
    # 单跑 hts 或 fr 时保留另一半的旧记录，避免 manifest 缺胳膊少腿
    old = {}
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {}
    m = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator": "scripts/fetch_tariff_data.py",
        "hts": parts.get("hts") or old.get("hts"),
        "fr": parts.get("fr") or old.get("fr"),
        "notes": [
            "HTS 为构建期快照（非实时），页面必须标注版本与抓取日期。",
            "税率字段一律保留原文；rk=t 表示文本引用，前端禁止换算成数字（红线 02）。",
            "Chapter 99 的 p 字段为按 indent 回溯还原的祖先链，产品名在此而非 d 字段（红线相关实现要点）。",
            "fr-adcvd 的 hs 来自文本抽取，存在缺漏与误报，仅作存在性风险提示（红线 03）。",
        ],
    }
    write_json(path, m)
    log(f"manifest -> {path}")


def main():
    ap = argparse.ArgumentParser(description="TariffLens 数据管线")
    ap.add_argument("cmd", choices=["hts", "fr", "all"])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--cache", default=DEFAULT_CACHE)
    ap.add_argument("--year", type=int, default=date.today().year)
    ap.add_argument("--rev", type=int, default=9)
    ap.add_argument("--days", type=int, default=90, help="关税类文档窗口（天）")
    ap.add_argument("--adcvd-days", type=int, default=1095,
                    help="反倾销/反补贴窗口（天），措施存续多年，默认 3 年")
    ap.add_argument("--force", action="store_true", help="忽略 HTS 本地缓存重新下载")
    args = ap.parse_args()

    parts = {}
    t0 = time.time()
    try:
        if args.cmd in ("hts", "all"):
            log("=== HTS ===")
            parts["hts"] = cmd_hts(args)
        if args.cmd in ("fr", "all"):
            log("=== Federal Register ===")
            parts["fr"] = cmd_fr(args)
    except Exception as e:                            # noqa: BLE001
        log(f"失败：{e}")
        return 1

    if parts:
        write_manifest(args.out, parts)
        h = parts.get("hts")
        if h:
            s = h["stats"]
            log(f"HTS 汇总：{s['total_rows']} 行 / 叶子 {s['leaf_rows']} / "
                f"{s['chapters']} 章 / Ch99 {s['ch99_rows']} 条"
                f"（其中 {s['ch99_with_refs']} 条可反查，{s['ch99_ref_keys']} 个被引子目）")
        f = parts.get("fr")
        if f:
            log(f"FR 汇总：关税 {f['tariff_count']} 条；"
                f"ADD/CVD {f['adcvd_count']} 条（{f['adcvd_with_hs']} 条含 HS 码，"
                f"{f['adcvd_hs_keys']} 个码）")
        log(f"完成，用时 {time.time()-t0:.1f}s，产物在 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
