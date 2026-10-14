# 维护工具

这些工具用于维护交付材料，应用运行只需要交付目录下的 `app` 与 Python 环境。

- `submission/build_report.py`：最新版 Word 报告的生成源文件，需要 python-docx。
- `submission/build_deck.mjs`：最新版 PPT 的生成源文件，依赖 Codex 自带的 artifact-tool 与演示文稿工具。默认路径对应制作电脑，可通过环境变量调整；普通使用者直接编辑交付的 PPT 即可。
- `submission/render_report.ps1`：通过本机 Microsoft Word 导出报告 PDF。
- `submission/report_text.md`、`slides_notes.json`：报告正文与幻灯片讲解备注。
- `submission/deck_validation.json`、`visual_qa.json`：2026-10-14 材料构建时的检查记录，含当时的路径，不代表每次克隆后重新验收。
- `qa/browser_qa.cjs`、`qa/review_qa.cjs`：使用本机 Edge 与 Playwright 检查对话和复核页面；仅使用合成输入和 mock 模式。
- `package_delivery.py`：使用当前交付目录生成便携 ZIP，过滤密钥、上传材料、日志和人工填写记录。需要本机已有便携 runtime；Git 仓库不包含该运行环境。

打包示例（在仓库根目录执行）：

```powershell
.\隐盾整合交付_20261012\运行Python.cmd -X utf8 tools/package_delivery.py
```

生成的 ZIP、报告渲染中间文件和自动化界面测试填写结果不入库。真实人工复核记录应由团队另行保存。
