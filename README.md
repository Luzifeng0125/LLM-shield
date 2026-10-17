# 隐盾 LLM-Shield

当前版本已融合原本地项目与 GitHub 版本，唯一维护目录为 `D:/project/LLM-shield`，应用源码位于 `delivery/app`。默认识别链为**正则校验 + 词典表头补充 + GLiNER**，动作模型使用本机配套的 feature v3，生成使用本机配置的 DeepSeek。

## 启动

本机双击根目录 `启动隐盾.cmd`，打开 http://127.0.0.1:8787/；名单核对页面为 http://127.0.0.1:8787/notice。启动器先加载并验证 GLiNER 和动作权重，再启动服务；模型不可用时明确失败。

```powershell
& '.\启动隐盾.cmd' --check-only
& '.\启动隐盾.cmd'
& '.\delivery\停止隐盾.cmd'
```

配置在 `delivery/app/.env`，密钥只保留在本机。GLiNER 默认开启；正常启动会强制开启。只有显式 `--offline` 才使用模拟生成。真实模式 API 失败时显示错误，不会退回离线演示。

全新 Git 克隆需安装依赖、单独取得授权 GLiNER 权重并配置密钥，步骤见[安装与验证](docs/从GitHub安装与验证.md)。Git 包含动作权重，不分发 GLiNER 大权重、Python 环境或本机资料。

## 合并后的架构

对话、预览和单次运行共用 `processing.py` 与 `material_processing.py`：权限检查 → 按材料解析与批量识别 → 分段动作分类 → 约束检查 → 转换 → 外发与回答复检。健康状态 `/api/health`、最近耗时 `/api/metrics` 不返回材料原文或密钥。会话为单进程内存，重启会清除。

Campus NER 及其预训练代码已从应用中移除；没有证据需要与 GLiNER 叠加。原人工复核 BERT 适配器仅供显式离线评测，在线管线不导入、不加载。模型权威清单为 [ACTIVE_MODELS.json](delivery/app/models/ACTIVE_MODELS.json)。旧 BERT 分数不代表当前 GLiNER 版本的精度。

Excel 支持多工作表、常见合并标题和部分 WPS 校验标记。大表对话用相关片段限制推理量；符合“专业/学院/校区人数”的窄口径问题由本机查完整选中表统计，避免用片段推断全表。

名单核对在本机执行；通知生成只接受单独填写的公开活动信息。通用文件对话中的处理结果仍须经过外发检查。

## 目录与验证

- `delivery/app`：唯一应用实现、配置、测试及本机活动权重。
- `delivery/数据集`：合成数据与人工复核、训练工具。
- `docs`：当前架构、历史实验和合并记录。
- `local`：从原目录迁入的私有文档、数据变体与诊断输出，Git 忽略。
- `delivery/runtime`：本机解释器选择，Git 忽略。

```powershell
& '.\delivery\运行验证.cmd'
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py
# 以下命令只用固定公开短句验证真实生成，会消耗少量 API 额度：
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py --connect
```

本机已通过 38 项 smoke、307 项 pytest 和 95 项子检查；GLiNER CUDA 预检、本机名单核对、全表统计、公开短句真实对话均已通过。软件通过和一次接口联调不能代表新独立材料上的准确率。详情见[合并记录](docs/版本对照与取舍_20261017.md)和[当前架构](docs/项目现状与架构总览.md)。
