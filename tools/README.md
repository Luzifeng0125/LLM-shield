# 保留的维护工具

`qa/browser_qa.cjs` 验证通用对话的附件、连续追问、清除会话和桌面/手机布局。它使用 delivery/runtime/training_env 和当前模型，在 8798 端口启动临时 mock 服务，输出至 delivery/app/outputs/browser_qa。运行前确保该端口未被占用；当前 Playwright 与 Edge 路径是本机路径。

独立名单工作流的 HTTP 和浏览器验证在 delivery/app/scripts/verify_notice_workflow.py 与 verify_notice_browser.cjs。

旧日期目录绑定的打包工具、报告生成中间工程和失败候选的一次性脚本已移除。新交付打包必须同时包含当前 NER、动作模型和可重建环境，并过滤本机密钥、名单及人工填写原件；具体要求见根目录 AI_EXECUTION_PLAN.md。
