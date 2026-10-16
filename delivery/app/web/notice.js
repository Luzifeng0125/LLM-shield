"use strict";
const byId = id => document.getElementById(id);
const categoryNames = {PERSON_NAME: "姓名", STUDENT_ID: "学号", PHONE: "电话", EMAIL: "邮箱", ORG: "机构", LOCATION: "地点", DORM: "宿舍"};
let serviceReady = false;
let reviewVersion = 0;
let reviewController;

async function post(path, body, signal) {
  const response = await fetch(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "输入不符合要求，请检查内容后重试。");
  return result;
}

function clearReview() {
  reviewVersion++;
  if (reviewController) reviewController.abort();
  byId("reviewRows").replaceChildren();
  byId("reviewTable").hidden = true;
  byId("reviewStatus").textContent = "";
  byId("reviewButton").disabled = false;
}
byId("roster").addEventListener("input", clearReview);
byId("identity").addEventListener("change", clearReview);
byId("clearRoster").addEventListener("click", () => { byId("roster").value = ""; clearReview(); });

byId("reviewForm").addEventListener("submit", async event => {
  event.preventDefault();
  clearReview();
  const version = reviewVersion;
  reviewController = new AbortController();
  byId("reviewButton").disabled = true;
  byId("reviewStatus").textContent = "正在本机识别…";
  try {
    const result = await post("/api/notice/review", {identity: byId("identity").value, text: byId("roster").value}, reviewController.signal);
    if (version !== reviewVersion) return;
    for (const span of result.spans) {
      const row = document.createElement("tr");
      for (const value of [categoryNames[span.category] || span.category, span.text, `${span.start + 1}–${span.end}`]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      byId("reviewRows").append(row);
    }
    byId("reviewTable").hidden = !result.spans.length;
    byId("reviewStatus").textContent = `本机识别到 ${result.spans.length} 个字段。${result.note}`;
  } catch (error) {
    if (version === reviewVersion && error.name !== "AbortError") byId("reviewStatus").textContent = error.message;
  } finally {
    if (version === reviewVersion) byId("reviewButton").disabled = false;
  }
});

byId("draftForm").addEventListener("submit", async event => {
  event.preventDefault();
  if (!serviceReady) return;
  const items = [...document.querySelectorAll('input[name="item"]:checked')].map(input => input.value);
  if (!items.length) { byId("draftStatus").textContent = "请至少选择一个通知事项。"; return; }
  byId("draftButton").disabled = true;
  byId("draft").textContent = byId("outgoing").textContent = "";
  byId("outgoingDetails").hidden = true;
  byId("draftStatus").textContent = "正在检查活动概要并生成草稿…";
  try {
    // Deliberately constructed from these three fields. Never serialize either
    // form, the roster textarea, local recognition results, or chat history.
    const body = {identity: byId("identity").value, activity_name: byId("activityName").value, items};
    const result = await post("/api/notice/draft", body);
    if (!result.ok || result.paused) throw new Error(result.pause_reason || result.access_reason || "生成已暂停，请检查活动概要。");
    if (!result.display_text) throw new Error("回复未通过展示检查，未显示草稿。");
    byId("outgoing").textContent = result.sanitized_text;
    byId("outgoingDetails").hidden = false;
    byId("draft").textContent = result.display_text;
    byId("draftStatus").textContent = "草稿已生成，尚未发送给任何参与者。";
  } catch (error) { byId("draftStatus").textContent = error.message; }
  finally { byId("draftButton").disabled = !serviceReady; }
});

fetch("/api/config").then(async response => {
  if (!response.ok) throw new Error("读取服务状态失败");
  return response.json();
}).then(config => {
  for (const [key, info] of Object.entries(config.identities)) {
    const option = document.createElement("option"); option.value = key; option.textContent = info.name;
    byId("identity").append(option);
  }
  byId("identity").value = "student_leader";
  const mock = config.models.llm.mode === "mock";
  byId("mode").textContent = mock ? "本次使用本地模拟回复，不调用外部模型。" : "生成时将把右侧活动概要提交给已配置的生成服务。";
  serviceReady = config.models.necessity_available;
  byId("draftButton").disabled = !serviceReady;
  if (!serviceReady) byId("draftStatus").textContent = "本地动作模型不可用，已暂停生成。";
}).catch(() => { byId("mode").textContent = "本机服务暂不可用，请刷新重试。"; });
