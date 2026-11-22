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

## 受控复现材料

两份 `app/data/ner_v3b` 历史增强语料继续保留原始字节。取得获准副本后放回同名路径。`field_v1_check.py` 的重叠分析需要训练分片，缺失时会停止。项目的生成脚本、训练方法、实验记录和冻结裁定保留原有版本与位置。文件摘要用于确认取得的是同一批材料。

| 相对路径 | SHA-256 |
| --- | --- |
| `app/data/ner_v3b/newtest300.jsonl` | 51bf20f25e3a04932aeb56d0fa153a2302cad9f9e1c96e0bfb717292ff10fc6a |
| `app/data/ner_v3b/train_aug300.jsonl` | 03437817eb2df61a8f135961eab8617a7f1291e22632498d34a43e2ffb429aa8 |

研究手册的 Word 原件带有文档属性，由资料负责人保管。同批 `scripts/build_manual.py` 可从已有内容生成本机手册；`scripts/render_manual.ps1` 在具备 Word 和 Poppler 时渲染。历史交付清单继续代表当时的原件。
