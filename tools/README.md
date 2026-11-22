# 辅助工具

- qa/optimization_qa.cjs：最近一次工程浏览器验证工具；mock + rules-only，不能替代真实 GLiNER 验收。
- qa/stage_evaluation_qa.cjs：官方GLiNER真实GPU识别＋mock生成的阶段页面和聊天流程，覆盖1440/768/390px屏宽；不调用真实云端API。
- qa/browser_qa.cjs：历史 BERT 候选阶段脚本，当前不作为默认启动或验收入口。
- maintenance：研究语料、复核包和历史计划维护工具。一次性旧目录迁移脚本可在基线 ed9a1f0c 中追溯。

应用脚本位于[app/scripts](../app/scripts)。浏览器 QA 可从 Node 模块搜索路径加载 playwright-core，或用 PLAYWRIGHT_MODULE 指定本机入口。任务优先级见[研发路线图](../ROADMAP.md)。
