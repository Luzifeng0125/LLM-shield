# 隐盾 LLM-Shield

隐盾是面向组织协作文档处理的本地隐私保护研究原型。项目当前转入**本科生创新训练项目（人工智能+专项）**研究阶段，重点研究人工智能如何理解任务语义、文档事实与接收方需求，并在授权约束下控制信息披露。

本仓库是研发协作与研究复现仓库，不等同于最终参赛/结题材料包。项目类型、研究目标、创新候选、假设、实验原则和申报文稿要求以[AI+大创研究基准](docs/research/AI_PLUS_RESEARCH_BASELINE.md)为准。

## 当前研究状态

- 现有 2.0 候选应用、模型、数据、历史评测和测试作为研究基础保留。
- 旧挑战杯材料保留为历史资料，不再决定当前研究目标。
- 下一阶段先进行系统查新、研究问题收敛和预实验，再决定新机制是否进入在线主流程。
- 当前候选研究方向：接收方感知的跨文档/跨轮次累积披露评估、事实依赖驱动的变更一致性、联合披露方案选择。它们尚未被证明为原创成果。

## 启动

首次安装按[安装与验证](docs/current/从GitHub安装与验证.md)配置 Python、完整 GLiNER 目录和 `app/.env`。

```powershell
.\\启动隐盾.cmd --check-only
.\\启动隐盾.cmd
```

默认地址 http://127.0.0.1:8787/。外部生成需要有效配置；本机表格计算可独立执行。

## 目录

| 目录 | 内容 |
|---|---|
| [app](app/README.md) | 应用、模型、配置、数据和测试 |
| [research](research/README.md) | 历史研究数据、人工复核和实验材料 |
| [docs/research](docs/research/AI_PLUS_RESEARCH_BASELINE.md) | 当前 AI+ 大创研究基准 |
| [docs/current](docs/current/README.md) | 当前架构、安装、部署和维护说明 |
| [docs/reports](docs/reports/) | 项目报告与仓库验收记录 |
| [docs/submissions](docs/submissions/使用说明.md) | 历史申报材料索引 |
| [docs/archive](docs/archive/README.md) | 旧方案、历史实验和挑战杯资料 |
| [tools](tools/README.md) | 维护、QA 和 Windows 工具 |

## 研究与协作规则

- 冻结数据、权重、人工裁定及历史报告不得覆盖。
- 新研究使用独立分支和实验目录，记录代码提交、数据版本、模型指纹和运行环境。
- 先冻结研究规格与验收标准，再实施；不能以工具自报完成代替独立验收。
- 通过 Issues 记录任务和完成条件，通过 Pull Requests 审查代码与证据。
- 详细路线见 [PROJECT_STATUS.md](PROJECT_STATUS.md)、[ROADMAP.md](ROADMAP.md)。
