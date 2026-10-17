# 从 GitHub 安装与验证

本页适用于全新克隆。仓库包含应用源码、测试和动作分类器权重；**不包含**本机 Python 虚拟环境和 `reviewed_ner` 大权重。缺少后者时，当前维护的 BERT NER 模式不能启动。不要把旧版 GLiNER 或规则底座当作该模型的替代品来声称验收通过。

## 1. 建立 Python 环境

需要 Windows 和 Python 3.12。在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1
```

安装器在 `delivery/app/.venv` 建立本机环境并安装 `requirements-lock.txt`。如果没有检测到 Python 3.12，可传入安装路径：

```powershell
powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1 -PythonPath 'C:\Python312\python.exe'
```

需要运行人工复核 BERT NER 时，再安装推理依赖：

```powershell
powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1 -WithNer
```

`-WithNer` 从当前 pip 源安装 PyTorch 和 Transformers；若使用 CUDA，应按本机驱动和 PyTorch 官方说明选择匹配的 wheel。CPU 也可运行，但推理速度会不同。安装成功不等于模型权重已经就绪。

## 2. 放置本机模型

从项目授权的训练产物或原运行机器取得**完整** `reviewed_ner` 目录，放到 `delivery/app/models/reviewed_ner`。目录至少包含：

```text
reviewed_ner/
  artifact_manifest.json
  model/
    config.json
    model.safetensors（或清单列出的分片）
    tokenizer 相关文件
```

`artifact_manifest.json` 中的文件哈希、标签映射和数据来源由应用加载时逐项校验。当前活动版本及预期权重哈希见 `delivery/app/models/ACTIVE_MODELS.json`。**不要**从网上随意找一个同名 BERT 替换，也不要把 `.env`、真实名单、上传资料或大权重提交到 Git。若拿不到这份模型产物，当前维护模式会明确失败，无法完成其真实运行验收。

动作权重已经入库，可独立核对：

```powershell
(Get-FileHash .\delivery\app\models\necessity_action.joblib -Algorithm SHA256).Hash.ToLower()
```

结果应与 `ACTIVE_MODELS.json` 的 `action.weights_sha256` 一致。

## 3. 验证

先运行不依赖大权重的软件回归：

```powershell
& '.\delivery\运行验证.cmd'
```

该命令先执行独立 smoke，再运行 pytest；不会调用真实生成 API。然后验证维护模式：

```powershell
& '.\启动隐盾.cmd' --check-only
& '.\启动隐盾.cmd'
```

`--check-only` 会实际加载本地 NER 与动作模型，并在不启动网页服务、不外发请求的条件下做软件样例推理。通过后页面地址为 `http://127.0.0.1:8789/`，名单页面为 `/notice`。当前统一入口强制 `LLM_MODE=mock`；它不能证明 DeepSeek 或其他真实生成服务已连通。真实 API 检查是独立入口，必须仅用公开、合成内容进行。

软件验证会从仓库中的合成批次与哈希清单恢复**缺失**的空白复核表。它不会覆盖已有复核表，也不会生成或冒充人工标注。复核表不受 Git 跟踪，测试通过不代表有真实人审结果。

## 4. 通用文件对话与 DeepSeek

复制 `delivery/app/.env.example` 为 `delivery/app/.env`，只在本机填写 `LLM_API_KEY`。示例配置使用 DeepSeek 官方 `https://api.deepseek.com` 和 `deepseek-flash`；模型名称与接口可能变化，联调前核对[官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。不要把 `.env` 提交到 Git。

```powershell
Copy-Item .\delivery\app\.env.example .\delivery\app\.env
# 在本机编辑 .env，填写 LLM_API_KEY
& '.\启动通用对话.cmd'
```

这个入口监听 `http://127.0.0.1:8787/`，强制 `LLM_MODE=real`；无密钥或 API 失败时给出错误，不会静默降级为演示回复。它以规则识别和已入库动作模型运行，**不等同于**缺少权重的人工复核 BERT 版本。模型回复只能在安全处理和外发检查通过后取得；对包含个人信息的文件，先在本机用合成材料验证配置与边界，再决定是否调用外部服务。

## 当前克隆版的已知限制

- Git 不分发 `delivery/runtime/training_env` 和 `delivery/app/models/reviewed_ner`，因此全新克隆的 `--check-only` 在取得权重前应失败。
- 仓库的测试、开发数据和既有开发集结果不能替代新的独立盲测，也不能证明实际名单均被正确识别。
- 用户真实表格属于本机私有资料，不应复制进仓库、测试快照或日志。未经人工核对的表格字段不能直接宣称为人工金标。
- 此安装流程只在当前开发机执行过；跨机器 CUDA、模型权重分发和资源曲线仍需另行验收。
