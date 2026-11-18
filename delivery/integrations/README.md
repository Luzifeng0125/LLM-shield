# 五项目融合接入

隐盾 2.0 候选版提供五个项目的接入路径。基础融合已通过 [PR #4](https://github.com/Luzifeng0125/LLM-shield/pull/4) 合入 `main`。统一配置位于 `delivery/app/config/integrations.yaml`。`SHIELD_INTEGRATIONS_CONFIG` 可指定本机独立配置文件，修改后重启服务。

## 实现与验证范围

| 组件 | 实现 | 验证范围 |
| --- | --- | --- |
| Presidio | 追加本机 PatternRecognizer，转换成隐盾 Span，沿用合并与动作决策 | 使用真实 2.2.366 库识别合成编号，无网络请求 |
| NeMo | 使用 LLMRails 和 Colang input flow 调用本地拒绝短语检查 | 使用真实 0.24.1 库验证放行、暂停及网关接入，无模型调用 |
| LiteLLM | 兼容代理请求，校验代理地址及模型别名，提供固定上游配置 | 隐盾生成客户端经过实际 1.109.1 代理访问合成回环上游 |
| Dify | 实现 External Knowledge API，凭证绑定固定来源、身份、用途和接收方 | 协议测试覆盖鉴权、转换后内容、来源删除和不支持的过滤条件 |
| Lakera | 本地检查后调用 `/v2/guard`，要求 enforce 策略及有效布尔结果 | 本机 HTTP 契约测试覆盖拒绝、无效响应及 detect-only |

Dify 实际实例和 Lakera 商业账户仍需连通验证。NeMo 当前执行配置中的短语规则，通用注入识别和越狱检测需要后续选定策略及评测集。Presidio 接入自定义模式识别，GLiNER 继续负责语义类。六类动作沿用隐盾必要性模型。

## 本机启用

首页“识别与集成”可查看配置状态、核对实体来源、动作及硬约束，修订文本后重新检查。页面仅供回环地址使用。

在仓库根目录安装可选组件。

```powershell
& '.\delivery\运行Python.cmd' -m pip install -r delivery/app/requirements-presidio.txt
& '.\delivery\运行Python.cmd' -m pip install -r delivery/app/requirements-nemo.txt
```

在当前激活配置中将 `presidio.enabled` 和 `nemo.enabled` 设为 true。Presidio 规则填写名称、已有隐盾类别、正则和分数。启用的组件配置或依赖不可用时暂停处理。

仓库配置默认关闭可选组件，供干净安装选择。2026-11-18 本机激活文件为 `local/integrations_active.yaml`，由应用 `.env` 的 `SHIELD_INTEGRATIONS_CONFIG` 引用。预检已确认 regex、entity、gliner 和 presidio 同时可用，GLiNER 使用 CUDA。词典测试模式下，Dify 检索和确认工具暂停外发。

## LiteLLM

单独建立代理环境并安装 `delivery/app/requirements-litellm.txt`。通过环境变量设置 `LITELLM_MASTER_KEY` 与 `SHIELD_UPSTREAM_API_KEY` 后启动。

```powershell
litellm --config delivery/integrations/litellm.yaml --host 127.0.0.1 --port 4000
```

隐盾 `.env` 配置如下，`LLM_API_KEY` 填代理凭证。

```dotenv
LLM_MODE=real
LLM_PROVIDER=litellm
LLM_BASE_URL=http://127.0.0.1:4000/v1
LLM_MODEL=shield-primary
```

在激活配置中启用 litellm，登记相同地址和 `approved_models`。示例代理使用单一明确上游，关闭跨供应商回退及正文日志。客户端验证地址和别名，代理管理员负责该别名实际指向的部署。更换实际供应商时重新评审接收范围。

样例设置请求及 token 限流。多人虚拟密钥、项目预算、费用面板需要数据库及身份配置，未自动部署。代理验证脚本依赖隐盾应用及代理两份依赖，使用临时配置经隐盾客户端调用代理及合成回环上游，无付费模型调用。

```powershell
python delivery/app/scripts/verify_litellm_local.py
```

## Dify 外部知识库

每个知识源固定绑定获准材料、身份、用途及外发接收方，并使用独立凭证。

```yaml
knowledge:
  campus-public:
    identity: student_leader
    task: meeting_minutes
    recipient: egress_tool_public
    token_env: SHIELD_DIFY_CAMPUS_TOKEN
    doc_ids: [替换为已上传材料编号]
```

在 `.env` 填写对应凭证，长度至少 32 字符。Dify 外部知识 API 地址填 `http://127.0.0.1:8787/api/integrations/dify`，知识源编号填 `campus-public`。Dify 请求 `/retrieval`。容器内 Dify 需要能访问隐盾的受控网络地址及部署层鉴权，默认启动器仅监听回环地址。

调用方无法覆盖身份、用途及来源范围。系统先做本地决策与转换，再检查实际返回内容。原始映射、本机路径和文件名不作为返回元数据。来源删除、过期或用途不符时拒绝返回，内容或策略变化会产生新引用。

当前检索将处理后文本分为最多 1200 字符的片段，按词项重合度打分；中文用相邻两字组成词项，无嵌入服务。每个知识源最多 20 份材料，每份分析上限 24000 字符，一次最多返回 5 个片段。整份转换结果仅在本机预检；排序选中的片段带原始检测与本机代号上下文执行完整出口检查，启用 Lakera 时只检查选中的片段。任一选中片段被拦截时本轮不返回内容。`score_threshold` 对应该词项分数。非空 `metadata_condition` 尚不支持，会明确拒绝。

## Lakera

设置 `lakera.enabled` 和 `approved_for_checked_content` 为 true，并在 `.env` 配置 `SHIELD_LAKERA_API_KEY`。这项设置允许该服务接收通过本机检查的外发文本。

本机权限及载荷检查先执行，随后附加 NeMo 和 Lakera 检查。授权展示可能含恢复原值，展示内容不会交给 Lakera。超时、缺少有效许可或返回 detect-only 时暂停。实际检测范围取决于商业账户策略，本分支未替账户设置策略。

## 受控工具

管理员配置固定 Webhook 地址、凭证、身份、用途及接收方。

```yaml
tools:
  deliver:
    endpoint: https://your-owned-service.example/receive
    token_env: SHIELD_DELIVERY_TOKEN
    identity: student_leader
    task: meeting_minutes
    recipient: egress_tool_public
```

地址支持 HTTPS 或回环 HTTP，工具凭证至少 16 字符。网页“外发工具确认”使用已有 `SHIELD_WORKFLOW_ADMIN_TOKEN`。先检查交付正文并展示接收地址，用户确认后执行，预览有效期两分钟。

实际 POST 正文为 `text` 和 `event_id`，附带 Authorization 及 Idempotency-Key。工具编号、正文或配置变化须重新预览。事件编号持久化到 SQLite，同一成功事件不重复发送。超时、执行中、响应过大或响应复检失败保留待核对状态，需在接收端确认。接收端仍须实现幂等。返回内容检查通过后，页面只展示执行结果。

该接口处理已经核对的交付文本，不会自动执行模型提出的任意工具调用，也未实现完整邮件或办公系统连接器。

## 回归与升级

2026-11-18 集成相关 24 项测试和 38 项冒烟检查通过。完整回归通过 485 项，另有一项旧多轮用例因 GLiNER 在部分人员代号上下文中将“准备海报”识别为敏感属性而失败。可选库在独立环境和本机应用环境分别验证，新诊断页通过桌面及 390 像素宽度的实际浏览器操作检查。

```powershell
& '.\delivery\运行Python.cmd' -m pytest delivery/app/tests/test_integrations.py -q
```

新增工具事件位于 `outputs/integrations`，不保存正文或工具响应。安装时记录 Python、NumPy 和可选组件版本，执行模型预检与回归。停用组件可在激活配置关闭对应开关。源材料仍使用现有单机用途及生命周期约束，组织身份隔离继续按计划建设。

参考接口为 [Presidio](https://presidio.dataprivacystack.org/samples/python/customizing_presidio_analyzer/)、[NeMo 自定义动作](https://docs.nvidia.com/nemo/guardrails/configure-guardrails/actions/registering-actions)、[LiteLLM](https://docs.litellm.ai/docs/simple_proxy)、[Dify External Knowledge API](https://docs.dify.ai/en/self-host/use-dify/knowledge/external-knowledge-api) 和 [Lakera Guard API](https://docs.lakera.ai/api-reference/lakera-api/guard/screen-content)。
