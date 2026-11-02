# 模型文件与版本

发布整理日期：2026-11-02。这里的动作分类器使用 TF-IDF 与逻辑回归；GLiNER 是另一条实体识别链路。

补充：官方 `gliner_multi-v2.1` 的完整1.16 GB权重已下载至本机 `gliner_official_multi_v2.1` 并完成严格加载和GPU评测；五份动作权重已从GitHub重新下载校验。见[分阶段实测报告](../../../04_技术文档/模型补齐与分阶段实测_20261102.md)。官方对照不替代缺失的项目微调权重，也未据合成结果晋级必要性候选。

## 本次分发的权重

- `necessity_action.joblib`：现有默认模型，特征版本 3。
- `necessity_action_campus_context_20261102.joblib`：最新训练的校园上下文增强候选，特征版本 5；尚未晋级。
- `necessity_action_campus_task_20261102.joblib`：校园任务需求候选，特征版本 4；尚未晋级。
- `necessity_action_campus_aligned_20261101.joblib`：上一轮对齐候选，特征版本 3；尚未晋级。
- `necessity_action_campus_candidate.joblib`：已冻结的早期校园候选，特征版本 3；仅供历史比较。

每份候选保留原始 JSON 说明。文件大小、SHA-256、特征版本及评测证据见 [MODEL_RELEASE.json](MODEL_RELEASE.json)，默认运行配置仍见 [ACTIVE_MODELS.json](ACTIVE_MODELS.json)。上传候选不代表替换默认模型。

## 最新人工评测

31 条冻结合并裁定上，硬约束后的动作匹配数分别为：默认模型 17/31、任务需求候选 22/31、最新上下文候选 19/31。上下文候选有两条不必要披露；任务需求候选也有任务所需信息误删。均未晋级。

这批材料来自三人复核加一人审核的合并返还，没有完整的个人原始独立标注记录，不能外推为所有校园任务的准确率。完整说明见 [人工评测报告](../../../04_技术文档/校园必要性模型独立人工评测报告_20261102.md)。本次归档了 [逐条结果、混淆矩阵、错误与环境记录](../eval/releases/campus_blind31_20261102/)，不重新执行一次性评测或训练。

## 下载与检查

从仓库克隆或下载 ZIP 即包含上述小型权重，无需 Git LFS。安装依赖时使用 `delivery/app/requirements-lock.txt`，其中固定了训练环境使用的 scikit-learn 与 joblib 版本。

在仓库根目录执行：

```powershell
# 仅检查文件大小和 SHA-256，无需加载权重
python -X utf8 delivery/app/scripts/verify_model_release.py
# 安装应用依赖后，额外检查五份权重的加载、特征版本与合成输入推理
python -X utf8 delivery/app/scripts/verify_model_release.py --load
```

本地离线比较可通过 `NecessityModel(model_path=...)` 显式加载候选。版本 4/5 依赖本次同步的 `llm_shield/m4_necessity/model.py` 中的特征函数，不能只下载 joblib 后配旧代码使用。

## GLiNER 与其他本地产物

`gliner_v3/pytorch_model.bin` 已按活动清单的 SHA-256 `3e7d4c3d704920e78fc0a8d65a768aaab4e095d0ae8c0da2fb96615d4883a360` 放入本机目录。仓库分发包本身仍只有配置和分词器，这份 1.1 GB 权重不随仓库分发。

`gliner_official_multi_v2.1`、`reviewed_ner`、运行环境、历史实验目录和上传材料继续留在本地。可用 `scripts/download_verified_models.py` 下载固定版本官方识别权重与校验过的必要性权重，随后自动准备离线配置。`启动官方模型测试.cmd` 显式选择官方对照与mock生成；原默认启动路径仍要求原微调权重。
