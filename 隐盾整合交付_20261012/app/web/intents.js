"use strict";
/* ============================================================
   隐盾 · 任务目录（前端意图层）
   ============================================================
   为什么要有这一层
   ----------------
   后端 `config/tasks.yaml` 只有 3 个任务模板，决策模型
   （models/necessity_action.joblib）、权限表、外发检查、合成训练数据
   全部绑死在这 3 个键上：

     meeting_minutes  会议纪要与任务分配
     activity_stats   活动统计与总结
     project_intro    项目对外介绍

   直接给用户看这 3 个名字，问题是「太宏大、不知道该选哪一个」：
   「活动统计与总结」到底是统计人数，还是写推文？用户无法判断。

   本文件因此只做一件事：把 3 个模板展开成 12 个**说人话的具体意图**。
   每个意图都：
     · label       用户一眼能对号入座的动作短语（不是名词堆）
     · example     一句真实场景示例，选择时就看得见
     · prompts     空态里可直接点用的问法，避免用户对着空输入框发呆
     · placeholder 该任务真正需要保留什么，写进「额外处理要求」的提示
     · task        映射回后端的 3 个模板键之一

   ⚠ 纪律：intents 只覆盖 `task`（模板键）与展示文案。
   它**不预填** `task_description`。留空时后端会用模板自身的 desc 兜底
   （见 m4_necessity/model.py 的 `[TASK_TEXT]`），这正是训练数据里的默认形态；
   一旦前端替用户填了内容，就等于在未被验证的输入分布上驱动决策模型。
   提示只走 placeholder，改不改由用户决定。
   ============================================================ */

/* 分组顺序：按校园场景里出现的频率排，会议最常用 */
const INTENT_GROUPS = ["会议与协作", "活动与数据", "对外与宣传"];

const INTENTS = [
  /* ---------------- 会议与协作 → meeting_minutes ----------------
     模板要求保留 PERSON_ROLE / TASK_ITEM / DEADLINE，
     姓名按 prefer 走 PSEUDONYMIZE（会话内稳定代号），
     联系方式、身份证号、敏感属性一律不外发。 */
  {
    id: "mm_minutes",
    group: "会议与协作",
    task: "meeting_minutes",
    label: "整理会议纪要",
    example: "把例会记录按议题整理成一份可存档的纪要",
    placeholder: "例如：保留负责人、事项和截止时间的对应关系",
    prompts: [
      "把这份会议记录整理成纪要，按议题分段，并列出结论",
      "总结本次会议的主要结论和下一步安排",
      "把会议记录里的讨论过程去掉，只留最终决定"
    ]
  },
  {
    id: "mm_tasks",
    group: "会议与协作",
    task: "meeting_minutes",
    label: "提取待办与负责人",
    example: "列出谁负责哪件事、什么时候交",
    placeholder: "例如：每条待办都要有责任人和截止时间",
    prompts: [
      "列出每个负责人的具体任务和截止时间",
      "把待办整理成清单，标注负责人和期限",
      "指出会议记录里没有明确负责人的事项"
    ]
  },
  {
    id: "mm_notice",
    group: "会议与协作",
    task: "meeting_minutes",
    label: "写会后通知",
    example: "把会议结论改写成发给成员的通知",
    placeholder: "例如：语气正式一点，只写需要大家执行的事",
    prompts: [
      "把会议结论改写成一条发给全体成员的通知",
      "用简短口语写一段会后提醒，突出时间地点",
      "把待办事项改写成每个人能看懂的行动清单"
    ]
  },
  {
    id: "mm_summary",
    group: "会议与协作",
    task: "meeting_minutes",
    label: "只做要点摘要",
    example: "压缩成几条要点，不要细节和过程",
    placeholder: "例如：最多 5 条，每条不超过一行",
    prompts: [
      "用 5 条要点总结这次会议，每条不超过一行",
      "只保留结论和分歧点，去掉过程讨论",
      "把会议记录压缩成 200 字以内的摘要"
    ]
  },

  /* ---------------- 活动与数据 → activity_stats ----------------
     模板要求保留 EVENT_NAME / COUNT / DATE / PUBLIC_FACT，
     手机号、邮箱、微信、学号、身份证号一律不外发，
     姓名走 LOCAL_AGGREGATE（本地汇总，不出个人明细）。 */
  {
    id: "as_count",
    group: "活动与数据",
    task: "activity_stats",
    label: "统计参与人数",
    example: "按部门、年级或批次汇总人数",
    placeholder: "例如：只统计人数，不要出现任何个人明细",
    prompts: [
      "统计这次活动的参与人数，并按部门汇总",
      "按年级统计报名人数，给出每类的人数",
      "算一下总人数和各部门占比"
    ]
  },
  {
    id: "as_report",
    group: "活动与数据",
    task: "activity_stats",
    label: "写活动总结文案",
    example: "生成一段可以对外发布的总结",
    placeholder: "例如：保留活动名称、时间和人数，语气积极",
    prompts: [
      "根据签到表生成一份活动总结文案",
      "写一段活动回顾，用于公众号推送",
      "把这次活动写成 300 字的总结，突出成果"
    ]
  },
  {
    id: "as_analyze",
    group: "活动与数据",
    task: "activity_stats",
    label: "分析报名情况",
    example: "说明参与情况、冷热环节和缺口",
    placeholder: "例如：指出参与人数偏少的环节，并给出可能原因",
    prompts: [
      "分析报名数据，说明本次活动整体参与情况",
      "指出报名人数偏少的环节，并分析可能原因",
      "对比不同部门的参与率，说明差异"
    ]
  },
  {
    id: "as_improve",
    group: "活动与数据",
    task: "activity_stats",
    label: "给出改进建议",
    example: "基于这次的数据，提下次怎么办更好",
    placeholder: "例如：建议要具体可执行，不要空话",
    prompts: [
      "根据这次活动的参与数据，给出下次活动的改进建议",
      "指出这次活动组织上的问题，并给出对应做法",
      "从时间安排和宣传方式两方面提三条改进建议"
    ]
  },

  /* ---------------- 对外与宣传 → project_intro ----------------
     模板要求保留 PROJECT_NAME / PUBLIC_FACT / ORG_PUBLIC，
     预算、联系方式、学号、身份证号、敏感属性一律不外发，
     姓名走 GENERALIZE（改成「负责人」这类泛称），地点降精度。 */
  {
    id: "pi_intro",
    group: "对外与宣传",
    task: "project_intro",
    label: "写项目对外介绍",
    example: "把计划书改写成可公开的项目简介",
    placeholder: "例如：保留项目名称和已获准公开的事实，去掉预算",
    prompts: [
      "把项目计划书改写成一段对外介绍文案",
      "写一段 200 字的项目简介，用于对外展示",
      "把项目背景、目标和成果整理成对外介绍"
    ]
  },
  {
    id: "pi_highlights",
    group: "对外与宣传",
    task: "project_intro",
    label: "提炼项目亮点",
    example: "挑出最值得对外讲的几个点",
    placeholder: "例如：只要可对外公开的内容，不要内部数据",
    prompts: [
      "提炼这个项目的核心亮点，用于对外宣传",
      "列出三个最值得宣传的点，各配一句话说明",
      "从项目材料里找出最有说服力的成果"
    ]
  },
  {
    id: "pi_plain",
    group: "对外与宣传",
    task: "project_intro",
    label: "改写成通俗版本",
    example: "面向非专业读者，去掉术语",
    placeholder: "例如：不要出现技术术语，句子短一点",
    prompts: [
      "将项目技术细节改写为面向非专业读者的简介",
      "用大白话解释这个项目在做什么，不要术语",
      "把这段项目介绍改写成高中生也能看懂的样子"
    ]
  },
  {
    id: "pi_faq",
    group: "对外与宣传",
    task: "project_intro",
    label: "生成项目问答",
    example: "把项目信息整理成常见问题",
    placeholder: "例如：问题要像真的有人会问，回答不超过三句",
    prompts: [
      "把这个项目的信息整理成 5 个常见问题及答案",
      "用问答形式介绍这个项目，问题由浅入深",
      "列出资方最可能问的问题，并给出简短回答"
    ]
  }
];

/* 按 id 取意图；找不到时回落到第一个，保证 UI 永远有有效状态 */
function intentById(id) {
  return INTENTS.find(item => item.id === id) || INTENTS[0];
}

/* 按分组归拢，顺序遵循 INTENT_GROUPS */
function intentsByGroup() {
  return INTENT_GROUPS
    .map(group => ({ group, items: INTENTS.filter(item => item.group === group) }))
    .filter(section => section.items.length > 0);
}

/* 关键词过滤：标签、示例、问法、后端模板名一起匹配 */
function matchIntents(query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return INTENTS;
  return INTENTS.filter(item => {
    const haystack = [item.label, item.example, item.group, item.task, ...item.prompts]
      .join(" ").toLowerCase();
    return haystack.includes(q);
  });
}
