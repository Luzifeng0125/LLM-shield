# 隐盾 LLM-Shield

当前维护版本：2026-10-17 本地实体识别、分段动作模型及“名单核对与通知”工作流。GitHub 检出经过软件回归；完整 BERT 模式仍需要单独提供模型权重。

安装 Python 环境并放置本机模型后，双击根目录 [启动隐盾.cmd](启动隐盾.cmd)，打开 http://127.0.0.1:8789/；名单页面为 http://127.0.0.1:8789/notice。这个已验证入口强制使用本地模拟回复，自动选择 CUDA / CPU。名单在本机核对，通知生成只接收独立填写的公开活动信息。需要通用文件对话和真实 DeepSeek 回复时，按[安装与验证说明](docs/从GitHub安装与验证.md)配置本机密钥后运行 [启动通用对话.cmd](启动通用对话.cmd)；它使用规则识别基线，需单独验收质量。

## 交接与目录

后续 AI 先读 [AI_EXECUTION_PLAN.md](AI_EXECUTION_PLAN.md)，按 [执行状态](docs/执行状态.json) 接着工作。计划覆盖补充数据、模型改进、回归、真实生成验证、交付材料和干净环境验收。

- `delivery/app`：Git 仓库中的应用源码、测试与动作模型；大权重和私有证据不入库。
- `delivery/runtime`：原开发机使用的本机 Python 环境和训练底座，Git 不分发；安装器可在 `delivery/app/.venv` 建立新环境。
- `delivery/数据集`：合成来源、完整人工复核工具、已导入的 gold 和训练记录。
- `delivery/提交材料`：保留的最近报告、PPT 和申报书，最终提交前需按新证据更新。
- `docs`：当前架构、必要实验记录及清理记录。
- `tools`：仍使用的界面验证工具。
- 原开发机的 `个人资料` 不在 Git 克隆中；该目录不属于应用，也不应被仓库同步覆盖。

旧日期交付目录、重复压缩包、旧启动入口、未采用的候选大权重和缓存已清理。运行文件已迁到上述实体目录，不依赖旧目录链接。未通过的实验保留结论和来源记录。

## 当前模型

权威清单：[ACTIVE_MODELS.json](delivery/app/models/ACTIVE_MODELS.json)。

- NER：人工复核训练数据得到的 `ner_bert_v1`，目录 `app/models/reviewed_ner`，启动时使用 `bio_viterbi`。
- 动作：`segment_coverage_v2`，已设为 `app/models/necessity_action.joblib`。这是 TF-IDF + 逻辑回归分类器，不是生成式大语言模型。
- 可选 Campus NER、GLiNER 在统一入口关闭。模型缺失或不兼容必须暂停，不能静默替换。

原验证集 BERT 严格 F1 99.45%，应用组合链 98.91%；开发集 field_v1 组合严格 F1 78.85%，cover F1 89.03%。单条名单的 20 项直接标识符通过本地接口及浏览器检查。公共地点与宿舍的混淆尚未解决；这些开发结果不代表盲测或生产安全保证。

详细证据：[名单联调](docs/名单样例联调_20261017.md)、[地点候选取舍](docs/地点与宿舍候选验证_20261017.md)、[当前架构](docs/项目现状与架构总览.md)。

本次 GitHub 与原本地版本的差异、模型取舍见[版本对照](docs/版本对照与取舍_20261017.md)。

## 使用与检查

在本目录 PowerShell 执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1
& '.\delivery\运行验证.cmd'
# 可选：在 delivery/app/.env 填写 LLM_API_KEY 后启用通用对话
& '.\启动通用对话.cmd'
# 放置并校验 reviewed_ner 权重后：
& '.\启动隐盾.cmd' --check-only
& '.\启动隐盾.cmd'
# 停止本项目在默认端口启动的服务：
& '.\delivery\停止隐盾.cmd'
```

测试入口运行独立 smoke 与 pytest，不自动评分封存测试集。API 配置自检入口会发起真实请求，应仅在真实联调阶段使用。

既有开发机完成过本机验证；全新克隆不是可直接启动的便携安装包。Python 环境需要安装，NER 大权重、runtime、人工填写结果、原始名单和本机配置均不在 Git 中。取得并校验权重前，维护模式的预检应明确失败。打包和干净环境重建在执行计划中单列验收。

共享前必须过滤 `.env`、原始名单、上传材料和本地输出；不要直接发送整个工作目录。
