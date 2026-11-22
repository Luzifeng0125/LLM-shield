# 隐盾 LLM-Shield

隐盾面向名单统计、通知起草、会议整理和协作交付。在本机识别敏感信息，依据任务、身份和接收方选择处理动作。支持的表格统计使用完整记录，生成服务接收通过检查的内容。

这里是团队的研发协作仓库，维护当前代码、必要工具、研究证据和决策。2.0 是当前候选研发版本。进度、分工方式和近期任务见[项目状态](PROJECT_STATUS.md)、[路线图](ROADMAP.md)和[协作说明](docs/current/仓库维护.md)。

## 启动

首次安装按[安装与验证](docs/current/从GitHub安装与验证.md)配置 Python、完整 GLiNER 目录和 `app/.env`。

```powershell
.\启动隐盾.cmd --check-only
.\启动隐盾.cmd
```

默认地址 http://127.0.0.1:8787/ 。启动器启用 GLiNER，自动选择 CUDA 或 CPU。外部生成需要有效配置，本机表格计算可独立执行。

## 功能与文档

| 能力 | 范围 |
| --- | --- |
| 文件对话与全表统计 | 受控历史、统计追问、条件筛选、分组、关联、去重、CSV/XLSX导出 |
| 接收方版本 | 授权恢复、批准版本绑定的Word导出、可选本机OCR |
| 项目协作 | 编号化分配与核验、供应商凭证与核销、本地封存验收 |
| 原生安全能力 | 注册识别规则、六动作模型、硬约束和六边界检查 |
| 原生网关 | 获准路由、同范围回退、预算预留、限流和费用查询 |
| 知识与外发 | 绑定用途的本地词项检索、预览确认的固定Webhook |

项目协作、知识源、工具和原生网关按需配置。请阅读[技术状态与历史验证范围](docs/current/状态.md)、[系统架构](docs/current/架构.md)、[原生能力](docs/current/原生能力开发范围.md)及[模型网关](docs/current/原生模型网关.md)。

## 文件位置

| 目录 | 内容 |
| --- | --- |
| [app](app/README.md) | 应用、网页、默认配置、活动模型清单与测试 |
| [research](research/README.md) | 研究入口与版本化复核资料 |
| [docs/current](docs/current/README.md) | 当前架构、安装、部署及维护说明 |
| [docs/reports](docs/reports/仓库整理验收_20261121.md) | 项目报告与验证记录 |
| [docs/submissions](docs/submissions/使用说明.md) | 申报与答辩材料索引，含个人属性的 Office 原件由负责人保管 |
| [docs/archive](docs/archive/README.md) | 历史方案、实验文档和旧说明 |
| [tools](tools/README.md) | Windows启动、打包、工程检查与维护工具 |
| local | 本机密钥、私有数据、环境、输出和备份，Git忽略 |

## 团队协作

在 [Issues](https://github.com/Luzifeng0125/LLM-shield/issues) 记录任务、负责人、范围与完成条件。在 [Pull requests](https://github.com/Luzifeng0125/LLM-shield/pulls) 提交变更、关联 Issue 并附检查结果。研发、修复和研究各使用独立任务分支。

研究批次、历史决策和模型身份可从 [研究入口](research/README.md)、[历史资料](docs/archive/README.md)、[模型记录](app/models/README.md) 和 [变更记录](CHANGELOG.md) 查找。取得授权后，在本机按指纹配置活动动作模型及项目 GLiNER。Git 保留清单、测试和复现说明。
