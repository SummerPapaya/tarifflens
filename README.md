# TariffLens · 关税测算参考台

> 输入一个 HTS 子目，看到它当下被哪些措施覆盖、依据出自哪里、以及**哪些部分本工具不替你算**。
>
> A read-only reference desk for U.S. HTS duty lookups: what measures apply, where each number comes from — and, just as importantly, what this tool deliberately refuses to compute.

TariffLens 是 [supply-chain-portfolio](https://github.com/SummerPapaya/supply-chain-portfolio)「衍生应用」序列的第 2 个项目（#2 关税与贸易合规自动化）。它是一个**纯静态站点**：无后端、无构建步骤、无 LLM 密钥，数据全部在构建期预取、随仓库分发。

- 在线预览：推送后由 GitHub Pages 托管（仓库根 `index.html`）
- 规格书：[`docs/spec.html`](docs/spec.html)（v1.3，12 项设计确认全部落地）
- 数据管线验证报告：[`docs/pipeline-report.html`](docs/pipeline-report.html)

---

## 一、三条红线（这不是免责声明，是产品逻辑）

工具的价值边界先于功能定义。以下三条在 UI 上是**可见状态**，不是折叠的脚注：

| # | 红线 | UI 行为 |
|---|------|---------|
| 01 | **不做自动 HS 归类** | 只出「参考测算」。检索命中即展示，但从不替用户判定商品应归哪个子目。 |
| 02 | **文本引用形态拒绝输出数字** | 税率字段若形如 `"The duty provided in..."`（形态码 `rk=t`），一律不出数字、不估算，只显示原文出处。 |
| 03 | **未覆盖项三类分治** | 规费（MPF/HMF）可算 → 正常输出；ADD/CVD 只出**存在性提示**不出金额；FTA / 原产地 / 归类 → 只读提示 + 免责。 |

## 二、三层数据架构

| 层 | 来源 | 形态 | 说明 |
|----|------|------|------|
| L1 实时 | [Federal Register API](https://www.federalregister.gov/api/v1/documents.json) | 浏览器直连 | CORS `*`、免密钥。拉取近 90 天关税类与 ADD/CVD 类文档，含 `effective_on` / `comments_close_on`。 |
| L2 快照 | USITC HTS 2026 rev.9 整表 | 构建期预取 | 35,502 行 → 按章切 gzip 分片，浏览器 `DecompressionStream('gzip')` 解压。首屏仅载 index（约 37 KB）。 |
| L3 演示 | 内置样例 | 仓库内置 | 网络不可用时仍可完整演示。 |

分片策略：按章（99 章 + Ch99 引用表）切分，中位体积约 1.6 KB，按需加载；`manifest.json` 记录版本、抓取时间、各分片体积与 sha256。

### 端到端验证样例（`docs/pipeline-report.html`）

| 样例 | 结果 |
|------|------|
| 多晶硅 | `Free` + 红线 01 触发 + Proclamation 11052 命中 |
| 锂电池 | 3.4% + Chapter 99 命中 3 条 |
| 镀锡钢板 | 前缀回退命中 + ADD/CVD 2 条 |
| 牛肉 | 26.4% + Chapter 99 命中 32 条（祖先链还原品名） |

## 三、目录结构

```
index.html                 正式 UI（Gazette 公报版式，中英双语 × 亮/暗四态）
verify.html                数据层验证页（与 UI 同源，逐项对照四样例）
data/                      数据产物（随仓库提交，约 1.2 MB）
  manifest.json            版本 / 抓取时间 / 分片体积与 sha256
  hts-2026rev9-index.json.gz
  hts-2026rev9-chNN.json.gz      按章分片
  hts-2026rev9-ch99*.json.gz     Chapter 99 附加措施 + 反查索引
  fr-tariff-20260928.json.gz     关税类联邦公报文档
  fr-adcvd-20260928.json.gz      反倾销/反补贴文档
scripts/
  fetch_tariff_data.py     数据管线：hts / fr / all
  verify_tariff_data.py    四样例端到端验证 → docs/pipeline-report.html
tools/
  serve.py                 本地静态服务器（.gz 按 octet-stream 发送，复现线上取数路径）
docs/
  spec.html                规格书
  pipeline-report.html     验证报告
cache/                     构建期缓存（gitignore）
```

## 四、本地运行

```bash
python3 tools/serve.py 8771      # 必须走服务器，file:// 下 fetch 会被 CORS 拦
open http://127.0.0.1:8771/      # UI
open http://127.0.0.1:8771/verify.html   # 数据层验证页
```

刷新数据（需要联网，USITC 整表较大）：

```bash
python3 scripts/fetch_tariff_data.py all           # hts + fr
python3 scripts/verify_tariff_data.py              # 重跑验证并刷新报告
```

> `scripts/fetch_tariff_data.py` 的默认产出目录已改为仓库根的 `data/`（原为作品集仓库下的临时路径）。

## 五、设计：Gazette

不沿用 VeloCortex 的暗色指挥台风格 —— 那套视觉语言暗示「实时掌控」，与本项目「只做参考测算」的红线冲突。Gazette 借用政府公报／法律简报的排版语汇：纸色底、衬线正文、双细线表格、竖细线分栏、朱红勘校旁注，配合**四级置信度标度（T0–T3）**让「这个数有多可信」在版面上直接可见。

## 六、数据来源与许可

- HTS 数据：USITC（美国政府机构作品，public domain）
- 联邦公报文档：Federal Register API（public domain，免密钥）
- 商业 AIS／关务数据：**未接入**，仅外部链接跳转

站点本身不含任何密钥，也不需要任何密钥即可运行。

---

*本工具输出仅供参考，不构成报关或法律意见。归类与税率适用以 CBP 裁定及最新 HTS 文本为准。*
