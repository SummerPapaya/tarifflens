<h1 align="center" style="font-size:2.4rem;letter-spacing:.06em;margin-bottom:.2rem">TariffLens</h1>
<p align="center"><strong>U.S. HTS Duty Reference Desk · 关税测算参考台</strong></p>

<p align="center">
  <strong>English</strong> ·
  <a href="README.md">简体中文</a>
</p>

![TariffLens](assets/hero.svg)

<p align="center">
  <img alt="deploy" src="https://img.shields.io/badge/deploy-GitHub%20Pages-1a4fd6">
  <img alt="build" src="https://img.shields.io/badge/build%20step-none-656d76">
  <img alt="keys" src="https://img.shields.io/badge/API%20keys-none-0e7a6d">
  <img alt="lang" src="https://img.shields.io/badge/i18n-zh%20%2F%20en-0969da">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-1a7f37">
</p>

Enter an HTS subheading and see which measures apply to it today, where each number comes from — and, just as importantly, **which parts this tool refuses to compute for you**.

> **Scope (important)**: this covers **US imports only**. The tariff schedule comes from the USITC HTS 2026 rev.9, measures from the Federal Register (including AD/CVD and §232 / §301 style proclamations), and fees from CBP FY2026 MPF / HMF.
> The EU (TARIC), the UK (UK Trade Tariff), China and every other market are **out of scope** — each has its own sources and its own conventions; this is not a switch you can flip.

TariffLens is the second entry (#2 Tariff & trade-compliance automation) in the *spin-off apps* series of [supply-chain-portfolio](https://github.com/SummerPapaya/supply-chain-portfolio). It is a **purely static site**: no backend, no build step, no API keys. All data is pre-fetched at build time and shipped with the repository; the browser reads it directly.

> Below the "reference estimates only" block sits a **collapsed-by-default**, scope-independent **Scenario estimate — including §232 additional measures**: it **counts only measures already in force**, and it is **for reference only**. The boundary between the two is spelled out in the red-lines section below.

- **Live demo**: https://summerpapaya.github.io/tarifflens/ (available once Pages is enabled)
- **Specification**: [`docs/spec.html`](docs/spec.html) (v1.3 — all 12 design decisions confirmed and implemented)
- **Pipeline verification report**: [`docs/pipeline-report.html`](docs/pipeline-report.html)

---

## 1. Three red lines (product logic, not a disclaimer)

The boundary of what this tool will do is defined before any feature is. These three rules render as **visible state on every query** — never collapsed, never buried in a footer:

| # | Red line | Behaviour |
|---|----------|-----------|
| 01 | **No automatic HS classification** | Reference estimates only. Results are shown for whatever subheading you enter; the tool never decides which subheading a product belongs to. |
| 02 | **No numbers from cross-reference wording** | When a rate reads `"The duty provided in..."` (form code `rk=t`), no number is produced or estimated — only the cited source text. |
| 03 | **Three-way split for uncovered items** | Fees (MPF / HMF) are computable → shown normally; ADD/CVD yields an **existence notice only**, never an amount; FTA / origin / classification → read-only notice plus disclaimer. |

> **"Reference estimates only" is a hard rule, and the scenario estimate does not relax it.** The reference estimate keeps its exact scope, wording and algorithm — base duty + MPF + HMF, Chapter 99 surcharges excluded. A separate, **scope-independent** block sits below it: *Scenario estimate — including §232 additional measures*. It **counts only measures whose effective date has passed** (every measure carries its date), and the rate tier is **declared by you** from the published proclamation (each tier is labelled with its Chapter 99 subheading and source — never reverse-engineered from `rk=t` cross-reference wording, so red line 02 still holds). Non-ad-valorem minimum import prices (MIP) are **listed, never converted**. The block is **for reference only**, and the two estimates never contaminate each other.

## 2. Three-layer data architecture

| Layer | Source | Delivery | Notes |
|-------|--------|----------|-------|
| L2 live | [Federal Register API](https://www.federalregister.gov/api/v1/documents.json) | Browser, direct | CORS `*`, no key. Pulls the last 90 days of tariff and AD/CVD documents, including `effective_on` and `comments_close_on`. |
| L1 snapshot | USITC HTS 2026 rev.9 full table | Pre-fetched at build time | 35,502 rows → gzip shards per chapter, decompressed in-browser with `DecompressionStream('gzip')`. First paint loads only the index (~37 KB). |
| L3 demo | Bundled samples | In-repo | Full demo still works offline. |

**Sharding**: one shard per chapter (99 chapters plus the Ch.99 reference table), median size ≈ 1.6 KB, loaded on demand. `manifest.json` records the revision, fetch time, and the size and sha256 of every shard; the UI renders this in an *evidentiary chain* panel so the numbers can be checked against their source.

> The decode layer is defensive: it inspects gzip magic bytes first and falls back to plain JSON if the host has already transparently decompressed the response, so a change of hosting cannot silently break every lookup.

### How to use it (three steps)

1. **Enter an HTS subheading** — 8 or 10 digits; if you are unsure of the code, click one of the category samples, or use **Browse by category** to drill from 97 chapters down to a single tariff line.
2. **Read the two layers top-down** — L1 snapshot (base rate + Chapter 99, ink-black edge) → L2 live (notices + AD/CVD, indigo edge). Each block collapses independently and starts collapsed; the header still carries that layer's headline numbers.
3. **Red lines first, numbers second** — the vermilion notes spell out what this page will not compute for you. The **reference estimate is expanded by default**, but it only covers base duty + MPF + HMF, and it states where every input comes from.

Above the results sits a collapsed *How to read this page* legend, with a section devoted to **where L1 ends and L2 begins**: by time (build-time snapshot vs fetched the moment you open the page), by content (a rate vs a move), by edge colour (ink black vs indigo).

> **Where the estimate's inputs come from**: value and mode of transport are yours to enter; the base rate comes from the L1 snapshot; MPF / HMF are CBP FY2026 published fee rates, pre-filled and editable. The estimate is **not** a third data layer — L3 is the offline demo layer. It excludes Chapter 99 surcharges, AD/CVD, FTA preferences and origin determinations, which are listed item by item in the L1 / L2 sections without amounts.

> **What the scenario estimate does and does not cover**: it **shares the same inputs** as the reference estimate (value / mode of transport / MPF / HMF); the only difference is whether effective §232 measures are added at the tier you declare. When measures match, the block starts collapsed and its header states how many matched. **Measures whose effective date is still in the future are registered but never counted** — they are listed below with their date in plain sight. If *every* measure matching a code is not yet in force, the block **produces no scenario total at all**: a total would equal the reference estimate above and read as "§232 = 0", which is the opposite of the truth. Tiers are always your declaration; the page only shows each tier's Chapter 99 source text and citation. **Every figure in this block is an estimate for reference only** and is no substitute for a CBP ruling or the current HTS text.

### End-to-end verification samples (`docs/pipeline-report.html`)

Eight samples, each tied to one design intent — they are **regression cases, not a product catalogue**:

| Code | Category | Base rate | Ch. 99 | AD/CVD | What it verifies |
|------|----------|-----------|--------|--------|------------------|
| `8507.60.00` | Electronics · Li-ion battery | 3.4% | 3 | 0 | Ad valorem rate alongside additional measures |
| `2804.61.00.00` | Chemicals · polysilicon | Free | 0 | 0 | **Red line 01**: snapshot says Free while the live layer shows measures |
| `7210.11.00` | Steel · tin-plate sheet | Free | 0 | 2 | Prefix fallback + AD/CVD existence notice |
| `0201.10.50` | Livestock · beef | 26.4% | 32 | 0 | Ancestor-chain name restoration + high-rate display |
| `1005.90.20` | Grain · corn | `0.05¢/kg` | 0 | 0 | **Red line 02**: specific rate, refuses to convert to a number |
| `6403.99.90` | Footwear · leather shoes | 10% | 8 | 0 | De-duplication and truncation under dense Ch. 99 hits |
| `6109.10.00` | Apparel · T-shirts | 16.5% | 0 | 0 | High ad valorem rate + fee estimate |
| `8481.80.90` | Machinery · valves | 2% | 5 | 0 | Ordering and overflow when measures stack |

> To look at other categories: both the UI and the verification page accept any HS code, and the verification page has a *random* button. Add one line to `SAMPLES` in `scripts/verify_tariff_data.py` and re-run the script to write that category into the report.

## 3. Repository layout

```
index.html                 Main UI (Gazette broadsheet styling; zh/en × light/dark)
verify.html                Data-layer verification page (same source of truth as the UI)
data/                      Data products (committed, ≈1.2 MB)
  manifest.json            Revision / fetch time / per-shard size and sha256
  hts-2026rev9-index.json.gz
  hts-2026rev9-chNN.json.gz      One shard per chapter (99 chapters)
  hts-2026rev9-ch99*.json.gz     Chapter 99 additional measures + reverse index
  hts-2026rev9-browse.json.gz    Category browser: 97 chapters -> 1,250 four-digit headings (38 KB, lazy-loaded)
  fr-tariff-20260928.json.gz     Federal Register tariff documents
  fr-adcvd-20260928.json.gz      AD/CVD documents
  section232-measures.json       §232 measure registry (hand-maintained, not a pipeline output): effective dates / rate tiers / scopes / Ch. 99 source text / citations
scripts/
  fetch_tariff_data.py     Pipeline: hts / fr / all
  build_browse_index.py    Builds the category-browser index (chapters -> 4-digit headings)
  verify_tariff_data.py    Four-sample end-to-end check -> docs/pipeline-report.html
tools/
  serve.py                 Local static server (serves .gz as octet-stream, mirroring production)
docs/
  spec.html                Specification v1.3
  pipeline-report.html     Pipeline verification report
assets/
  hero.svg                 README hero image (Gazette layout, same palette as the UI)
cache/                     Build-time cache (gitignored)
```

## 4. Running locally

```bash
python3 tools/serve.py 8771      # a server is required: fetch() is blocked under file://
open http://127.0.0.1:8771/                 # main UI
open http://127.0.0.1:8771/verify.html      # data-layer verification page
```

Refreshing the data (needs network; the USITC full table is large and is cached under `cache/`):

```bash
python3 scripts/fetch_tariff_data.py all    # HTS chapter shards + Federal Register snapshot
python3 scripts/verify_tariff_data.py       # re-run the four samples and refresh the report
```

## 5. Design: Gazette

The dark control-room styling of VeloCortex was deliberately **not** reused — that visual language implies live command-and-control, which contradicts a tool whose entire premise is "reference estimates only".

Gazette borrows from government gazettes and legal briefs: paper ground, serif body text, double-rule tables, hairline column dividers, vermilion marginal annotations — plus a **four-level confidence scale (T0–T3)** that makes "how trustworthy is this number" visible in the layout itself rather than hidden in a tooltip.

## 6. Data sources and licensing

- **HTS data**: USITC (U.S. government work, public domain)
- **Federal Register documents**: Federal Register API (public domain, no key required)
- **Commercial AIS / customs data**: **not integrated** — external links only

Code is released under the **MIT** license (see [`LICENSE`](LICENSE)); the underlying data is public domain.

---

## License

MIT License — Copyright (c) 2026 SummerPapaya. See [`LICENSE`](LICENSE) for the full text.

Output is for reference only and is not customs or legal advice. Classification and applicable rates are governed by CBP rulings and the current HTS text.
