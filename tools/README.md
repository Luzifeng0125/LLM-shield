# 辅助工具

- qa/optimization_qa.cjs：最近一次工程浏览器验证工具；mock + rules-only，不能替代真实 GLiNER 验收。
- qa/stage_evaluation_qa.cjs：官方GLiNER真实GPU识别＋mock生成的阶段页面和聊天流程，覆盖1440/768/390px屏宽；不调用真实云端API。
- qa/browser_qa.cjs：历史 BERT 候选阶段脚本，当前不作为默认启动或验收入口。
- maintenance：本次目录迁移与路径维护记录。

应用自己的脚本位于 ../delivery/app/scripts。完整执行任务请看 ../01_优化方案。
