# 隐盾 · 必要性模型驱动的保留/脱敏重构设计方案（v2）

> 状态：**✅ P0 + P1 已实现并验证通过**
> 编写日期：2026-10-11
> 涉及模块：`m2_detect` / `m3_decide` / `m4_necessity` / `config` / `web` / `server.py`

## 实施状态（2026-10-11）

| 项 | 状态 | 产物 |
|---|---|---|
| 分层门槛（按 信任度 × 类别 校准） | ✅ | `config/retain_thresholds.json` |
| 必要性模型重训（标签改为任务必要性） | ✅ | `models/necessity_v2.joblib`，准确率 **0.9748** |
| 三段决策 + 细粒度 | ✅ | `m3_decide/decision_v2.py` |
| 必要性判定层 | ✅ | `m4_necessity/necessity_verdict.py` |
| 受控保留权限判定（含 trust 门槛） | ✅ | `m3_decide/retain_policy.py` |
| 细粒度转换 | ✅ | `anonymizer.process_segment_v2()` |
| 训练集生成 | ✅ | `m4_necessity/dataset_v2.py` → 28435 条 |
| 前端四项改动 | ✅ | `web/index.html` / `app.js` / `style.css` |
| 测试 | ✅ | `tests/test_decision_v2.py`（22 项）等，全套 **109 项全绿** |

**关键验证结果**：

| 验证项 | 结果 |
|---|---|
| 关掉必要性模型 | 中/高信任保留率 **20.1%/23.4%/29.2% → 0%**；低信任本就短路（正确） |
| full vs fixed | 保留率 **15.3% vs 0%/20.1%/23.4%**，full 具备接收方差异化、fixed 恒 15.3% |
| 安全性 | 所有接收方 × 开关组合 **0 泄露**，完成率 100% |
| v1 回归 | `test_smoke` 38 项无破坏 |

### 实现期发现并修复的三个问题（原设计未覆盖）

1. **受控保留需要 trust 门槛**。原设计只做「级别 + forbidden」核对，而
   `PERSON_NAME`(L2) 对 `external_model`(L2) 是**放行**的 → 会把学生真名发给云端模型，
   且评测口径（`absolute_ban ∪ never_send`）不含 PERSON_NAME，**指标上还看不出来**。
   已在 `check_retain_permission` 补 `trust >= medium` 要求。

2. **权限核对必须叠加任务 `never_send`**。否则 meeting_minutes 的 `PHONE`
   （明令禁发）会被受控保留 → 判为泄露。已补。

3. **脱敏通道内仍需「不破坏任务」约束**。只按代价选会恒选 DELETE（cost=0），
   「负责人张明」被删成「负责人」，指代关系丢失。已在 `_pick_masking_action`
   叠加 v1 的 `_breaks_task`。
   职责因此明确为：「保留 vs 脱敏」由模型定；「脱敏用哪个动作」由规则约束 + 代价定。

4. **空任务描述会导致分数偏低**。模型与门槛都是带描述训练的，
   线上若传空串则特征变成 `[DESC]NONE`（分布外）。已在 `_resolve_description`
   回退到任务默认描述，保证训练/校准/推理三处特征一致。

---

## 0. 一句话概括这次改动的本质

**把「必要性模型」从决策流程的装饰品提升为主干决策者。**

现状：必要性模型只在两个**同代价**动作之间做 tie-break，而六种动作的披露代价
（0/1/2/3/5）两两不同，导致这个 `min(cost, -score)` 的第二个字段**永远读不到**
（`eval/run_ablation.py` 已实测：关掉它指标完全不变）。

新设计：必要性模型负责回答一个**决策性问题**——「这段信息对当前任务是否必要」，
即决定片段进入 **可保留** 还是 **必须脱敏** 两条通道。动作选择被降级为
"必须脱敏"通道内的次要问题。

这是一次**决策语义**的升级：从「在所有动作里挑代价最小的」，变成
「先判断该不该保留，再决定怎么脱敏」。

---

## 1. 新旧决策流程对照

### 1.1 现状（v1）

```
片段
 └─① 硬约束过滤（五类检查）
      └─② 任务必需信息检查（TASK_BREAK_RULES，硬编码规则表）
           └─③ 在剩余动作中选 disclosure_cost 最小
                └─ 其余片段 RETAIN
                      └─ 边界检查
```

问题：② 是**硬编码的规则表**（`TASK_BREAK_RULES`），③ 的排序由**人手赋的成本**决定。
必要性模型只能在 ③ 里等一个几乎不会出现的平局。

### 1.2 新设计（v2）

```
片段 + 上下文（类别/局部文本/任务模板/任务描述/接收方/列名/是否已聚合/保留偏好/字段级偏好）
 │
 ├─① 硬约束过滤【规则库只给"禁止"与"敏感级别"】
 │     · level 4（证件/银行卡/密钥/敏感属性）→ 硬禁止，直接进「必须脱敏」
 │     · 低置信 + 高风险 → 暂停转人工（PAUSE）
 │
 ├─② 必要性判断【必要性模型做「保留 vs 脱敏」二选一】
 │     · 字段级偏好=强制保留 → 直接进「可保留」（跳过模型）
 │     · 字段级偏好=强制脱敏 → 直接进「必须脱敏」（跳过模型）
 │     · 自动 → 必要性分数 vs 门槛（门槛受保留偏好调节）
 │          ├─ 分数 ≥ 门槛 → 进「可保留」
 │          └─ 分数 < 门槛 → 进「必须脱敏」
 │
 ├─③ 路径分流
 │     ├─「可保留」→ 权限核对
 │     │      有权限 → RETAIN（受控保留，原样保留）
 │     │      无权限 → 降级 PSEUDONYMIZE（代号替换）
 │     └─「必须脱敏」→ 选代价最小的动作
 │            DELETE / LOCAL_AGGREGATE / GENERALIZE / PSEUDONYMIZE
 │            无可行方案 → PAUSE（暂停外发）
 │
 └─④ 边界检查（三边界观测，不变）
```

**核心变化一句话**：必要性模型在「保留」与「脱敏」之间选，而不是在「代号替换」与「泛化」之间选。

---

## 2. 数据模型改动（前后端契约）

### 2.1 请求侧新增四个字段

现有 `ShieldRequest`（`llm_shield/schema.py`）新增：

```python
@dataclass
class ShieldRequest:
    session_id: str
    identity: str
    task: str
    recipient: str
    materials: List[Material]
    user_instruction: str = ""
    enabled_categories: Optional[Set[str]] = None

    # ---- v2 新增 ----
    task_description: str = ""                       # 前端①：任务描述自由文本
    retain_preference: str = "balanced"              # 前端②：prioritize_retain|balanced|prioritize_delete
    field_preferences: Dict[str, str] = field(default_factory=dict)
                                                     # 前端③：{类别: auto|force_keep|force_mask}
    decision_mode: str = "necessity_v2"              # 后端开关：rule_v1|necessity_v2
```

### 2.2 响应侧新增必要性解释

`PipelineResult` 新增：

```python
    necessity: List[Dict[str, Any]] = field(default_factory=list)
    # 每项 = {
    #   "seg_id": "seg_3",
    #   "text": "负责人张明",
    #   "categories": ["PERSON_NAME"],
    #   "necessity_score": 0.82,
    #   "threshold": 0.50,
    #   "advice": "keep",                # keep | mask | pause
    #   "route": "keep_to_retain",       # keep_to_retain|keep_downgraded|must_mask|paused
    #   "reason": "必要性=0.82，会议纪要需要保留责任关系",
    #   "scores": {"DELETE":0.02,"LOCAL_AGGREGATE":0.05,
    #              "GENERALIZE":0.08,"PSEUDONYMIZE":0.11,"RETAIN":0.74}
    # }
```

---

## 3. 后端四项改动

### 3.1 规则库去动作化

**现状**：`config/tasks.yaml` 里每个任务都有 `prefer` 段，为各类别预设首选动作：

```yaml
meeting_minutes:
  prefer:
    PERSON_NAME: PSEUDONYMIZE      # ← v2 移除
    PHONE: DELETE
```

**v2 改动**：

| 文件 | 改动 | 说明 |
|---|---|---|
| `config/rules.yaml` | **保留** `categories`（level + hard_ban），新增 `retain_policy` 段 | 只表达"禁止"与"敏感级别" |
| `config/tasks.yaml` | `prefer` 段标记 `deprecated: true`，v2 路径不读 | 保留供 v1 双路径使用 |
| `m3_decide/decision.py` | `TASK_BREAK_RULES` 标记 `deprecated`，v2 路径不读 | 职责移交必要性模型 |

`config/rules.yaml` 新增：

```yaml
# ------------------------------------------------------------
# v2：必要性判断的保留策略（规则库只定义"级别"，不预设动作）
# ------------------------------------------------------------
retain_policy:
  # ⚠️ 门槛必须**按类别分层**，不能用单一全局门槛。
  #    实测（cases_dev 1910 个片段）：各类别的 P(RETAIN) 分布差异极大，
  #    全局门槛 P50=0.093 会让 API_KEY/DORM/WECHAT/LOCATION 保留率 =100%，
  #    而 EMAIL/PHONE/STUDENT_ID 保留率 = 0.0%、PERSON_NAME 仅 6.7%。
  #    分层后每类保留率均回到 ~50%（见 §3.2 实测）。
  #
  # 数值由 scripts/calibrate_threshold.py 在语料上**按类别**按分位数校准，
  # 下面的 null 表示"用校准产物 config/retain_thresholds.json 覆盖"。
  threshold_by_category: null      # ← 由校准脚本生成

  # 优先保留/优先删除：把分层门槛整体乘一个松弛系数
  preference_factor:
    prioritize_retain: 0.75        # 门槛 × 0.75 → 更易保留（保留率升到 ~70%）
    balanced: 1.00
    prioritize_delete: 1.25        # 门槛 × 1.25 → 更易脱敏（保留率降到 ~30%）

  # 兜底：某类别没有校准值时的全局门槛
  fallback_threshold: 0.09

  # 无权限时的降级动作（受控保留失败后的退路）
  downgrade_action: PSEUDONYMIZE

  # 不可降级为代号替换的类别（只能继续在"必须脱敏"里选）
  non_pseudonymizable_on_downgrade:
    - PHONE
    - EMAIL
    - STUDENT_ID
    - DORM
    - BUDGET
    - GRADE
    - WECHAT
```

**为什么不能用全局门槛**（实测数据，见 §11）：

| 类别 | P(RETAIN) 中位数 | 全局门槛 0.093 下的保留率 |
|---|---|---|
| API_KEY | 0.263 | **100.0%** ⚠️ |
| DORM / WECHAT / LOCATION | 0.240 / 0.233 / 0.153 | **100.0%** ⚠️ |
| ORG | 0.092 | 47.9% |
| PERSON_NAME | 0.051 | **6.7%** ⚠️ |
| EMAIL / PHONE / STUDENT_ID | 0.056 / 0.047 / 0.050 | **0.0%** ⚠️ |

> **API_KEY 是 level 4 硬禁止项，却被模型判为最该保留（100%）**——
> 这既说明硬约束（第一段）绝对不可省略，也说明模型对 RETAIN 的排序
> **与安全语义脱节**（详见 §11.3 的重训建议）。

> **关于"受限预算"的语义澄清**（见 §9 待确认项 ①）：
> 本设计**不引入"受限"这个新概念**，统一用 `level` 表达：
> - `level 4` → 硬禁止（`absolute_ban`：证件/银行卡/密钥/敏感属性）
> - `level 1~3` → 能否保留由「身份 max_level ∩ 接收方 max_level」判定
>
> 因此"预算 level 3 默认不保留"在当前配置下自然成立：`external_model.max_level = 2 < 3`，
> 预算对云端模型不可保留，效果上等于"禁止"。

### 3.2 必要性模型的输入/输出契约

**输入**（每片段一行特征，`build_feature_text` 扩展）：

```python
def build_feature_text_v2(seg, task_key, recipient_key, *,
                          task_description="", retain_preference="balanced",
                          already_aggregated=False) -> str:
    """v2 特征串。

    必需字段（用户需求）：
      片段类别 / 局部上下文 / 任务模板 / 接收方 / 列名 / 是否已本地聚合
    新增字段：
      任务描述 / 保留偏好
    """
    tokens = [
        "[CAT]"  + "|".join(sorted({s.category for s in seg.spans})),
        "[TASK]" + task_key,
        "[ROLE]" + rec_type,          # EXTERNAL_MODEL / VIEWER / EGRESS_TOOL
        "[TRUST]" + trust,            # low / medium / high
        "[COL]"  + "|".join(cols),
        "[N]"    + str(len(seg.spans)),
        "[CONF]" + f"{max_conf:.2f}",
        "[AGG]"  + ("1" if already_aggregated else "0"),   # ← 新增（用户要求）
        "[DESC]" + normalize(task_description)[:60],       # ← 新增（前端①）
        "[PREF]" + retain_preference,                      # ← 新增（前端②）
    ]
    return " ".join(tokens) + " [TEXT]" + seg.text[:120]
```

> ⚠️ **重要限制（如实说明）**：你已确认**沿用现有五分类模型**。现模型是
> `TfidfVectorizer(char_wb 2-4gram, min_df=1)`，词表在训练时固定，
> **`[AGG]` / `[DESC]` / `[PREF]` 三个新 token 对已训练模型是 OOV，实际不产生影响**。
>
> 因此过渡期采取**双轨**：
> - **特征位预留**：新 token 写进特征串，为将来重训做好准备（重训后即自动生效）；
> - **规则层兜底**：`[DESC]` 与 `[PREF]` 的作用**暂时由规则层实现**——
>   - `[PREF]` → 直接调节门槛（这在设计上本就是规则层职责，无需模型）；
>   - `[DESC]` → 关键词规则表（见下），命中则微调门槛。
>
> 这条限制直接决定了：**前端①的任务描述在当前模型下只能通过关键词规则生效**，
> 要让它真正进入模型语义，必须重训（建议列入后续计划）。

`[DESC]` 过渡期关键词规则（`m4_necessity/desc_rules.py`，新增）：
```python
DESC_KEYWORDS = {
    # 表达"只要结论/摘要" → 更多删除
    "mask_bias": ["不需要", "无需", "不必", "只要结论", "简要", "摘要",
                  "只关注任务", "不用讨论过程", "去掉过程"],
    # 表达"要完整信息" → 更多保留
    "keep_bias": ["完整", "详细", "全部", "务必保留", "原始", "逐条", "一一对应"],
}
# 命中 mask_bias → 门槛 × 1.15（更难保留）
# 命中 keep_bias → 门槛 × 0.85（更易保留）
```

**输出**：必要性分数 + 建议动作。

```python
@dataclass
class NecessityVerdict:
    score: float            # 0~1，越高越"该保留"
    advice: str             # keep | mask | pause
    threshold: float
    detail: Dict[str, float]   # 模型原始五动作概率
    reason: str
```

**五分类 → 必要性分数的映射**（`m4_necessity/necessity_verdict.py`，新增）：

```python
COST = {"DELETE": 0, "LOCAL_AGGREGATE": 1, "GENERALIZE": 2,
        "PSEUDONYMIZE": 3, "RETAIN": 5}

def to_verdict(scores: Dict[str, float], threshold: float) -> NecessityVerdict:
    """把五动作概率映射成「保留 vs 脱敏」的判定。

    必要性分数 = P(RETAIN)
    ---------------------
    刻意**不用**「期望披露代价」加权：
        expected = Σ P(a)·COST(a) / 5
    因为 PSEUDONYMIZE（代价 3）会算出 0.6 的高分，但它本质上属于**脱敏**
    而非保留 —— 用它会把"代号替换"误判成"可保留"。

    所以直接用 P(RETAIN)：五个概率和为 1，它本身就是"该片段应受控保留"的
    归一化度量，语义干净、可解释：「模型认为该片段应该原样保留的概率」。

    门槛校准（已实测，结论见 §11）
    -----------------------------
    实测 P(RETAIN) 分布极偏（segment 级 P50 仅 0.093），
    固定门槛 0.5 会让**保留率只有 0.8%** —— 正如风险预警所说，
    新流程会退化成旧的"全删"。

    但**按分位数校准还不够**：各类别的分布差异极大，用单一全局门槛会出现
    极端失衡（API_KEY 保留率 100%、人名只有 6.7%）。
    所以必须**按类别分层**校准：

        每类的门槛 = 该类别 P(RETAIN) 分布的分位数
          平衡        → 各类自身的 P50   （每类保留率 ≈ 50%）
          优先保留    → 门槛 × 0.75       （保留率升到 ≈ 70%）
          优先删除    → 门槛 × 1.25       （保留率降到 ≈ 30%）

    分层后实测每类保留率均回到 ~50%，类别间恢复可比（见 §11.2）。
    """
    p_keep = float(scores.get("RETAIN", 0.0))
    advice = "keep" if p_keep >= threshold else "mask"
    reason = (f"必要性={p_keep:.2f}"
              + ("，高于门槛，判定为任务所需" if advice == "keep"
                 else "，低于门槛，判定为非必要"))
    return NecessityVerdict(score=p_keep, advice=advice, threshold=threshold,
                            detail=scores, reason=reason)
```

### 3.3 决策三段重构

新增 `m3_decide/decision_v2.py`（**不改动现有 `decision.py`**，双路径并存）：

```python
def decide_all_v2(segments, task_key, recipient_key, identity_key, *,
                  task_description="", retain_preference="balanced",
                  field_preferences=None, necessity_scorer=None) -> List[DecisionV2]:
    ...
```

单片段决策逻辑：

```python
def decide_segment_v2(seg, task_key, recipient_key, identity_key, ctx) -> DecisionV2:
    cats = sorted({s.category for s in seg.spans})
    if not seg.spans:
        return DecisionV2(seg.seg_id, Action.RETAIN, cats,
                          route="no_sensitive_content", reason="该段无敏感信息")

    # ── ① 硬约束过滤（规则库只给"禁止"与"敏感级别"）─────────────
    hard = check_hard_constraints(seg, task_key, recipient_key, identity_key)
    if hard.pause:                                  # 低置信 + 高风险
        return DecisionV2(seg.seg_id, Action.PAUSE, cats, route="paused",
                          reason=hard.pause_reason)
    if hard.all_banned:                             # 全部片段都是 level 4 硬禁
        return _pick_masking_action(seg, cats, forced_banned=hard.banned,
                                    route="must_mask", reason=hard.reason)
    # 部分硬禁 → 这些类别直接进"必须脱敏"，其余走必要性判断
    ...

    # ── ② 必要性判断 ────────────────────────────────────────────
    verdicts = {}
    for cat in cats:
        fp = (field_preferences or {}).get(cat, "auto")
        if fp == "force_keep":
            verdicts[cat] = _forced_keep(cat)          # 跳过模型
        elif fp == "force_mask":
            verdicts[cat] = _forced_mask(cat)          # 跳过模型
        elif cat in hard.banned:
            verdicts[cat] = _forced_mask(cat, "级别4硬禁止")
        else:
            verdicts[cat] = necessity_verdict(seg, cat, ctx)   # 走模型

    if any(v.advice == "pause" for v in verdicts.values()):
        return DecisionV2(..., Action.PAUSE, route="paused", ...)

    keep_cats = [c for c, v in verdicts.items() if v.advice == "keep"]
    mask_cats = [c for c, v in verdicts.items() if v.advice == "mask"]

    # ── ③ 路径分流 ──────────────────────────────────────────────
    if mask_cats and not keep_cats:
        return _pick_masking_action(seg, mask_cats, route="must_mask", ...)

    if keep_cats and not mask_cats:
        return _retain_with_permission_check(seg, keep_cats, recipient_key,
                                             identity_key, ...)

    # ── 混合片段：**按类别分别处理**，不做整段统一 ──────────────────
    # 实测（§11.2）：分层门槛下混合片段的建议冲突率高达 40.6%，
    # 若"以更保守者为准、整段脱敏"，会连带把该保留的类别也脱敏掉
    # （如「负责人张明，电话138…」里的张明）。所以必须细粒度。
    #
    # 做法：为每个类别各出一个动作，交给转换层按区间分别执行。
    keep_actions = {}
    for cat in keep_cats:
        ok, _ = check_retain_permission(cat, identity_key, recipient_key)
        keep_actions[cat] = Action.RETAIN if ok else Action.PSEUDONYMIZE
    mask_actions = _masking_actions_for(seg, mask_cats, ...)   # 逐类别选最小代价
    return DecisionV2(
        seg_id=seg.seg_id,
        clip_actions={**keep_actions, **mask_actions},   # {类别: 动作}
        categories=cats,
        primary_action=_most_conservative(keep_actions, mask_actions),  # 展示用
        route="mixed_per_category",
        reason="；".join(f"{c}→{a.value}" for c, a in
                        {**keep_actions, **mask_actions}.items()),
        necessity=[verdicts[c] for c in cats],
    )
```

**细粒度的落点：转换层要支持「一个片段多个动作」**

现有 `apply_decisions` 是 `zip(segments, decisions)`（一段一动作）。v2 需要扩展：

```python
# m6_transform/anonymizer.py 新增（不改动现有 process_segment）
def process_segment_v2(seg, clip_actions, session_id, agg_items, mapping,
                       default_action=Action.RETAIN) -> str:
    """按类别分别应用动作：把片段切成「动作相同的连续区间」逐段处理。

    复用现有 process_segment 的单动作逻辑 —— 每个区间构造一个子 Segment
    （span 坐标平移到区间内），用该区间的动作套一次，拼接结果。
    """
    # 1) 逐字符标注动作（无 span 的字符用 default_action）
    char_act = [default_action] * len(seg.text)
    for s in seg.spans:
        a = clip_actions.get(s.category, default_action)
        for i in range(s.start - seg.start, min(s.end - seg.start, len(seg.text))):
            char_act[i] = a
    # 2) 合并连续相同动作 → runs = [(start, end, action), ...]
    # 3) 逐 run 构造子 Segment + 子 Decision，复用 process_segment
    ...
    return "".join(parts)
```

> **为什么这样设计**：`process_segment` 已经正确处理了删除/聚合/泛化/代号替换
> 四种动作的细节（含空标签清理、金额区间化等）。细粒度只需**把片段切成区间**
> 再复用同一套逻辑，**不必重写转换算法**，风险可控。

**示例效果**：

| 原文 | 全局保守方案（旧设计） | 按类别细粒度（新设计） |
|---|---|---|
| `负责人张明，电话13812345678` | `负责人某同学，电话***`（人名也丢了） | `负责人人员甲，电话`（张明保留为代号，电话删除） |
| `主办单位：绿野环保协会，联系人王芳` | `组织甲，人员甲`（机构名也代号化） | `绿野环保协会，人员甲`（机构名受控保留） |

`_retain_with_permission_check`（后端改动 ④ 的核心）：

```python
def _retain_with_permission_check(seg, keep_cats, recipient_key, identity_key,
                                  downgrade_action="PSEUDONYMIZE"):
    """受控保留必须过权限核对 —— 这是"同一信息对不同接收方差异化处理"的落点。

    有权限 → RETAIN（原样保留）
    无权限 → 降级：能代号替换的走 PSEUDONYMIZE，不能的继续走"必须脱敏"
    """
    allowed, denied = [], []
    for cat in keep_cats:
        ok, _ = check_retain_permission(cat, identity_key, recipient_key)
        (allowed if ok else denied).append(cat)

    # 全部有权限 → 直接受控保留
    if allowed and not denied:
        return DecisionV2(seg.seg_id, Action.RETAIN, keep_cats,
                          route="keep_to_retain",
                          reason=f"必要性={...}，且接收方有权查看 → 受控保留")

    # 部分/全部无权限 → 降级
    dn = set(rules()["retain_policy"]["non_pseudonymizable_on_downgrade"])
    if all(c in dn for c in denied):
        return _pick_masking_action(seg, denied, route="keep_downgraded",
                                    reason="必要性建议保留但无权查看，且不可代号化")
    return DecisionV2(seg.seg_id, Action.PSEUDONYMIZE, denied,
                      route="keep_downgraded",
                      reason=f"必要性建议保留，但接收方无权查看 {denied} → 降级为代号替换")
```

`check_retain_permission(cat, identity_key, recipient_key)`：
```python
# 复用现有硬约束的判定口径（constraints.check_hard 的 PERMISSION_LEVEL + RECEIVER_BAN）
max_level = min(identity_max_level(identity_key), recipients()[recipient_key]["max_level"])
return category_level(cat) <= max_level and cat not in recipients()[recipient_key]["forbidden"]
```

`_pick_masking_action`：在"必须脱敏"集合内选代价最小动作（沿用现有
`action_cost` + `feasible_actions` 逻辑，但**不接受 RETAIN 作为候选**）：

```python
MASKING_ACTIONS = [Action.DELETE, Action.LOCAL_AGGREGATE,
                   Action.GENERALIZE, Action.PSEUDONYMIZE]

def _pick_masking_action(seg, cats, *, route, reason, forced_banned=None):
    cands = [a for a in MASKING_ACTIONS
             if is_applicable(a, seg, cats)
             and passes_hard_constraints(a, seg, ..., forced_banned)]
    if not cands:
        return DecisionV2(..., Action.PAUSE, route="paused",
                          reason="必须脱敏但无任何可行动作 → 暂停外发")
    best = min(cands, key=lambda a: action_cost(a.value))
    return DecisionV2(seg.seg_id, best, cats, route=route, reason=...)
```

> **注意**：v2 里 `PAUSE` 有两处来源 —— ① 低置信高风险；② "必须脱敏"却无可行动作。
> 与现状一致，但第二处现在只可能在脱敏动作集合内发生。

### 3.4 开关与双路径并存

```python
# m3_decide/decision.py（保持不动）
# m3_decide/decision_v2.py（新增）

# 统一入口（m3_decide/__init__.py 或 pipeline.py 调用处）
def decide_all_dispatch(segments, task_key, recipient_key, identity_key, *,
                        mode="necessity_v2", **kwargs):
    if mode == "rule_v1":
        return decide_all(segments, task_key, recipient_key, identity_key,
                          necessity_scorer=kwargs.get("necessity_scorer"))
    return decide_all_v2(segments, task_key, recipient_key, identity_key, **kwargs)
```

`pipeline.py` / `eval/run_eval.py` 通过 `ShieldRequest.decision_mode` 切换，
**默认 `necessity_v2`**，评测脚本显式传 `rule_v1` 以复现历史基线。

---

## 4. 前端四项改动

### 4.1 「任务描述」输入框

| 项 | 内容 |
|---|---|
| 位置 | 左侧配置面板，「任务模板」`<select>` **下方** |
| 元素 | `<textarea id="taskDesc" rows="2" placeholder="例如：这次只关注任务分配，不需要讨论过程">` |
| 状态 | `state.taskDesc`（`app.js`） |
| 提交 | `payload().task_description` |
| 说明文案 | 小字提示：「描述会作为必要性判断的输入；当前模型下以关键词规则生效，重训后进入模型语义」 |

### 4.2 「保留偏好」选择器

| 项 | 内容 |
|---|---|
| 位置 | 「接收方」`<select>` **下方** |
| 元素 | `<select id="selRetainPref">`，选项：`prioritize_retain` 优先保留 / `balanced` 平衡（默认） / `prioritize_delete` 优先删除 |
| 默认 | `balanced` |
| 作用 | 后端 `retain_policy.threshold[pref]` 取门槛；前端在选中的选项旁显示当前门槛值（由 `/api/config` 下发），让用户看到实际影响 |

### 4.3 「字段级偏好」折叠面板

| 项 | 内容 |
|---|---|
| 位置 | 「保留偏好」**下方**，默认折叠 |
| 折叠控件 | `<details><summary>字段级偏好（可选）</summary>…</details>` |
| 内容 | **常用 6 类直接展示** + 其余收进「更多」子折叠 |
| 默认 | 全部 `auto`，不强制用户填写 |
| 状态 | `state.fieldPrefs = { "PERSON_NAME": "auto", ... }` |
| 提交 | `payload().field_preferences` |

**为什么只放 6 类**：14 个选项平铺会让用户无所适从、且大部分类别
（身份证/银行卡/密钥/敏感属性）是 level 4 硬禁、给用户开关只会造成"看起来能选、
实际无效"的误导。所以按**使用频率**分层：

```
字段级偏好（可选）                              ← 主折叠，默认收起
  姓名       [自动 ▾]      ← 会议纪要/活动统计最常需要保留
  手机号     [自动 ▾]
  邮箱       [自动 ▾]
  学号       [自动 ▾]
  机构       [自动 ▾]
  预算       [自动 ▾]
  ▸ 更多字段（地点 / 宿舍 / 成绩 / 微信号 / 身份证 / 银行卡 / 密钥 / 敏感属性）
       身份证 🔒[强制脱敏]   ← level 4 硬禁项：仅展示、置灰不可改
       ...
```

> 「更多」里的 level 4 类别（身份证/银行卡/密钥/敏感属性）三态选择器
> **固定为「强制脱敏」且置灰**，并标注 🔒，与「硬约束优先于用户偏好」保持一致。

**交互细节**：硬禁止项（level 4）的三态选择器旁标注 🔒，「强制保留」选项置灰不可选
（因为硬约束优先级高于用户偏好，避免给出"看似能选、实际无效"的误导）。

### 4.4 处理方案页：决策表 + 必要性解释

**决策表**改为三列（现有为四列）：

| 片段 | 动作 | 决策依据 |
|---|---|---|
| 负责人张明 | 受控保留 | 必要性=0.82（≥门槛0.50），会议纪要需要保留责任关系；接收方有权查看 → 无权限则降级代号替换 |

**必要性解释**（新增，位于决策表右侧或下方 `#necessityPanel`）：

```
必要性解释
┌─────────────────────────────────────────┐
│ 片段：负责人张明                          │
│ 必要性分数 0.82  ████████░░  门槛 0.50    │
│ 建议：保留                                │
│ 路径：可保留 → 权限核对通过 → 受控保留     │
│ 模型打分：RETAIN 0.74 / PSEUDONYMIZE 0.11 │
│           GENERALIZE 0.08 / DEL 0.02      │
└─────────────────────────────────────────┘
```

前端取数：`data.necessity[]`（§2.2 契约）。分数用进度条可视化，
门槛用竖线标记，让"为什么判保留/脱敏"一眼可见。

---

## 5. 数据流与模块依赖

```
┌─────────────────────── 前端（web/index.html + app.js）───────────────────────┐
│ 任务模板 ─┐                                                                  │
│ 任务描述 ─┤                                                                  │
│ 接收方   ─┼─→ payload() ─→ POST /api/preview | /api/run                      │
│ 保留偏好 ─┤        { task, task_description, recipient, retain_preference,   │
│ 字段级偏好┘          field_preferences, decision_mode, ... }                 │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────────────────┐
│ server.py                                                                     │
│   RunRequest（+4 字段）→ _build_request() → ShieldRequest（+4 字段）           │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼───────────────────────────────────────────┐
│ pipeline.py  run_pipeline()                                                   │
│  ① check_read / check_provide            （不变）                              │
│  ② detect_and_segment                    （不变，m2_detect）                   │
│  ③ decide_all_dispatch(mode=...)  ───────┐                                    │
│  ⑥ apply_decisions                       │                                    │
│  ⑦ EgressGateway                         │                                    │
│  ⑧ 三边界观测                             │                                    │
└──────────────────────────────────────────┼────────────────────────────────────┘
                                            │
        ┌───────────────────────────────────▼────────────────────────────────┐
        │ m3_decide/decision_v2.py                                            │
        │   ├─ check_hard_constraints()  ← config/rules.yaml(categories+hard) │
        │   ├─ necessity_verdict()       ← m4_necessity/necessity_verdict.py  │
        │   │      └─ necessity_scorer() ← m4_necessity/model.py（五分类）     │
        │   │             └─ build_feature_text_v2()（含 DESC/PREF/AGG 预留位）│
        │   │      └─ desc_rules.py（过渡期关键词兜底）                        │
        │   ├─ check_retain_permission() ← config/identities + recipients     │
        │   └─ _pick_masking_action()    ← config/rules.yaml(actions.cost)    │
        └─────────────────────────────────────────────────────────────────────┘
                                            │
        ┌───────────────────────────────────▼────────────────────────────────┐
        │ PipelineResult.necessity[]  →  前端「必要性解释」面板                 │
        └─────────────────────────────────────────────────────────────────────┘
```

**依赖关系要点**：

| 模块 | 依赖 | 被依赖 |
|---|---|---|
| `config/rules.yaml` | — | decision_v2（级别/硬禁/门槛/成本） |
| `m4_necessity/model.py` | sklearn、训练数据 | necessity_verdict（五分类打分） |
| `m4_necessity/necessity_verdict.py` | rules.yaml(threshold)、model | decision_v2（保留/脱敏判定） |
| `m4_necessity/desc_rules.py` | — | necessity_verdict（门槛微调） |
| `m3_decide/decision_v2.py` | constraints / necessity_verdict / identities+recipients / rules | pipeline |
| `pipeline.py` | decision_v2（或 decision v1） | server |
| `web/app.js` | `/api/config`(门槛/类别) | — |

---

## 6. 接口契约

### `GET /api/config` 新增返回

```json
{
  "retain_policy": {
    "threshold": {"prioritize_retain": 0.30, "balanced": 0.50, "prioritize_delete": 0.70},
    "options": [
      {"key": "prioritize_retain", "name": "优先保留"},
      {"key": "balanced", "name": "平衡"},
      {"key": "prioritize_delete", "name": "优先删除"}
    ]
  },
  "decision_modes": ["rule_v1", "necessity_v2"],
  "field_preference_options": [
    {"key": "auto", "name": "自动"},
    {"key": "force_keep", "name": "强制保留"},
    {"key": "force_mask", "name": "强制脱敏"}
  ],
  "categories": { "PERSON_NAME": {"name":"姓名","level":2,"hard_ban":false}, "...": {} }
}
```

### `POST /api/preview` / `POST /api/run` 请求体新增

```json
{
  "task": "meeting_minutes",
  "task_description": "这次只关注任务分配，不需要讨论过程",
  "recipient": "external_model",
  "retain_preference": "balanced",
  "field_preferences": {"PERSON_NAME": "force_keep", "PHONE": "auto"},
  "decision_mode": "necessity_v2"
}
```

---

## 7. 改造清单（文件级）

### 后端

| 文件 | 类型 | 内容 |
|---|---|---|
| `config/rules.yaml` | 改 | 新增 `retain_policy` 段 |
| `config/tasks.yaml` | 改 | `prefer` 标记 deprecated |
| `llm_shield/schema.py` | 改 | `ShieldRequest` +4 字段；`PipelineResult` +`necessity` |
| `llm_shield/m4_necessity/necessity_verdict.py` | **新增** | 五分类→必要性分数/建议 映射 + 门槛调节 |
| `llm_shield/m4_necessity/desc_rules.py` | **新增** | 任务描述关键词 → 门槛微调（过渡期） |
| `llm_shield/m4_necessity/model.py` | 改 | `build_feature_text_v2()`（预留 AGG/DESC/PREF 位） |
| `llm_shield/m3_decide/decision_v2.py` | **新增** | 三段决策 + 受控保留权限降级 |
| `llm_shield/m3_decide/decision.py` | 不动 | 保留 v1 路径 |
| `llm_shield/m6_transform/anonymizer.py` | 改 | 新增 `process_segment_v2()` 按区间细粒度处理（**复用** `process_segment`） |
| `llm_shield/pipeline.py` | 改 | 走 `decide_all_dispatch`，回填 `result.necessity` |
| `llm_shield/server.py` | 改 | `RunRequest` +4 字段；`/api/config` 下发门槛与选项 |
| `scripts/analyze_retain_distribution.py` | ✅ **已完成** | P(RETAIN) 分布分析（§11 的数据来源） |
| `scripts/calibrate_threshold.py` | **新增** | 按类别分位数校准，产出 `config/retain_thresholds.json` |
| `config/retain_thresholds.json` | **新增（生成物）** | 分层门槛表，由校准脚本产出 |

### 前端

| 文件 | 类型 | 内容 |
|---|---|---|
| `web/index.html` | 改 | 任务描述框、保留偏好选择器、字段级偏好折叠面板、必要性面板容器 |
| `web/app.js` | 改 | 4 处状态与提交；决策表改三列；渲染必要性解释 |
| `web/style.css` | 改 | 折叠面板、必要性分数条样式 |

### 测试

| 文件 | 类型 | 内容 |
|---|---|---|
| `tests/test_decision_v2.py` | **新增** | 三段决策、权限降级、字段级偏好旁路、无方案→PAUSE |
| `tests/test_necessity_verdict.py` | **新增** | 五分类→三分映射、门槛调节、DESC 关键词 |
| `tests/test_smoke.py` | 不动 | v1 路径回归（38 项） |
| `eval/run_ablation.py` | 改 | 新增 `rule_v1` vs `necessity_v2` 对照 |

---

## 8. 风险与验证方案

| 风险 | 影响 | 缓解 |
|---|---|---|
| **门槛未校准** → 新流程退化成"全删"或"全保留" | 高 | 先跑 `calibrate_threshold.py`，用分位数定档；测试断言"平衡模式下保留率落在 30%~70%" |
| **任务描述进不了模型**（旧模型 OOV） | 中 | 已如实说明；过渡期用关键词规则，重训后排期 |
| **P(RETAIN) 分布偏移** → 门槛失效 | 中 | 校准脚本写进 CI 流程；`/api/config` 下发门槛供前端展示 |
| **权限降级引入泄露** | 高 | 降级只降为 PSEUDONYMIZE（不降为 RETAIN）；不可代号化类别继续走脱敏；三边界观测仍兜底 |
| **双路径代码分叉** | 中 | v1/v2 完全独立文件，靠 `decision_mode` 切换；`run_eval` 同时跑两者做对照 |
| **硬约束被用户偏好绕过** | 高 | 硬约束**永远优先**于字段级偏好；level 4 的"强制保留"选项在 UI 置灰 |

**验证清单**（实现完成后必须全绿）：

1. `tests/test_smoke.py` 38 项（v1 路径无回归）
2. `tests/test_skweak_labels.py` 43 项 / `test_ner_align.py` 6 项（不受影响）
3. `tests/test_decision_v2.py`（新增）—— 覆盖：level 4 硬禁、低置信 PAUSE、
   字段级强制保留/脱敏旁路、**权限不足降级为代号替换**、必须脱敏无方案→PAUSE、
   同一片段对不同接收方产出不同动作（差异化处理）
4. `eval/run_eval.py --decision-mode rule_v1` 复现历史基线
5. `eval/run_ablation.py` 新旧决策层对照，**必要性消融必须产生差异**
   （v2 下关掉必要性模型，保留/脱敏判定全塌成规则，指标应显著变化）

---

## 9. 待确认问题（已按反馈收敛）

| # | 问题 | 结论 |
|---|---|---|
| ① | **"受限预算"** 是独立概念，还是就是 `level 3 + 接收方无权限`？ | ✅ 用 level 统一表达，不引入新概念（§3.1 末） |
| ② | 字段级偏好面板放几个字段？ | ✅ **改为常用 6 类 + 「更多」收纳**（§4.3） |
| ③ | 混合片段怎么处理？ | ✅ **改为按类别细粒度**，不做整段统一（§3.3）——实测冲突率 40.6%，保守方案损失不可接受 |
| ④ | 保留偏好/字段级偏好是否随身份变化？ | ✅ 固定默认（平衡 / 全 auto），不随身份变 |
| ⑤ | 校准门槛用语料？ | ✅ `cases_dev.jsonl` 210 条（与测试集隔离），**按类别分层**校准 |
| ⑥ | **是否需要重训必要性模型？** | ⚠️ **建议重训**（数据支持，见 §11.3）——但可作为后续工作，先用分层门槛过渡 |

---

## 10. 预期效果

| 维度 | 现状 v1 | 新设计 v2 |
|---|---|---|
| 必要性模型的角色 | 同代价 tie-break（**实测从不生效**） | 决定片段走「保留」还是「脱敏」通道 |
| 规则库职责 | 预设动作（`prefer`）+ 任务破坏规则 | 只定义「禁止」与「敏感级别」 |
| 差异化处理 | 靠 `disclosure_cost` 间接实现 | 显式的「受控保留 + 权限降级」 |
| 用户可控性 | 仅"处理哪些类别" | + 任务描述 / 保留偏好 / 字段级偏好 |
| 可解释性 | 决策依据为规则文本 | 必要性分数 + 门槛 + 路径 + 模型打分 |

---

## 11. 实测验证（`scripts/analyze_retain_distribution.py`）

> 针对反馈中的**风险一（门槛校准）**与**风险三（混合片段）**，
> 已在真实语料上跑完验证。脚本可复跑：`python scripts/analyze_retain_distribution.py`
> 数据源：`data/generated/cases_dev.jsonl`（210 条，与测试集隔离），
> 参与统计片段 **1910** 个，其中含多类别的 **1120** 个（58.6%）。

### 11.1 风险一被证实：P(RETAIN) 分布极偏

| 口径 | P10 | P30 | P50 | P70 | P90 | 均值 |
|---|---|---|---|---|---|---|
| segment 级 | 0.055 | 0.066 | **0.093** | 0.124 | 0.239 | 0.121 |
| span 级 | 0.029 | 0.046 | 0.053 | 0.066 | 0.153 | 0.078 |

不同门槛下的实际保留率：

| 门槛方案 | 保留率 |
|---|---|
| 固定 0.50 | **0.8%** ← 正如风险预警，退化为"全删" |
| 固定 0.30 | 5.2% |
| 固定 0.10 | 40.8% |
| 分位数 P50（=0.093） | **50.0%** ✓ |
| 分位数 P70 / P30 | 30.1% / 70.0% ✓ |

**分位数校准有效**，保留率可精确控制在设定分位。但门槛绝对值极低（0.093），
说明 **P(RETAIN) 的绝对数值没有语义、只有相对排序有意义**。

### 11.2 全局门槛不可用 → 必须分层（本次设计修正）

各类别的 P(RETAIN) 分布差异极大，用**全局门槛**会严重失衡：

| 类别 | P50 | 全局门槛(0.093) 下保留率 |
|---|---|---|
| API_KEY | 0.263 | **100.0%** ⚠️ |
| DORM | 0.240 | **100.0%** ⚠️ |
| WECHAT | 0.233 | **100.0%** ⚠️ |
| LOCATION | 0.153 | **100.0%** |
| ORG | 0.092 | 47.9% |
| PERSON_NAME | 0.051 | **6.7%** ⚠️ |
| EMAIL | 0.056 | **0.0%** ⚠️ |
| STUDENT_ID | 0.050 | **0.0%** ⚠️ |
| PHONE | 0.047 | **0.0%** ⚠️ |
| BUDGET | 0.026 | 19.9% |

**结论：改为按类别分层门槛**。分层后各类保留率：

```
API_KEY 50.0% | BUDGET 50.0% | DORM 50.0% | EMAIL 50.0% | LOCATION 51.9%
ORG 50.1% | PERSON_NAME 50.0% | PHONE 50.0% | STUDENT_ID 50.0% | WECHAT 50.0%
```

### 11.3 风险三被证实：混合片段冲突率高达 40.6%

| 门槛方案 | 混合片段建议冲突率 |
|---|---|
| 全局门槛 P50 | 14.9% |
| **分层门槛** | **40.6%** |

分层门槛下，近一半混合片段内部"该保留"与"该脱敏"并存。
若按原设计"以更保守者为准、整段脱敏"，会连带丢掉 40% 该保留的内容。
**结论：改为按类别细粒度处理**（§3.3）。

### 11.4 关于重训：模型对 RETAIN 的排序与安全语义脱节

实测各类别 P(RETAIN) 均值排序：

```
API_KEY 0.264 > DORM 0.261 > WECHAT 0.234 > ORG 0.163 > LOCATION 0.146
             > PERSON_NAME 0.056 > EMAIL 0.056 > STUDENT_ID 0.050
             > PHONE 0.045 > BUDGET 0.045
```

两个明显问题：

1. **API_KEY（level 4 硬禁止）得分最高** —— 模型认为"最该保留"的恰恰是最不该保留的。
   这印证了硬约束（第一段）绝对不可省略。
2. **PERSON_NAME 仅 0.056，几乎垫底** —— 但会议纪要/活动统计恰恰需要保留责任关系。
   模型没有学到"任务必要性"，更像是复现了**训练标签里的动作分布**
   （训练时人名的首选动作是 `LOCAL_AGGREGATE`/`PSEUDONYMIZE`，都不是 `RETAIN`）。

**建议**：
- **短期（本次实现）**：分层门槛 + 硬约束兜底，可跑通且有实际区分度；
- **中期（建议排期）**：重训必要性模型，让它真正学「任务必要性」而非「动作分布」——
  做法是把训练标签从"动作"改为"该片段是否为任务所需"，并引入任务描述特征。
  这一条建议直接写进申报书的「后续工作」。

### 11.5 对原设计的修正汇总

| 原设计 | 实测后修正 | 依据 |
|---|---|---|
| 单一全局门槛 + 分位数校准 | **按类别分层门槛** | §11.2 全局门槛导致 100%/0% 极端失衡 |
| 混合片段"以更保守者为准" | **按类别细粒度处理** | §11.3 冲突率 40.6%，保守方案损失过大 |
| 字段级偏好放全部 14 类 | **常用 6 类 + 「更多」收纳** | 用户反馈（风险四） |
| 门槛由 `calibrate_threshold.py` 分位数校准 | 同左，但**按类别**输出 `retain_thresholds.json` | §11.1 分位数校准有效 |

---

> 设计文档到此为止。**§9 的 6 个问题已全部收敛**（①②③④⑤ 已定，⑥ 建议重训但可后置）。
> 若认可，我按 §7 的改造清单进入实现，并按 §8 的验证清单逐项跑通 ——
> 其中最关键的一条：**v2 下关掉必要性模型，指标必须显著变化**。
