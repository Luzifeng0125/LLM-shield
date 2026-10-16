"use strict";
/* ============================================================
   隐盾 · 身份展示层
   ============================================================
   用户反馈：「身份之间的区别是什么不明确」。

   问题出在数据来源：后端 `config/identities.yaml` 里的 `desc`
   描述的是**这个人是谁**（「社团/学生会负责人」），
   而不是**这个身份能做什么、和别的身份差在哪**。
   而真正决定差别的三个字段是：

     readable      能读哪些材料
     can_send_to   能发给谁（其中 external_model = 能不能用云端模型）
     max_level     可提供的最高敏感级别

   但 `/api/config` 只回传 `name / desc / max_level`（见 llm_shield/server.py），
   `readable` 与 `can_send_to` 不出网。后端本轮不动，所以这里用一张
   **前端展示表**把差别写成一句人话。

   ⚠ 纪律：本表必须与 `config/identities.yaml` 保持一致。
     它不是权限判断（权限一律由后端裁决，前端这张表只影响文案），
     但文案说错了会误导用户，所以 `uishot.js` 里有断言：
     本表的键集合必须与 `/api/config` 返回的身份键集合**完全相同**，
     后端增删身份而忘了改这里，会立刻失败。

   对应 yaml 的三个身份（照抄，勿凭印象改）：
     student_leader  readable: activity_roster, meeting_minutes, project_plan, uploaded
                     can_send_to: external_model, viewer_teacher, viewer_peer,
                                  egress_tool_public, egress_tool_internal
                     max_level: 3   can_restore: true
     course_member   readable: meeting_minutes, uploaded
                     can_send_to: external_model, viewer_peer
                     max_level: 2   can_restore: false
     external_partner readable: project_intro_draft, uploaded
                     can_send_to: egress_tool_public
                     max_level: 1   can_restore: false
   ============================================================ */

const IDENTITY_DISPLAY = {
  /* 唯一能用全部材料、也是唯一能发给老师和内部工具的身份 */
  student_leader: {
    tag: "权限最全",
    diff: "能读活动名单、会议记录、项目计划，可以调用云端模型"
  },
  /* 少了活动名单与项目计划 —— 这是和上一个身份最关键的区别 */
  course_member: {
    tag: "课程限定",
    diff: "只能读课程会议记录，读不到活动名单和项目计划"
  },
  /* 唯一不能调用云端模型的身份，只能产出公开材料 */
  external_partner: {
    tag: "仅公开材料",
    diff: "只能读已获准公开的项目稿，不调用云端模型"
  }
};

/* 取某个身份的展示信息；后端出现未登记的身份时给一个安全的兜底，
   绝不显示 undefined，也不假装知道它的权限。 */
function identityDisplay(key) {
  return IDENTITY_DISPLAY[key] || {
    tag: "未登记",
    diff: "这个身份的权限范围尚未在前端登记，请以后端配置为准"
  };
}
