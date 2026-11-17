# 隐盾应用

应用只有这一份实现。入口为仓库根目录的“启动隐盾.cmd”，端口 8787。代码与本机 GLiNER 权重都在本目录内；密钥从 .env 读取。

对话、预览、单次运行共用 processing.py 和 material_processing.py；GLiNER 单例加载，批量处理材料窗口。格式标识符由正则与校验规则识别，语义类别由 GLiNER 与词典补充。动作模型 feature v3 与其权重配套，不兼容的候选不能直接替换。

Campus NER 已移除。eval/reviewed_ner.py 仅由离线 BERT 比较脚本显式使用，在线识别管线没有该模型开关。模型清单见 models/ACTIVE_MODELS.json；安装和验证命令见根目录 README。

config、web、tests 分别保存配置、前端与回归；data/uploads、outputs、.env 和本机大权重被 Git 忽略。/api/health 用于就绪检查，/api/metrics 返回有界的阶段耗时统计。

## 生成服务与组织策略

默认 `LLM_MODE=real`。已有的 `auto` 配置同样走真实生成。缺少密钥或请求失败时，界面显示原因，本轮暂停。本机全表统计无需生成服务。可用启动脚本的 `--offline` 参数显式切换模拟生成。

在应用目录使用启动器同一 Python 运行 `python -m llm_shield.api_check` 可检查配置。加 `--connect` 会发一条固定公开短句测试实际连接，可能产生少量 API 费用。

如已有 [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy)，可将 `LLM_PROVIDER=litellm`、`LLM_BASE_URL=http://127.0.0.1:4000`、`LLM_MODEL` 及 `LLM_API_KEY` 分别设为代理标识、地址、部署别名及虚拟密钥。隐盾先检查完整消息，再交由代理选择上游。远程生成地址须使用 HTTPS。代理侧的日志、路由及回退服务按部署方策略配置。

可选的 [OPA](https://www.openpolicyagent.org/docs/rest-api) 为组织提供额外的授权层。在应用目录执行 `opa run --server --addr 127.0.0.1:8181 config/opa`，再在 `.env` 设置 `SHIELD_EGRESS_POLICY=opa` 并重启。样例策略只许可列出的会议纪要操作。部署前按组织职责修改许可清单。隐盾只把角色、任务、接收方和操作标识交给回环地址上的 OPA。模型输入、对话回答、授权展示和工具外发分别查询许可。服务故障、超时和未知许可均暂停对应操作。本地权限及载荷复检继续生效。

多轮对话默认将历史消息与本轮动作评分隔离。通过复检的历史仍可送给生成服务，支持追问。

## 本地项目工作流

使用 [项目工作流试运行说明](../../04_技术文档/项目工作流试运行.md) 启用管理员凭证，并在 PowerShell 中调用本地 API。项目入口提供替身分配、供应商签到和买方封存验收。
