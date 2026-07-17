# PKA 随机多格式真实录入 E2E 复验

- 执行时间：2026-07-17 20:38:11–20:48:50（Asia/Shanghai）
- 隔离运行目录：`/var/folders/by/ryk2x0p133n0q7syh20tp2l40000gn/T/pka-public-automotive-ingest-bkgs38w4`
- 样本数量：19
- 格式覆盖：DOCX、PPTX、XLSX、PNG、JPG、WebP、TXT、Markdown 各 2 份，PDF 3 份
- 来源覆盖：Texas DIR、NASA、EPA、USGS、Mozilla、Tesseract.js、Paddle/Tesseract 测试资料及多个开源项目
- 总结果：通过

## 验收口径

被质量策略接受的文件必须同时满足：

1. 通过真实 `/api/ingest/file` 录入并产生非零分块；
2. 通过真实 `/api/query` 返回属于该 `source_id` 的来源；
3. 完全相同文件再次上传时返回 `duplicate` 或 `duplicate_pending`；
4. 删除资料源成功；
5. 删除后可重新上传成功。

低文字量图片允许进入 `review_required`，但必须保持零分块，不能把不可靠 OCR 结果写入资料库。

## 样本与结果

| 格式 | 样本 | 公共来源 | 质量结果 | 分块 | 检索 | 重复阻断 | 删除/重传 |
|---|---|---|---|---:|---|---|---|
| DOCX | Texas Monitoring Report Template | [Texas DIR](https://dir.texas.gov/sites/default/files/2026-04/Monitoring%20Report%20Template_2026%20%281%29.docx) | high / passed | 11 | 命中 | 通过 | 通过 |
| DOCX | comments-rich-para fixture | [python-docx](https://raw.githubusercontent.com/python-openxml/python-docx/master/features/steps/test_files/comments-rich-para.docx) | high / passed | 1 | 命中 | 通过 | 通过 |
| PPTX | Comparison of Planet Sizes | [NASA](https://assets.science.nasa.gov/content/dam/science/astro/exo-explore/2023/09/B-02-NOV-2021.pptx) | high / passed | 1 | 命中 | 通过 | 通过 |
| PPTX | Comparison of Metal Phases | [NASA](https://assets.science.nasa.gov/content/dam/science/astro/exo-explore/2023/09/D-02-NOV-2021.pptx) | high / passed | 1 | 命中 | 通过 | 通过 |
| XLSX | IRIS Database Export | [EPA](https://www.epa.gov/system/files/documents/2025-04/iris_downloads_database_export_april2025.xlsx) | high / passed | 1,163 | 命中 | 通过 | 通过 |
| XLSX | EnviroAtlas National Data Downloads | [EPA](https://www.epa.gov/system/files/documents/2025-04/enviroatlas_data_downloads_national.xlsx) | high / passed | 755 | 命中 | 通过 | 通过 |
| PDF | Climate Adaptation Decision Framework | [USGS](https://pubs.usgs.gov/of/2025/1005/ofr20251005.pdf) | high / passed | 249 | 命中 | 通过 | 通过 |
| PDF | TraceMonkey paper | [Mozilla PDF.js](https://raw.githubusercontent.com/mozilla/pdf.js/master/web/compressed.tracemonkey-pldi-09.pdf) | high / passed | 99 | 命中 | 通过 | 通过 |
| PDF（扫描） | French OCR fixture | [OCRmyPDF](https://raw.githubusercontent.com/ocrmypdf/OCRmyPDF/main/tests/resources/francais.pdf) | high / passed | 1 | 命中 | 通过 | 通过 |
| PNG | OCR paragraph fixture | [Tesseract.js](https://raw.githubusercontent.com/naptha/tesseract.js/master/tests/assets/images/testocr.png) | high / passed | 1 | 命中 | 通过 | 通过 |
| PNG | PowerPoint chart | [python-pptx](https://raw.githubusercontent.com/scanny/python-pptx/master/docs/_static/img/chart-01.png) | low / conditional pass | 0 | 不索引 | 不适用 | 不适用 |
| JPG | Multilingual OCR fixture | [pytesseract](https://raw.githubusercontent.com/madmaze/pytesseract/master/tests/data/test-european.jpg) | high / passed | 1 | 命中 | 通过 | 通过 |
| JPG | Meditations page | [Tesseract.js](https://raw.githubusercontent.com/naptha/tesseract.js/master/benchmarks/data/meditations.jpg) | high / passed | 2 | 命中 | 通过 | 通过 |
| WebP | Browserslist screenshot | [Browserslist](https://raw.githubusercontent.com/browserslist/browserslist/main/img/screenshot.webp) | high / passed | 2 | 命中 | 通过 | 通过 |
| WebP | Image Generator screenshot | [Gramener imagegen](https://raw.githubusercontent.com/gramener/imagegen/main/screenshot.webp) | high / passed | 1 | 命中 | 通过 | 通过 |
| TXT | WebP Container Specification | [libwebp](https://raw.githubusercontent.com/webmproject/libwebp/main/doc/webp-container-spec.txt) | high / passed | 37 | 命中 | 通过 | 通过 |
| TXT | python-pptx lab README | [python-pptx](https://raw.githubusercontent.com/scanny/python-pptx/master/lab/README.txt) | high / passed | 1 | 命中 | 通过 | 通过 |
| Markdown | TensorFlow README | [TensorFlow](https://raw.githubusercontent.com/tensorflow/tensorflow/master/README.md) | high / passed | 15 | 命中 | 通过 | 通过 |
| Markdown | Kubernetes README | [Kubernetes](https://raw.githubusercontent.com/kubernetes/kubernetes/master/README.md) | high / passed | 10 | 命中 | 通过 | 通过 |

## 结论

- 19 份新样本没有依赖此前的唯一测试源。
- 18 份可用内容完整通过录入、解析、索引、查询、重复阻断和删除/重传。
- 1 份文字量不足的图表 PNG 被正确拦截为 `review_required`，且分块数为 0；这是质量策略的预期行为，不是解析失败。
- 新增的图像型 PDF 经本机 PaddleOCR 提取 326 字符，质量为 high，并完成完整生命周期验证。
- 大型结构化工作簿也完成了真实端到端验证，未通过缩小数据或模拟分块规避压力。
- 本轮未发现需要修改生产录入逻辑的格式缺陷。
- 本轮发现并修复了验证器对平台 MIME 数据库的隐式依赖：当 macOS 未识别 `.md` MIME 时，现在会按 PKA 支持的扩展名安全回退。
- 本轮还修复了验证器对异步 OCR 重传成功状态的误判：`accepted` 只有在同时具备 `source_id` 和非零分块时才计为成功。

SHA-256、`source_id` 命中数、质量覆盖状态和完整生命周期证据见同目录的
`general_ingest_20260717_124850.json` 与 `general_ingest_20260717_124850.md`。
扫描 PDF 的初始误判证据与修复后证据分别见
`general_ingest_20260717_125514.json` 和 `general_ingest_20260717_125702.json`。
