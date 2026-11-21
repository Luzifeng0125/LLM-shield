# 研究与标注

历史复核材料位于[datasets/legacy](datasets/legacy)。校准、独立测试、AI建议与人工返还维持各自身份。冻结数据按原始字节迁移，清单哈希可继续核对。

研究脚本保留app/scripts兼容入口，训练与候选特征模块维持原Python导入路径。在线金额补全引用campus_v11.magnitude，该模块继续随应用分发。

| 工作 | 兼容入口 |
| --- | --- |
| 训练与候选实验 | ../app/scripts/train_*.py、run_*experiment.py |
| 标注与复核 | ../app/scripts/build_*pack*.py、import_*review*.py |
| 独立评测 | ../app/scripts/eval_*.py、../app/eval |
| 模型状态 | [模型说明](../app/models/README.md) |

从app目录使用项目Python执行。新实验使用research/实验名分支，结果需记录数据版本、代码提交、模型哈希与是否晋级。私有返还保存到local/private-data，生成包放local/exports。
