# 隐盾 LLM-Shield

隐盾面向名单统计、通知起草、会议整理和协作交付。在本机识别敏感信息，依据任务、身份和接收方选择处理动作。支持的表格统计使用完整记录，生成服务接收通过检查的内容。

当前主分支提供 **2.0 候选版**。正式产品、默认配置和已合并功能均从 main 获取。

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

项目协作、知识源、工具和原生网关按需配置。请阅读[当前状态](docs/current/状态.md)、[系统架构](docs/current/架构.md)、[原生能力](docs/current/原生能力开发范围.md)及[模型网关](docs/current/原生模型网关.md)。

## 文件位置

| 目录 | 内容 |
| --- | --- |
| [app](app/README.md) | 应用、网页、默认配置、活动模型清单与测试 |
| [research](research/README.md) | 研究入口与版本化复核资料 |
| [docs/current](docs/current/README.md) | 当前架构、安装、部署及维护说明 |
| [docs/reports](docs/reports/仓库整理验收_20261121.md) | 项目报告与验证记录 |
| [docs/submissions](docs/submissions) | 已纳入版本管理的申报材料 |
| [docs/archive](docs/archive/README.md) | 历史方案、实验文档和旧说明 |
| [tools](tools/README.md) | Windows启动、打包、工程检查与维护工具 |
| local | 本机密钥、私有数据、环境、输出和备份，Git忽略 |

## 开发与发布

任务在 feat/*、fix/*、research/*、refactor/* 分支开发，通过PR合并main。整理前代码在 `archive/pre-reorganization-20261121`。备份与分支说明见[仓库维护](docs/current/仓库维护.md)。

```powershell
.\tools\windows\运行验证.cmd
.\tools\windows\运行Python.cmd app/scripts/make_release.py --profile runtime --version 2.0-candidate --out local/exports/shield-runtime.zip
```

运行包包含动作权重，GLiNER完整目录单独提供。发布变更见[CHANGELOG](CHANGELOG.md)，模型哈希见[活动模型](app/models/ACTIVE_MODELS.json)。
