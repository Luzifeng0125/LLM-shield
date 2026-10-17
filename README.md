# LLM-shield · 隐盾

面向高校场景的大模型隐私保护中间件。学生在把活动名单、会议纪要、项目材料交给大模型之前，先在本地完成
**识别 → 必要性判定 → 脱敏/泛化 → 受控外发 → 回答复检**，模型侧只拿到完成任务所必需的最小信息。

全过程在三个边界上做泄露观测：**发给模型的请求 / 展示给用户的结果 / 提交给工具端的内容**。
单进程本地服务，默认 <http://127.0.0.1:8787/>，识别与决策不出本机。

---

## 目录

- [处理主流程](#处理主流程)
- [仓库结构](#仓库结构)
- [快速开始](#快速开始)
- [配置](#配置)
- [敏感信息识别](#敏感信息识别)
- [模型与权重](#模型与权重)
- [实测效果](#实测效果)
- [数据集与人工复核](#数据集与人工复核)
- [验证结果](#验证结果)
- [隐私边界](#隐私边界)
- [已知限制](#已知限制)
- [分支](#分支)
- [文档索引](#文档索引)

## 处理主流程

对话、预览、单次运行三条入口**共用同一套本地策略路径**（`processing.analyze()`），
不存在「某个入口少做了一步检查」的情况：

```text
web/ → server.py → chat.py 或 pipeline.py
                     ↓
              m1_access 权限与材料读取
                     ↓
       material_processing 材料展开、逐份识别、坐标统一
                     ↓
                 m2_detect 识别与分段
                     ↓
        m4_necessity 模型评分 → m3_decide 硬约束
                     ↓
             m6_transform 脱敏与代号映射
                     ↓
       m7_egress 外发复检 → 模型 / 展示 / 工具
                     ↓
                m8_audit 记录三个边界结果
```

`schema.py` 是跨模块数据契约；`config.py` 读 `config/*.yaml`、模型目录与环境变量。
`m9_data` 与 `scripts/` 属离线工具，不在在线链路内。

> **失败关闭**：启用 GLiNER 而模型缺失或推理异常时请求**暂停**，不会被当成「没有命中」；
> 识别失败永远不会被解释成「这段是干净的」。真实 API 失败会显式报错，不静默回落为演示文本。

## 仓库结构

```
LLM-shield/
├── 启动隐盾.cmd              # 根目录启动入口（委派 delivery\启动隐盾.cmd）
├── README.md
├── AI_EXECUTION_PLAN.md      # 架构决策与后续执行顺序
├── delivery/
│   ├── app/                  # 唯一应用实现：llm_shield/ web/ config/ data/ models/ tests/ scripts/
│   ├── 数据集/               # 专项数据集 v1 + 人工复核与训练执行包
│   ├── 提交材料/             # 申报书、最终报告、答辩 PPT 与使用说明
│   └── *.cmd / *.ps1         # 安装、启动、停止、验证入口
├── docs/                     # 安装验证、架构总览、评测报告与融合记录
├── tools/qa/                 # 浏览器 QA 脚本
└── local/                    # 本机私有文档与诊断输出（Git 已忽略）
```

2026-10-17 完成本机版本与 GitHub 版本的实际融合，`delivery/app` 是唯一应用副本，不再存在第二份源码。
Git 只分发这份受维护工程：**不含** GLiNER 大权重、Python 虚拟环境、`.env` 密钥、上传材料与本机日志。

## 快速开始

### 已有本机配置

双击仓库根目录 `启动隐盾.cmd`，浏览器打开 <http://127.0.0.1:8787/>（名单核对页 <http://127.0.0.1:8787/notice>）。

```powershell
& '.\启动隐盾.cmd' --check-only   # 只做依赖与权重预检，不拉起服务
& '.\启动隐盾.cmd'                # 启动
& '.\delivery\停止隐盾.cmd'       # 停止
```

启动器先加载并校验 GLiNER 与动作权重，再拉起服务；模型不可用会明确失败。

### 从 GitHub 克隆

需要 **Python 3.12**（安装脚本会强制校验版本）。

```powershell
git clone https://github.com/Luzifeng0125/LLM-shield.git
cd LLM-shield
powershell -ExecutionPolicy Bypass -File .\delivery\安装开发环境.ps1   # 不跑模型加 -BaseOnly
```

安装脚本创建 `app/.venv` 并安装锁定依赖，但**不含 GLiNER 权重**。克隆后还需：

1. 取授权的 `gliner_v3` 完整目录（含 `pytorch_model.bin`、`gliner_config.json`、`config.json`、分词器文件、`spm.model`），
   放入 `delivery/app/models/gliner_v3`。网络上的同名公开下载**不等于**本项目的微调产物。
2. 复制 `delivery/app/.env.example` 为 `delivery/app/.env`，填写 `LLM_API_KEY`。默认 DeepSeek
   （`https://api.deepseek.com`，`deepseek-flash`），OpenAI 兼容的自建端点改 `LLM_BASE_URL` 即可。
3. 执行[验证](#验证结果)命令后再启动。

详细步骤与排错见 [docs/从GitHub安装与验证.md](docs/从GitHub安装与验证.md)。

> 建议仓库放在纯英文路径。**GLiNER 路径必须是纯 ASCII**：sentencepiece 的 C++ 后端打不开含中文路径。
> `SHIELD_MODEL_DIR` 可指向任意 ASCII 路径；决策模型本身（joblib）没有这个限制。

### 手动启动与运行时自检

```bash
cd delivery/app
python run.py --host 127.0.0.1 --port 8787

python scripts/check_runtime.py     # 启动前检查模型与 API 配置（不打印密钥）
python scripts/benchmark_local.py   # 只测本地处理耗时，不外呼、不落载荷
```

| 端点 | 返回 |
| --- | --- |
| `GET /api/health` | 动作模型 / 识别器 / 真实 API 配置 / 会话容量的就绪状态；**不返回密钥与模型路径** |
| `GET /api/metrics` | 各阶段耗时统计；每项最多保留最近 500 个数值，**只统计数字、不记录内容** |

本地识别与决策并发上限由 `SHIELD_MAX_PARALLEL_ANALYSES` 控制（默认 2，范围 1–8），
满载时新请求暂停并提示重试，避免并发把显存打满。

## 配置

关键项写在 `delivery/app/.env`（**不提交**）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_MODE` | `real` | `real` 调用真实 API；`mock` 使用本地模拟生成（仅显式 `--offline`） |
| `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` | deepseek / `https://api.deepseek.com` / `deepseek-flash` | OpenAI 兼容端点均可 |
| `LLM_API_KEY` | 空 | 只存在本机，绝不入库 |
| `LLM_TIMEOUT` | `60` | 秒 |
| `SHIELD_HOST` / `SHIELD_PORT` | `127.0.0.1` / `8787` | 服务监听地址 |
| `SHIELD_MODEL_DIR` | `models` | 模型根目录，可指向任意 ASCII 路径 |
| `SHIELD_USE_GLINER` | `true` | 正常启动强制开启；仅显式 `--offline` 关闭 |
| `SHIELD_MAX_PARALLEL_ANALYSES` | `2` | 并行分析上限（1–8） |
| `SHIELD_ACTION_MODEL_PATH` | 空 | 留空使用 `models/necessity_action.joblib` |

规则层另有四份 YAML：`rules.yaml`（敏感类别、级别、`hard_ban`）、`identities.yaml`（身份可读范围与最高可披露级别）、
`tasks.yaml`（任务必留项与永禁外发项）、`recipients.yaml`（接收方定义）。

依赖分层：`requirements-lock.txt`（基础锁定版）、`requirements-gliner.txt`（GLiNER 推理）、
`requirements-dev.txt`（开发）、`requirements.txt`（人工可读总览）。CUDA 版 PyTorch 需与显卡驱动匹配。

## 敏感信息识别

识别层由三条路组成，各司其职，结果经统一合并策略归并：

| 检测器 | 负责类别 | 说明 |
| --- | --- | --- |
| **正则规则**（常开） | 格式类 | 带校验位验证：身份证 GB 11643、银行卡 Luhn；手机号允许段内空格/连字符 |
| **词典 + 上下文**（常开） | 姓名 / 敏感属性 / 列名 | GLiNER 启用时让出机构/地点规则（词典贪婪前缀边界过宽） |
| **GLiNER**（默认启用） | 语义 5 类 | 人名 / 机构 / 地点 / 宿舍 / 敏感属性；基于 `urchade/gliner_multi-v2.1`（Apache-2.0）微调 |

**格式类永远交给正则，不交给模型**——实测让 GLiNER 覆盖 13 类会让高敏类别 F1 从 0.914 掉到 0.779
（模型买到的是人名召回，付出的是格式类误报）。

### 三个关键工程点

1. **字符级中文分词**：GLiNER 默认分词会把整串连续中文当成一个 token，导致实体边界错位。
   项目改用字符级分词器（`m2_detect/char_splitter.py`）。
2. **滑窗批量推理**：长文本按 `max_len-32` 滑窗，所有窗口一次性批量送进模型而非逐窗循环；
   多份材料的窗口还会合成一批（每批最多 16 个窗口），结果按材料还原坐标。
   实测 2000 字从 ~500 ms 降到 **~190–210 ms**，这是把识别耗时压回「P50/P95 ≤ 500 ms」指标内的关键一步。
3. **合并策略**：同类别重叠取置信度更高的精确边界；跨类别冲突按检测器可信度排序（正则 > 模型），
   避免模型的高置信猜测覆盖带校验位的正则结果。

## 模型与权重

```
delivery/app/models/
├── ACTIVE_MODELS.json        # 活动模型清单与哈希（权威来源）
├── necessity_action.joblib   # 决策模型 m4，feature v3，约 1 MB，随仓库分发
└── gliner_v3/                # 识别模型 m2，约 1.1 GB，不随仓库分发
```

清单见 [`models/ACTIVE_MODELS.json`](delivery/app/models/ACTIVE_MODELS.json)：

| 组件 | 状态 | 备注 |
| --- | --- | --- |
| 正则 + 校验规则 | 启用 | 格式类字段判定 |
| GLiNER `gliner_v3` | 默认启用，CUDA/CPU 自动选择 | 语义 5 类标签；权重哈希见清单文件 |
| 动作模型 `structured_content_v3` | 启用 | feature v3（结构/内容分路），与 v2 权重不可混用 |
| Campus NER（RoBERTa） | 已移除 | 无本机权重，叠加收益无证据 |
| reviewed_ner BERT | 仅离线评测代码 | 在线管线不导入、不加载，其历史分数不代表当前版本 |

要自行启用 GLiNER：取 `urchade/gliner_multi-v2.1`（Apache-2.0）与对应 tokenizer，
用 `delivery/app/` 下脚本微调后放到**纯 ASCII 路径**，并在 `.env` 中设 `SHIELD_USE_GLINER=true`。

## 实测效果

识别层默认「正则 + 词典 + 语义类 GLiNER」。粒度无关口径 F1：

| 测试集 | 基线（正则+词典） | + GLiNER 语义 5 类（默认） | + GLiNER 13 类 |
| --- | --- | --- | --- |
| `gold_v3` test（旧留出集，**与训练同源**） | 0.8411 | **0.9500** | 1.0000 |
| `field_v1`（独立手写集，87 条 / 149 实体） | 0.7790 | **0.9068** | 0.8443 |

> **第二行才是可信的数字。** `gold_v3` 与训练语料出自同一个生成器——身份证一律 `999999` 开头、
> 邮箱一律 `@example.invalid`，80 条 test 里有 63 条与训练集存在 8-gram 以上连续重合（78.8%），
> 它衡量的是「有没有背下模板」。`field_v1` 是独立手写的 87 条真实场景文本（真实地区码、真实 BIN、
> 真实域名、复姓与少数民族姓名、大量数值诱饵），与训练语料 8-gram 重合率仅 **2.4%**。

把 GLiNER 从 13 类收窄到语义 5 类，并在正则底座补上「带分隔符手机号、裸分数、wx_/wxid_ 微信 ID、
ghp_/AKIA 密钥」四条规则后：独立集 F1 **0.8383 → 0.9068**，高敏类别 F1 0.770 → 0.914，
纯负例误报 13/17 → 10/17 条；同源旧集从 1.0000 降到 0.9500——降掉的正是模型背下来的假密钥/裸分数模板。

识别耗时（本机 RTX 5060，启用 GLiNER）：`field_v1` 全集 1856 ms / 87 条 ≈ **21.3 ms 每条**；
13 类配置 4837 ms / 87 条 ≈ 55.6 ms 每条。样本数仍少，**不当作生产 P95**——
实际请求的分阶段耗时用 `/api/metrics` 收集。

两个测试集的 F1 均基于**合成或手写数据**，不能直接当作真实场景的隐私保护准确率。回归门禁见
`delivery/app/tests/test_field_v1.py`：识别层任何改动都必须同时看这两把尺子。

原始报告：[`delivery/app/data/field_v1/eval_report.md`](delivery/app/data/field_v1/eval_report.md)。

## 数据集与人工复核

- [专项数据集 v1](delivery/数据集/隐盾数据集_v1/README.md)：公开中文合成数据、多类实体标注、动作决策、
  三轮对话及微调格式，含预览页与校验脚本。
- [数据复核与训练执行包](delivery/数据集/复核与训练执行包_20261014/开始这里.md)：已选好训练 / 独立验证 /
  封存测试单位，含 A/B 独立标注页面、裁决工具、人员培训与模型训练脚本。**人工标注仍待团队执行**，
  因此现有权重不能宣称来自人工金标。
- [提交材料](delivery/提交材料/使用说明.md)：申报书、最终报告 docx 与答辩 PPT；历次更新版依次替代前一版，
  旧版保留用于追溯，**不要**据此判断当前实现。

## 验证结果

```powershell
& '.\delivery\运行验证.cmd'                      # smoke + pytest（mock 模式，不调用真实 API）
& '.\delivery\检查API连接.cmd'                   # 只发送一条固定公开短句，验证真实 API
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py
& '.\delivery\运行Python.cmd' -X utf8 delivery/app/scripts/verify_merged_runtime.py --connect
```

2026-10-17 本机复跑（见 [`docs/执行状态.json`](docs/执行状态.json)）：

| 项目 | 结果 |
| --- | --- |
| smoke | 38 项通过，0 失败 |
| pytest | 402 项通过，0 失败、0 跳过（含 `delivery/数据集/复核与训练执行包_20261014/scripts`） |
| GLiNER CUDA 预检 | 通过 |
| 合成名单核对 / 全表计数 / 网页路由 | 通过 |
| 真实 DeepSeek 公开短句往返 | 通过，示例整轮 1831 ms |

软件通过和一次接口联调**不等于**新独立材料上的准确率。

## 隐私边界

- `.env`、上传材料、GLiNER 大权重、本机私有文档与会话历史均不入库，`.gitignore` 逐条覆盖。
- `/api/health` 与 `/api/metrics` 只返回就绪状态和有界耗时统计，不含原文、代号映射或密钥。
- 昂贵识别器为带锁单例，并行分析受限，耗时记录最多 500 条且不保存内容。
- 会话为单进程内存映射，关闭、过期或清除时释放私有原值与代号表；重启即失效。
- 名单核对只在本机执行；通知生成只接受单独填写的公开活动信息，不接受名单、文档 ID 或历史。
- 用户上传的真实工作簿只做本机只读验证，不直接充作训练金标。

## 已知限制

- **动作决策**：TF-IDF + 逻辑回归分类器本地选动作，安全校验**只接受或暂停，不做规则动作兜底**。
- **识别边界**：地点、宿舍、间接身份标识与复杂跨表统计的精度尚未在独立盲测集上单独测量；
  现有 GLiNER 开发集与历史 BERT 分数均不适用。
- **表格统计**：精确统计目前只支持单张选中表内的窄口径「专业 / 学院 / 校区人数」，
  不把检索片段交给模型推断全表。
- **多轮一致性**：会话内代号已稳定（同一实体在同一会话得到同一代号），但多轮人工验收尚未执行。
- **组合式重识别**（如唯一奖项 + 组织 + 代号联合可重新识别到人）尚未覆盖。
- **身份与存储**：身份选择目前是界面配置，**不是**生产级身份认证；会话为进程内存储，仅支持单进程。
- **性能与部署**：冷启动有一次模型加载开销；P50/P95 与大文件资源占用尚未完整记录；
  其他机器的 CUDA 环境与权重分发流程未验收。

后续计划见 [`AI_EXECUTION_PLAN.md`](AI_EXECUTION_PLAN.md)。

## 分支

| 分支 | 内容 |
| --- | --- |
| `main` | **主线**：融合后的单一目录结构 + GLiNER 识别层 + feature v3 决策 + 数据集与复核工具 + 2026-10-17 工程加固 |
| `v3` | GLiNER 识别层的工作分支，已并入 `main`，仅作历史追溯（本地保留） |
| `frontend` | 前端改版分支，已并入 `main`（本地保留） |

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/从GitHub安装与验证.md](docs/从GitHub安装与验证.md) | 依赖安装、GLiNER 权重放置、验证命令与排错 |
| [docs/项目现状与架构总览.md](docs/项目现状与架构总览.md) | 在线路径、模型取舍与验证边界 |
| [docs/版本对照与取舍_20261017.md](docs/版本对照与取舍_20261017.md) | 本机版本与 GitHub 版本的融合记录 |
| [docs/评测报告-独立手写集field_v1.md](docs/评测报告-独立手写集field_v1.md) | 独立手写集评测与独立性校验 |
| [docs/标注数据评估-与方案更新.md](docs/标注数据评估-与方案更新.md) | 标注数据评估与方案修订 |
| [docs/本地模型联调_20261016.md](docs/本地模型联调_20261016.md) | 本机 GLiNER 与动作模型联调记录 |
| [docs/名单样例联调_20261017.md](docs/名单样例联调_20261017.md) | 名单核对与通知生成联调 |
| [docs/地点与宿舍候选验证_20261017.md](docs/地点与宿舍候选验证_20261017.md) | 地点与宿舍候选词验证 |
| [AI_EXECUTION_PLAN.md](AI_EXECUTION_PLAN.md) | 架构决策与后续执行顺序 |

---

项目未附加开源许可证，代码与材料默认仅供交流学习；如需使用或二次分发请先联系作者。
