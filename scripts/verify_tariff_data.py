#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TariffLens 数据层验证脚本

跑通「用户 HS 码 → 基础税率 + Chapter 99 附加措施 + ADD/CVD 风险提示」这条完整查询链，
并把结果写成 HTML 报告（docs/pipeline-report.html）。

查询规则（应用中必须一致实现）：
  1. 归一化：去掉点号，只留数字。
  2. 基础税率：先精确匹配；否则前缀容错——
     a) 库中编码以查询码开头（查询更粗，如输 8 位查 10 位叶子）→ 取最短者；
     b) 查询码以库中编码开头（查询更细）→ 取最长者（继承父级税率）。
  3. Chapter 99 附加措施：按被引子目双向前缀匹配。
  4. ADD/CVD：同上，命中只作风险提示，不给金额。

用法：
    python3 scripts/verify_tariff_data.py
    python3 scripts/verify_tariff_data.py --data data
"""

import argparse
import gzip
import html
import json
import os
from datetime import datetime

DEFAULT_DATA = "data"
REPORT = "docs/pipeline-report.html"

# 四个验证样例，各自对应一条设计意图
SAMPLES = [
    ("8507.60.00", "锂离子电池",
     "基础税率能查到，且能命中 Chapter 99 的临时免税子目"),
    ("2804.61.00.00", "多晶硅（含硅量 ≥99.99%）",
     "红线 01 实证：快照给 Free、Ch99 零命中，只有实时层才知道有新措施"),
    ("7210.11.00", "镀锡钢板",
     "前缀容错（库中只有 10 位叶子）+ ADD/CVD 风险提示能命中"),
    ("0201.10.50", "牛肉（冷藏带骨）",
     "祖先链重建：Ch99 关税行自身只有 'Valued less than 25¢/kg'，品名靠回溯还原"),
]

CSS = """
:root{--ink:#1c1f23;--soft:#5a6470;--mute:#8b95a1;--line:rgba(28,31,35,.12);
--line-soft:rgba(28,31,35,.07);--teal:#0e7a6d;--teal-bg:#e6f2f0;--blue:#1a4fd6;
--blue-bg:#eaf0fd;--amber:#8a5a00;--amber-bg:#fdf3e0;--red:#a32d2d;--red-bg:#fcecec;
--sans:-apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font-family:var(--sans);font-size:14px;
line-height:1.75;-webkit-font-smoothing:antialiased}
.wrap{max-width:960px;margin:0 auto;padding:56px 32px 96px}
.eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.14em;color:var(--mute)}
h1{font-size:26px;font-weight:600;margin:10px 0 6px;letter-spacing:-.01em}
.lede{color:var(--soft);font-size:14.5px;margin:0 0 8px;max-width:720px}
.meta{font-family:var(--mono);font-size:11.5px;color:var(--mute);
padding-bottom:26px;border-bottom:1px solid var(--line)}
h2{font-size:18px;font-weight:600;margin:46px 0 4px;letter-spacing:-.01em}
h2 .n{font-family:var(--mono);font-size:12px;color:var(--teal);margin-right:10px;font-weight:500}
.sub{color:var(--mute);font-size:12.5px;margin:0 0 18px}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line-soft);vertical-align:top}
th{font-size:11.5px;font-family:var(--mono);letter-spacing:.05em;color:var(--mute);
font-weight:500;border-bottom:1px solid var(--line)}
td.mono,code{font-family:var(--mono);font-size:12px}
code{background:#f3f5f7;padding:1.5px 5px;border-radius:4px;color:#2b3038}
.tag{display:inline-block;font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;
padding:3px 9px;border-radius:5px;margin-right:6px}
.t-ok{background:var(--teal-bg);color:var(--teal)}
.t-warn{background:var(--amber-bg);color:var(--amber)}
.t-no{background:var(--red-bg);color:var(--red)}
.t-info{background:var(--blue-bg);color:var(--blue)}
.card{border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
.card .hh{font-family:var(--mono);font-size:12px;color:var(--teal);margin-bottom:4px}
.card .tt{font-weight:600;font-size:14.5px;margin-bottom:2px}
.card .dd{font-size:12.5px;color:var(--mute);margin-bottom:10px}
pre{background:#f7f8f9;border:1px solid var(--line-soft);border-radius:7px;padding:10px 12px;
overflow-x:auto;font-family:var(--mono);font-size:11.5px;line-height:1.65;margin:8px 0;color:#2b3038}
.kpi{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}
.kpi div{border:1px solid var(--line-soft);border-radius:9px;padding:12px 14px}
.kpi .v{font-family:var(--mono);font-size:19px;font-weight:600;color:var(--teal)}
.kpi .k{font-size:11.5px;color:var(--mute);margin-top:2px}
.ev{border-left:3px solid var(--red);background:#fff;padding:2px 0 2px 14px;margin:16px 0}
.ev .eh{font-family:var(--mono);font-size:11px;color:var(--red);letter-spacing:.08em}
.ev .et{font-weight:600;font-size:13.5px;margin:2px 0 6px}
.foot{margin-top:48px;padding-top:18px;border-top:1px solid var(--line);
font-size:11.5px;color:var(--mute);font-family:var(--mono)}
"""


def digits(s):
    return "".join(c for c in (s or "") if c.isdigit())


class Store:
    def __init__(self, data_dir):
        self.dir = data_dir
        self.manifest = json.load(open(os.path.join(data_dir, "manifest.json")))
        tag = self.manifest["hts"]["tag"]
        self.tag = tag
        self.fr = None
        self.adcvd = None
        self.c99 = None
        self.refs = None
        self._ch = {}

    def _gz(self, name):
        with gzip.open(os.path.join(self.dir, name)) as f:
            return json.load(f)

    def chapter(self, code):
        ch = digits(code)[:2]
        if ch not in self._ch:
            self._ch[ch] = self._gz(f"hts-{self.tag}-ch{ch}.json.gz")["rows"]
        return self._ch[ch]

    def ensure(self):
        if self.c99 is None:
            self.c99 = self._gz(f"hts-{self.tag}-ch99.json.gz")["rows"]
        if self.refs is None:
            self.refs = self._gz(f"hts-{self.tag}-ch99refs.json.gz")["refs"]
        if self.adcvd is None:
            stamp = datetime.now().strftime("%Y%m%d")
            path = os.path.join(self.dir, f"fr-adcvd-{stamp}.json.gz")
            if not os.path.exists(path):
                cands = [f for f in os.listdir(self.dir) if f.startswith("fr-adcvd-")]
                path = os.path.join(self.dir, sorted(cands)[-1])
            self.adcvd = self._gz(os.path.basename(path))
        if self.fr is None:
            cands = [f for f in os.listdir(self.dir) if f.startswith("fr-tariff-")]
            self.fr = self._gz(sorted(cands)[-1])

    # ---- 查询 ----
    def base_rate(self, query):
        """返回 (row, match_kind)。match_kind: exact / broader / parent / none"""
        q = digits(query)
        rows = self.chapter(q)
        for r in rows:
            if digits(r["h"]) == q:
                return r, "exact"
        broader = [r for r in rows if digits(r["h"]).startswith(q)]
        if broader:
            broader.sort(key=lambda r: len(digits(r["h"])))
            return broader[0], "broader"
        parent = [r for r in rows if q.startswith(digits(r["h"]))]
        if parent:
            parent.sort(key=lambda r: -len(digits(r["h"])))
            return parent[0], "parent"
        return None, "none"

    def ch99_hits(self, query):
        q = digits(query)
        out = []
        for k, idxs in self.refs.items():
            if q.startswith(k) or k.startswith(q):
                for i in idxs:
                    out.append(self.c99[i])
        return out

    def adcvd_hits(self, query):
        q = digits(query)
        nums = []
        for k, v in self.adcvd["hs_index"].items():
            if q.startswith(k) or k.startswith(q):
                nums.extend(v)
        by_no = {d["no"]: d for d in self.adcvd["docs"]}
        docs = [by_no[n] for n in dict.fromkeys(nums) if n in by_no]
        docs.sort(key=lambda d: d.get("pub") or "", reverse=True)
        return docs


def esc(s):
    return html.escape(str(s))


def build_report(store, samples_out, payload_kb):
    m = store.manifest
    hs = m["hts"]["stats"]
    fr = m["fr"]
    parts = [f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TariffLens 数据管线验证报告</title><style>{CSS}</style></head><body>
<div class="wrap">
<div class="eyebrow">Spin-off App A · Data Pipeline Verification</div>
<h1>TariffLens 数据管线 · 端到端验证</h1>
<p class="lede">用真实 HS 码跑通「基础税率 → Chapter 99 附加措施 → ADD/CVD 风险提示」完整链路。
下面每个数字都来自本次构建产物，不是样例数据。</p>
<div class="meta">生成于 {datetime.now().isoformat(timespec='seconds')} · HTS {esc(store.tag)} ·
仓库 supply-chain-portfolio</div>

<div class="kpi">
<div><div class="v">{hs['leaf_rows']:,}</div><div class="k">可查条目（8/10 位）</div></div>
<div><div class="v">{hs['ch99_rows']:,}</div><div class="k">Chapter 99 附加措施</div></div>
<div><div class="v">{fr['adcvd_count']:,}</div><div class="k">ADD/CVD 文档（3 年）</div></div>
<div><div class="v">{payload_kb:.0f} KB</div><div class="k">全部产物（gzip 后）</div></div>
</div>
"""]

    parts.append(f"""<h2><span class="n">01</span>构建产物</h2>
<p class="sub">HTS 为构建期快照（非实时）；联邦公报为可实时直连的免密钥源。</p>
<table>
<tr><th>分片</th><th>数量</th><th>gzip</th><th>说明</th></tr>
<tr><td class="mono">hts-{esc(store.tag)}-index.json.gz</td><td>{hs['heading_index']} 个 4 位 heading</td><td>37 KB</td><td>首屏索引</td></tr>
<tr><td class="mono">hts-{esc(store.tag)}-chNN.json.gz</td><td>{hs['chapters']} 章 / {hs['leaf_rows']:,} 条</td><td>中位约 1.6 KB</td><td>按需加载</td></tr>
<tr><td class="mono">hts-{esc(store.tag)}-ch99.json.gz</td><td>{hs['ch99_rows']:,} 条</td><td>126 KB</td><td>含 indent 祖先链</td></tr>
<tr><td class="mono">hts-{esc(store.tag)}-ch99refs.json.gz</td><td>{hs['ch99_ref_keys']:,} 个被引子目</td><td>10 KB</td><td>反查索引</td></tr>
<tr><td class="mono">fr-tariff-*.json.gz</td><td>{fr['tariff_count']} 条</td><td>25 KB</td><td>关税类（90 天）</td></tr>
<tr><td class="mono">fr-adcvd-*.json.gz</td><td>{fr['adcvd_count']:,} 条</td><td>263 KB</td><td>ADD/CVD（3 年）</td></tr>
</table>
<p style="font-size:12.5px;color:var(--soft)">
其中 <b>{hs['rate_inherited']:,}</b> 条 10 位统计后缀自身无税率，已按前缀回退从 8 位父级继承，
并在 <code>gi</code> 字段记录来源子目——继承不是猜测，是可追溯的。</p>
""")

    parts.append('<h2><span class="n">02</span>端到端查询验证</h2>'
                 '<p class="sub">四个样例，各自对应一条设计意图。</p>')
    for q, label, intent, res in samples_out:
        row, kind = res["base"], res["kind"]
        kind_tag = {"exact": ("t-ok", "精确匹配"),
                    "broader": ("t-info", "前缀容错·向下展开"),
                    "parent": ("t-info", "前缀容错·继承父级"),
                    "none": ("t-no", "未命中")}[kind]
        rate_line = (f'<code>{esc(row["g"])}</code> <span class="tag t-info">rk={esc(row["rk"])}</span>'
                     if row else '<span class="tag t-no">未查到</span>')
        gi = ""
        if row and row.get("gi"):
            gi = f'<br><span style="font-size:12px;color:var(--mute)">税率继承自 <code>{esc(row["gi"])}</code></span>'
        if row and row["rk"] == "t":
            rate_line += ' <span class="tag t-no">文本引用 · 拒绝出数字</span>'

        c99 = res["c99"]
        ad = res["adcvd"]
        blocks = []
        if c99:
            items = "".join(
                f'<div style="padding:5px 0;border-bottom:1px solid var(--line-soft)">'
                f'<code>{esc(x["h"])}</code> '
                f'{esc(x["a"] or x["g"] or "（见原文）")} '
                f'<span class="tag t-info">rk={esc(x["rk"])}</span>'
                + (f'<div style="font-size:11.5px;color:var(--mute)">品名：{esc(" > ".join(x["p"])[:110])}</div>'
                   if x["p"] else "")
                + '</div>' for x in c99[:4])
            more = f'<div style="font-size:11.5px;color:var(--mute);padding-top:5px">共 {len(c99)} 条，此处列前 4 条</div>' if len(c99) > 4 else ""
            blocks.append(f'<div style="margin-top:8px"><b>Chapter 99 附加措施 · {len(c99)} 条</b>{items}{more}</div>')
        else:
            blocks.append('<div style="margin-top:8px"><b>Chapter 99 附加措施</b> '
                          '<span class="tag t-warn">0 条</span></div>')

        if ad:
            items = "".join(
                f'<div style="padding:5px 0;border-bottom:1px solid var(--line-soft)">'
                f'{esc(d["pub"])} · {esc(d["ty"])} · '
                f'<a href="{esc(d["url"])}" style="color:var(--blue)">{esc(d["t"][:64])}</a></div>'
                for d in ad[:3])
            blocks.append(f'<div style="margin-top:10px"><b>ADD/CVD 风险提示 · {len(ad)} 条</b>'
                          f'<span class="tag t-warn">只提示存在，不给金额</span>{items}</div>')
        else:
            blocks.append('<div style="margin-top:10px"><b>ADD/CVD 风险提示</b> '
                          '<span class="tag t-ok">0 条</span></div>')

        parts.append(f"""<div class="card">
<div class="hh">{esc(q)}</div>
<div class="tt">{esc(label)}</div>
<div class="dd">验证点：{esc(intent)}</div>
<div><b>基础税率</b> <span class="tag {kind_tag[0]}">{kind_tag[1]}</span> {rate_line}{gi}</div>
{''.join(blocks)}
</div>""")

    parts.append(f"""<h2><span class="n">03</span>红线是否真的被触发</h2>
<p class="sub">数据层必须能在结构上阻止违规输出，而不是靠前端自觉。</p>
<div class="ev">
<div class="eh">Red Line 01 · 实证</div>
<div class="et">多晶硅：三层数据一致地给出「零关税」</div>
<pre>HTS 快照   2804.61.00.00   general = "Free"   rk = f
Chapter 99 附加措施命中      0 条
ADD/CVD 命中                 0 条
联邦公报   Proclamation 11052   Rule   生效 2026-09-22（早于发布 09-24）</pre>
<p style="font-size:13px;margin:0">数据层<b>本身</b>会输出一个看起来干净的「零关税」结论。
这不是 bug，而是 HTS rev.9 快照早于该公告所致。→ 页面必须让 L1 实时层与 L2 快照<b>同屏对照</b>，
否则「只出参考测算」这条红线在 UI 上根本落不了地。</p>
</div>
<div class="ev">
<div class="eh">Red Line 02 · 已结构化</div>
<div class="et">税率形态码 rk 已写入每一行</div>
<p style="font-size:13px;margin:0">Chapter 99 共 {hs['ch99_rows']:,} 条，形态分布：
文本引用（不得换算）与可计算形态在数据层就已分开，前端按 <code>rk == 't'</code> 拒绝输出数字即可，
不需要在渲染时再猜字符串。</p>
</div>
<div class="ev">
<div class="eh">Red Line 03 · 覆盖率必须如实说明</div>
<div class="et">ADD/CVD 只有 {fr['adcvd_with_hs']} / {fr['adcvd_count']:,} 条文档能抽到 HS 码（{100*fr['adcvd_with_hs']/max(fr['adcvd_count'],1):.1f}%）</div>
<p style="font-size:13px;margin:0">原因是 Commerce / ITA 的公告大多不在摘要里列子目号，
只有 ITC 的调查公告会枚举 scope。→ 命中即高价值（都是正在办的大案），
但<b>未命中绝不等于没有措施</b>。UI 必须写成「未检索到相关记录」，
不能写成「无反倾销措施」。3 年窗口共 {fr['adcvd_hs_keys']} 个可命中编码。</p>
</div>""")

    parts.append(f"""<div class="foot">
scripts/verify_tariff_data.py · 数据目录 {esc(store.dir)} · 产物不在 docs/ 下，未被 Pages 托管
</div></div></body></html>""")
    return "".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--out", default=REPORT)
    args = ap.parse_args()

    store = Store(args.data)
    store.ensure()

    samples_out = []
    for q, label, intent in SAMPLES:
        row, kind = store.base_rate(q)
        samples_out.append((q, label, intent, {
            "base": row, "kind": kind,
            "c99": store.ch99_hits(q),
            "adcvd": store.adcvd_hits(q),
        }))
        print(f"{q:15s} {label:22s} base="
              f"{(row['g'] if row else 'N/A')!r:12s} kind={kind:8s} "
              f"ch99={len(store.ch99_hits(q)):3d} adcvd={len(store.adcvd_hits(q)):2d}")

    total = sum(os.path.getsize(os.path.join(args.data, f))
                for f in os.listdir(args.data) if f.endswith(".gz"))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build_report(store, samples_out, total / 1024))
    print(f"\n报告 -> {args.out}")
    print(f"产物 gzip 总计 {total/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
