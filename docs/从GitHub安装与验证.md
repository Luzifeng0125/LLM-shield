# 安装与验证

推荐使用纯英文路径，例如 D:/project/LLM-shield。GLiNER 的分词器在本机使用 ASCII 路径，项目源码位于 delivery/app。

## 本机已有完整配置

双击根目录“启动隐盾.cmd”，或在 PowerShell 执行：

```powershell
& '.\启动隐盾.cmd' --check-only
& '.\启动隐盾.cmd'
```

地址为 http://127.0.0.1:8787/。GLiNER 开启、自动选择 CUDA/CPU；DeepSeek 使用 delivery/app/.env 的配置。需要模拟生成时显式增加 --offline。检查API连接.cmd 仅发送固定公开测试短句。

## 新机器或干净克隆

1. 安装 Python 3.12，运行 `powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1`。基础依赖使用 requirements-lock.txt，GLiNER 推理依赖使用 requirements-gliner.txt。CUDA PyTorch 版本应与显卡驱动匹配。`-BaseOnly` 只供不运行模型的软件开发环境使用。
2. 从授权本机训练产物取得完整 gliner_v3 目录，放入 delivery/app/models/gliner_v3，至少包含 pytorch_model.bin、gliner_config.json、config.json、tokenizer 文件和 spm.model。当前哈希见 ACTIVE_MODELS.json。Git 不分发这份大权重；普通同名下载不能视为当前微调产物。
3. 复制 delivery/app/.env.example 为 delivery/app/.env，并在本机填写 LLM_API_KEY。默认官方 DeepSeek 地址为 https://api.deepseek.com，模型为 deepseek-flash。不要提交 .env。
4. 运行预检与软件验证，然后启动服务。安装本身不能证明 CUDA 与模型质量已经验收。

“运行Python.cmd”优先使用 SHIELD_PYTHON，随后读取本机 delivery/runtime/python-path.txt；未配置时使用 app/.venv。当前机器复用已安装完整 GLiNER/CUDA 依赖的解释器。两种 Python 环境不会同时加载应用。

## 验证

```powershell
& '.\delivery\运行验证.cmd'
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py
# 仅发送固定公开短句，验证真实生成：
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py --connect
```

软件验证在测试子进程关闭 GLiNER 并使用 mock，同时保留故障与边界测试；模型运行验证单独开启实际 GLiNER。验证命令按入库合成批次和哈希清单重建缺失的空白复核表，已有表不会覆盖；生成空白输入不构成人工标注。

维护模式不再要求 Campus NER 或 reviewed_ner BERT。真实模式 API 失败会报错，不静默回落为演示文本。当前会话保存在单进程内存，重启会清除。
