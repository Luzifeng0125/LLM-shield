# 人工 gold 导入、训练与独立验证

> 当前状态（2026-10-17）：既有人工 gold 已验收并训练，统一入口为 delivery/启动隐盾.cmd（8789，mock）。当前 NER 已迁到 delivery/app/models/reviewed_ner；失败候选仅保留证据。以下早期指标与流程供追溯，不是最新验收结论。后续工作以根目录 AI_EXECUTION_PLAN.md 为准。

本流程接收已导出的 `train_gold.jsonl`、`validation_gold.jsonl`、`test_gold.jsonl`。现已完成数据验收、基线、中文 BERT 实体模型训练、上下文动作模型 v2，以及实体模型的本地应用接入。原始 gold 和模型产物放在被 Git 忽略的 `outputs/` 内。

## 2026-10-16 最新结果：训练与候选接入已完成

本轮汇总见 [improvement_summary.json](outputs/gold_run_20261016/improvement_summary.json)；其中保留旧基线、两个新模型指标、文件完整性检查和软件验收证据。

- **实体模型已经实际训练**：`google-bert/bert-base-chinese`，14 类实体 / 29 类 BIO，使用 152 行训练数据；在 116 行验证视图中的 56 个独立 NER 单位上选最佳轮次。第 4 轮最佳，第 7 轮早停；权重保存与重载的预测一致。没有使用测试集训练、选参或评分。
- **BERT 单模型**：严格实体 precision 100%、recall 98.91%、F1 **99.45%**（91 TP / 0 FP / 1 FN）；55/56 个单位完全正确，12 个无实体单位均无误报。独立评分脚本与真实 CPU 适配器复算一致。模型及训练记录见 [当前 NER 目录](../../app/models/reviewed_ner/)，独立复算见 [summary.json](outputs/gold_run_20261016/ner_bert_v1_independent_score/summary.json)。
- **应用组合检测链**：旧规则 + 新 BERT 的严格实体 F1 **96.74%**（89 TP / 3 FP / 3 FN），原规则基线为 **55.78%**。53/56 个单位完全正确，12 个无实体单位均无误报。其剩余 3 例是旧规则把机构、地点的边界扩宽；不应把单模型 99.45% 当作应用组合链指标。[最新组合验证报告](outputs/gold_run_20261016/ner_app_viterbi_boundaries_20261017/summary.json) 同时记录 CPU 延迟、4,799 字含 emoji 长文本滑窗检查和当前代码指纹。
- **上下文动作 v2 已训练**：独立保留当前文本、历史用户文本、任务说明和可信配置四类特征。60 个验证动作全部命中，12/12 个应暂停请求均预测暂停，48 个其他请求无误暂停，12/12 段对话全部动作正确。训练内部按来源分组的三折留出为 59/60，未用验证集调参数。详见 [动作指标](outputs/gold_run_20261016/policy_context_v2/metrics.json)。该模型仍是整请求/轮次动作实验产物，**尚未替换应用的分段动作模型**。
- **应用适配器已接入**：显式配置路径后才加载候选模型，检查来源、标签、模型文件存在性和哈希；模型不可用时暂停处理。保留原文 Unicode 偏移、长文本滑窗和模型缓存。真实冒烟发现的“12 位数字片段误标身份证”已修复；应用层拒绝截断的身份证片段，完整合成号码仍按语义处理，不额外用校验位否决人审标注。训练权重与共享 BIO 推理未变，应用层修订指纹另存于最终应用报告。
- **检查结果**：应用及训练全套回归 160 项、81 个子检查通过；格式防护修改后，受影响的适配器/识别/外发回归 71 项、16 个子检查通过；实际候选模型的整流程冒烟 38/38 通过。XML 与 [冒烟日志](outputs/gold_run_20261016/candidate_smoke.log) 已归档。旧应用动作权重 SHA-256 仍为 `691a1f820648c0b1f85e35b2dca061aae0f309516672f8b5c4eb21020abc4e46`。
- **接口联调**：实际 ASGI 首页及处理接口返回 200；会议材料去除姓名和电话后获得本地模拟回复，未知接收方返回 400，原始敏感载荷被拦截，代号载荷允许。外部模型调用次数为 0。[接口验收记录](outputs/gold_run_20261016/candidate_service_verification.json) 也保留一个发现：现有分段动作模型对“负责人任务；单独联系电话”的写法选择了不适用的代号动作，系统安全暂停、三个边界全部拒绝；这是待改进的可用性问题，不能宣称应用所有请求已正确处理。

这些结果来自人工复核的合成开发数据，不是封存测试成绩，也不能表示真实业务隐私保护率。动作 v2 的 100% 仅指动作分类，没有测量其生成外发文本的能力。BERT 是实体标注模型，本轮未做生成式大语言模型 SFT。

## 直接使用本地候选版

交付目录新增 [启动隐盾.cmd](../../启动隐盾.cmd)。双击后，等待预检成功，打开 `http://127.0.0.1:8789/`。该入口实际加载新实体模型，同时明确使用**本地模拟回复**，不调用外部大模型。清理后统一入口加载已验证的 segment_coverage_v2；`.env` 未改写。窗口关闭或按 Ctrl+C 即停止。

该入口自动选择 CUDA / CPU，预加载实体模型和现有动作模型。无需重新训练。也可从交付目录只做预检：

```powershell
& './启动隐盾.cmd' --check-only
```

真实训练环境为独立 `runtime/training_env`：Python 3.12、PyTorch 2.11.0+cu128、Transformers 4.57.6，已验证 RTX 5060 Laptop CUDA 运算。版本清单见 [training_environment_lock.txt](outputs/gold_run_20261016/training_environment_lock.txt)。基础权重经 ModelScope 下载，其 SHA-256 与 [官方权重页面](https://huggingface.co/google-bert/bert-base-chinese/blob/main/model.safetensors) 一致：`3404a1ffd8da507042e8161013ba2a4fc49858b4e3f8fbf5ce5724f94883aec3`。下载传输分支及实际文件指纹单独记录，不把镜像 master 宣称为已锁定的官方 revision。

## 重现实验

在本执行包目录运行；新实验必须使用不存在的新输出目录，以下示例中的 `rerun` 不会覆盖已交付结果：

```powershell
$trainingPython = '../../runtime/training_env/Scripts/python.exe'
$run = 'outputs/gold_run_20261016'
& $trainingPython -X utf8 scripts/train_transformer_ner.py `
  --base-model '../../runtime/base_models/bert_base_chinese' `
  --train "$run/ner/train.jsonl" --validation "$run/ner/validation.jsonl" `
  --out "$run/ner_bert_rerun" --device cuda

& $trainingPython -X utf8 scripts/train_context_policy.py `
  --train "$run/gold/train_gold.jsonl" --validation "$run/gold/validation_gold.jsonl" `
  --baseline "$run/policy_baseline" --out "$run/policy_context_rerun"

& $trainingPython -X utf8 scripts/verify_reviewed_ner_app.py `
  --data "$run/gold/validation_gold.jsonl" --model ../../app/models/reviewed_ner `
  --app '../../app' --out "$run/ner_app_rerun" --device cpu --decoding bio_viterbi

& $trainingPython -X utf8 scripts/verify_candidate_service.py `
  --model ../../app/models/reviewed_ner --out "$run/candidate_service_rerun.json" --device cuda
```

无 GPU 时将 `--device cuda` 改为 `--device cpu`。所有评估入口均限制在验证集；默认 `evaluate_gold_ner.py` 固定为原规则链，不受候选模型环境变量污染。

## 首轮基线记录（保留作对照）

已完成原始包备份、312 个单位的结构与批次验收、NER/BIO/SFT 训练视图生成，以及两个独立验证实验。产物目录为 `outputs/gold_run_20261016/`，完整记录见 [run_summary.json](outputs/gold_run_20261016/run_summary.json)。本地 A 的三批原件均与 gold 内指纹一致；用于导出的 B 原件未随包提供，需继续保留原件归档。

- 当前实体检测器：56 个 NER 验证单位，严格实体 precision 0.7455、recall 0.4457、F1 0.5578；全文实体集合完全正确 24/56；12 个无实体单位未出现误报。姓名、成绩等漏检和宿舍边界不一致需要优先处理。详见 [实体指标](outputs/gold_run_20261016/ner_baseline/summary.json) 和 [实体错例](outputs/gold_run_20261016/ner_baseline/errors.jsonl)。
- 新训练的动作实验基线：60 个训练动作样本，60 个独立验证动作样本；首选/可接受动作命中均为 55/60（91.67%），macro-F1 0.9415；12 段会话中只有 7 段所有动作均正确。这些数字仅衡量动作选择。
- **不具备上线条件**：12 个应暂停的验证请求中，5 个被预测为使用代号。具体包括指代不清 2 个、累计身份线索 2 个、恢复原名 1 个。详见 [动作指标](outputs/gold_run_20261016/policy_baseline/metrics.json) 和 [动作错例](outputs/gold_run_20261016/policy_baseline/validation_errors.jsonl)。该实验权重也不兼容应用当前的分段动作接口。
- 模型保存与重载后的 60 条预测及概率完全一致，产物哈希已核验。当前应用权重未变。数据/训练相关回归检查和三个入口的实际执行均通过。

首轮基线未进行神经网络训练；后续的 14 类实体模型和上下文动作 v2 训练已完成，结果见本文上方。封存测试仍未评分。

## 运行方式

在本执行包目录打开 PowerShell。每次运行使用新的输出目录；脚本拒绝覆盖已有结果。

```powershell
$reviewPython = '..\..\runtime\training_env\Scripts\python.exe'
$run = 'outputs/gold_run_20261016'

& $reviewPython -X utf8 scripts/prepare_reviewed_gold.py `
  --archive 'D:\WeChat_photo\xwechat_files\wxid_gee0s13lqolc12_61ca\msg\file\2026-10\gold(1).zip' `
  --decisions 'D:\WeChat_photo\xwechat_files\wxid_gee0s13lqolc12_61ca\msg\file\2026-10\裁决表(1).jsonl' `
  --out $run

& $reviewPython -X utf8 scripts/evaluate_gold_ner.py `
  --data "$run/gold/validation_gold.jsonl" `
  --app '../../app' `
  --out "$run/ner_baseline"

& $reviewPython -X utf8 scripts/train_gold_policy.py `
  --train "$run/gold/train_gold.jsonl" `
  --validation "$run/gold/validation_gold.jsonl" `
  --out "$run/policy_baseline"
```

先检查上一条命令退出码为 0，再运行下一条。脚本不会调用外部 API、不会使用测试标签选模型，也不会替换当前应用的在线权重。

## 结果如何解释

- gold 的训练、验证、测试分别有 128、92、92 个原始单位。一段完整对话算一个单位；逐轮展开后，训练与验证的 SFT 视图分别有 152、116 行。这些转换视图不能再次计入独立样本数。
- 验收检查覆盖原文与上下文、ID、split、签署字段、实体边界、动作约束、原始文件指纹及跨批次整条输入重复。结构检查不能代替人工判断，也不能单凭一个哈希证明 A/B 独立完成了复核；原始 A/B 文件与比较记录仍应归档。
- NER 结果来自当前格式与上下文检测器在 56 个 NER 验证单位上的严格实体匹配。它是后续训练要比较的起点，不是新训练 NER 的成绩，也不是真实业务隐私保护率。报告保留全部 14 类和困难负例误报。
- 动作实验使用训练批的 24 个单轮动作单位与 12 段三轮对话，共 60 个动作训练样本；验证批也有 60 个动作样本。特征仅来自输入与可信配置；历史仅使用此前用户原文，不使用 gold 动作或外发文本。
- 动作模型是整请求/对话轮次的 TF-IDF 加逻辑回归实验基线。它与应用当前的分段动作模型不同，不可直接覆盖 `app/models/necessity_action.joblib`。它不生成外发文本，动作正确率或对话动作全对数不能当作外发安全或完整会话验收结果。
- 首轮基线使用原便携 Python。后续神经网络训练与候选应用改用独立 `runtime/training_env`，已安装并验证 `torch`、`transformers`；便携 Python 本身没有因此升级。
- 测试文件只做数据验收并保留。此次检查中曾显示过首条 NER 测试样本，未用于特征设计、训练或评分，因此不应把该包描述为从未打开过。正式测试应在候选模型、参数和验收口径冻结后运行；如要求所有测试样本完全未被开发者查看，应另选替换样本并独立复核。

## 下一阶段

实体候选已可本地运行。下一阶段的研究任务是把整请求动作 v2 与应用的分段执行语义对齐，扩大独立场景和真实外发行为验收；不能把该 joblib 直接覆盖应用现有动作文件。封存测试应等候选、参数和验收口径冻结后一次性执行。验证集剩余错误已保留，不通过改动 gold 或逐例硬编码消除。

旧的“重新训练”入口已删除；后续训练直接使用明确的数据与输出参数，见根目录执行计划。
