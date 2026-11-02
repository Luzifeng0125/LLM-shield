"""把 31 条空白盲标收成可单独拿走的文件夹。不加载模型，不填写动作。"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "03_数据与人工复核" / "校园必要性盲标_20261102"
DST = ROOT / "03_数据与人工复核" / "校园必要性盲标包_20261102"
ZIP = ROOT / "03_数据与人工复核" / "校园必要性盲标包_20261102.zip"
CATEGORIES = {
    "PERSON_NAME": "人名",
    "ORG": "机构",
    "LOCATION": "地点",
    "PHONE": "电话",
    "EMAIL": "邮箱",
    "DORM": "宿舍",
    "BUDGET": "金额",
    "GRADE": "成绩",
    "STUDENT_ID": "学号",
    "BANK_CARD": "银行卡",
    "SENSITIVE_ATTR": "敏感个人情况",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_documents() -> list[dict]:
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    documents = []
    for item in manifest["files"]:
        path = SRC / item["file"]
        if sha256(path) != item["sha256"]:
            raise SystemExit(f"{item['file']} 已偏离空白清单")
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("label_status") != "unlabeled" or document.get("model_screened") is not False:
            raise SystemExit(f"{item['file']} 不是空白材料")
        for unit in document["units"]:
            if unit["annotation"]["canonical_action"] or unit["annotation"]["required_facts"] or unit["annotation"]["notes"]:
                raise SystemExit(f"{unit['unit_id']} 已有填写内容")
            if document["text"][unit["start"]:unit["end"]] != unit["quote"]:
                raise SystemExit(f"{unit['unit_id']} 片段和位置不一致")
        document["_file"] = item["file"]
        document["_sha256"] = item["sha256"]
        documents.append(document)
    if sum(len(document["units"]) for document in documents) != 31:
        raise SystemExit("条目不是 31")
    return documents


def write_questions(documents: list[dict]) -> None:
    target = DST / "题目"
    target.mkdir(parents=True, exist_ok=True)
    for document in documents:
        source = SRC / document["_file"]
        destination = target / document["_file"]
        destination.write_bytes(source.read_bytes())
        if sha256(destination) != document["_sha256"]:
            raise SystemExit(f"{document['_file']} 复制后哈希变了")


def write_overview(documents: list[dict]) -> None:
    lines = [
        "# 题目一览",
        "",
        "共 12 篇、31 条。这里只列材料，动作留空。请填在 `人工盲标表.csv`、`打开题目.html`，或 `返还/` 里的 JSON 副本。不要把动作写回本文件，也不要改 `题目/` 里的空白原件。",
        "",
    ]
    for document in documents:
        lines.append(f"## {document['document_id']} {document['workflow_name']}")
        lines.append("")
        lines.append(document["text"])
        lines.append("")
        lines.append(f"要求：{document['user_task']}")
        lines.append("")
        for unit in document["units"]:
            lines.append(
                f"- {unit['unit_id']}｜{unit['quote']}｜{CATEGORIES.get(unit['category'], unit['category'])}"
                f" {unit['category']}｜{unit['boundary_name']}｜{unit['recipient_name']}｜{unit['identity_name']}"
            )
        lines.append("")
    (DST / "题目一览.md").write_text("\n".join(lines), encoding="utf-8")


def write_parse(documents: list[dict]) -> None:
    lines = [
        "# 题目解析",
        "",
        "每条已经划好片段。位置是原文里的字符区间，从 0 开始，含起始、不含结束。下面用原文切片核对过，片段和区间一致。",
        "",
        "类别已经给定，这次不用重新判断某段文字属于哪一类。要判断的是：面对这个任务和这个接收方，该片段怎么处理。",
        "",
    ]
    for document in documents:
        lines.append(f"## {document['document_id']} {document['workflow_name']}")
        lines.append("")
        lines.append(f"原文：{document['text']}")
        lines.append("")
        lines.append(f"用户要求：{document['user_task']}")
        lines.append("")
        lines.append("| 编号 | 片段 | 位置 | 类别 | 边界 | 接收方 | 身份 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for unit in document["units"]:
            lines.append(
                f"| {unit['unit_id']} | {unit['quote']} | {unit['start']}–{unit['end']} | "
                f"{CATEGORIES.get(unit['category'], unit['category'])} `{unit['category']}` | "
                f"{unit['boundary_name']} | {unit['recipient_name']} | {unit['identity_name']} |"
            )
        lines.append("")
    (DST / "题目解析.md").write_text("\n".join(lines), encoding="utf-8")


def write_sheet(documents: list[dict]) -> None:
    path = DST / "人工盲标表.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "编号", "原文", "片段", "类别", "边界", "接收方", "身份", "用户任务", "动作", "必要事实", "备注",
        ])
        writer.writeheader()
        for document in documents:
            for unit in document["units"]:
                writer.writerow({
                    "编号": unit["unit_id"],
                    "原文": document["text"],
                    "片段": unit["quote"],
                    "类别": unit["category"],
                    "边界": unit["boundary_name"],
                    "接收方": unit["recipient_name"],
                    "身份": unit["identity_name"],
                    "用户任务": unit["user_task"],
                    "动作": "",
                    "必要事实": "",
                    "备注": "",
                })


def write_html(documents: list[dict]) -> None:
    cards = []
    for document in documents:
        units = []
        for unit in document["units"]:
            before = html.escape(document["text"][:unit["start"]])
            quote = html.escape(unit["quote"])
            after = html.escape(document["text"][unit["end"]:])
            units.append(f"""
            <article class="unit" data-id="{html.escape(unit['unit_id'])}">
              <h3>{html.escape(unit['unit_id'])}</h3>
              <p class="sentence">{before}<mark>{quote}</mark>{after}</p>
              <dl>
                <div><dt>片段</dt><dd>{quote}</dd></div>
                <div><dt>位置</dt><dd>{unit['start']}–{unit['end']}</dd></div>
                <div><dt>类别</dt><dd>{html.escape(CATEGORIES.get(unit['category'], unit['category']))} {html.escape(unit['category'])}</dd></div>
                <div><dt>边界</dt><dd>{html.escape(unit['boundary_name'])}</dd></div>
                <div><dt>接收方</dt><dd>{html.escape(unit['recipient_name'])}</dd></div>
                <div><dt>身份</dt><dd>{html.escape(unit['identity_name'])}</dd></div>
                <div><dt>要求</dt><dd>{html.escape(unit['user_task'])}</dd></div>
              </dl>
              <label>动作
                <select name="action">
                  <option value="" selected>请选择</option>
                  <option>DELETE</option>
                  <option>LOCAL_AGGREGATE</option>
                  <option>GENERALIZE</option>
                  <option>PSEUDONYMIZE</option>
                  <option>RETAIN</option>
                  <option>PAUSE</option>
                </select>
              </label>
              <label>必要事实<textarea name="facts" rows="2"></textarea></label>
              <label>备注<textarea name="notes" rows="2"></textarea></label>
            </article>""")
        cards.append(f"""
        <section>
          <h2>{html.escape(document['document_id'])} {html.escape(document['workflow_name'])}</h2>
          <p class="source">{html.escape(document['text'])}</p>
          {''.join(units)}
        </section>""")
    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>31 条校园必要性盲标</title>
<style>
body {{ margin: 0; font-family: "Segoe UI", "PingFang SC", sans-serif; background: #f6f4ef; color: #1d1c19; }}
main {{ max-width: 880px; margin: 0 auto; padding: 32px 20px 80px; }}
h1 {{ font-size: 28px; margin-bottom: 8px; }}
h2 {{ margin: 36px 0 8px; font-size: 20px; }}
.note, .source {{ line-height: 1.7; }}
.unit {{ background: white; border: 1px solid #e2ddd4; border-radius: 12px; padding: 16px 18px; margin: 14px 0; }}
.sentence {{ font-size: 18px; line-height: 1.8; }}
mark {{ background: #ffe08a; padding: 0 2px; }}
dl {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 18px; margin: 0 0 12px; }}
dt {{ color: #6d675e; font-size: 12px; }}
dd {{ margin: 0; }}
label {{ display: block; margin-top: 10px; font-size: 14px; }}
select, textarea {{ width: 100%; box-sizing: border-box; margin-top: 4px; font: inherit; padding: 8px; }}
.bar {{ position: sticky; top: 0; background: #1d1c19; color: white; padding: 12px 20px; display: flex; justify-content: space-between; gap: 12px; align-items: center; }}
button {{ font: inherit; padding: 8px 14px; border: 0; border-radius: 8px; background: #ffe08a; cursor: pointer; }}
</style>
</head>
<body>
<div class="bar"><strong>空白盲标，页面里没有参考动作</strong><button type="button" id="save">导出已填表格</button></div>
<main>
<h1>31 条校园必要性盲标</h1>
<p class="note">先读同目录的说明书。每条只判断划线片段。动作可以留空。导出的表格是填写副本，不会改写题目原件。</p>
{''.join(cards)}
</main>
<script>
document.getElementById("save").onclick = () => {{
  const rows = [["编号","动作","必要事实","备注"]];
  for (const unit of document.querySelectorAll(".unit")) {{
    rows.push([unit.dataset.id, unit.querySelector("[name=action]").value, unit.querySelector("[name=facts]").value, unit.querySelector("[name=notes]").value]);
  }}
  const csv = rows.map(row => row.map(value => `"${{String(value).replaceAll('"', '""')}}"`).join(",")).join("\\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob(["\\ufeff" + csv], {{type: "text/csv;charset=utf-8"}}));
  link.download = "人工盲标_已填写.csv";
  link.click();
}};
</script>
</body>
</html>
"""
    (DST / "打开题目.html").write_text(page, encoding="utf-8")


def write_docs() -> None:
    (DST / "从这里开始.md").write_text("""# 校园必要性盲标包

日期：2026-11-02。这个文件夹可以单独拿走。31 条题目、片段解析、填写说明和入口都在这里。

本包没有模型预测，没有参考动作，也没有已经填好的标签。动作请由人工填写。

## 入口

1. 读完本页。
2. 读 `说明书.md`。
3. 用下面任一处看题：
   - 双击 `打开题目.html`
   - 打开 `题目一览.md`
   - 打开 `题目解析.md`，核对每个片段在原文中的位置
4. 填写时使用 `人工盲标表.csv`、网页里的导出，或 `返还/` 中的 JSON 副本。

`题目/` 里的 12 个 JSON 是空白原件。请保持它们不动。
""", encoding="utf-8")
    (DST / "说明书.md").write_text("""# 说明书

共 12 篇、31 条。每条已经划出片段和信息类别，不用重新找实体，也不用改类别。

要判断的是：这条信息对这个用户要求、这个接收方，应该怎么处理。

同一段原文如果分成几条，接收方或要求可能不同，请分开判断。

## 填写什么

动作只使用这六个代码：

| 动作 | 含义 |
| --- | --- |
| `DELETE` | 这条信息不出现在给该接收方的结果里 |
| `LOCAL_AGGREGATE` | 只留下数量或统计，不留下是谁 |
| `GENERALIZE` | 留下大致水平或角色，不留下原来的值 |
| `PSEUDONYMIZE` | 换成稳定代号，不同的人仍要能分开 |
| `RETAIN` | 这个接收方可以看到原来的值 |
| `PAUSE` | 先停下来。接收方、权限或任务要求不够，或者继续做会越过权限 |

判断时看三件事：用户这句话要完成什么，接收方是谁，这个身份能不能把这条信息给这个接收方。

拿不准就不要猜。动作留空，在必要事实或备注里写卡在哪里。

## 三个填写入口

三个入口填的是同一套题，选一个即可。

- `人工盲标表.csv`：在「动作」列填写。必要事实和备注可以留空。
- `打开题目.html`：在浏览器里选择动作，点「导出已填表格」。导出的文件是副本。
- `返还/`：如需交 JSON，把填好的 `n01.json` 到 `n12.json` 放进这个文件夹。只改 `annotation` 里的 `canonical_action`、`required_facts`、`notes`、`annotator`、`annotated_at`。能判断时 `adjudication` 写「已填写」，不能判断写「待裁定」。

`题目/` 中的空白原件不要覆盖。交回时请说明人工盲标已经完成并冻结。

## 类别对照

`PERSON_NAME` 人名，`ORG` 机构，`LOCATION` 地点，`PHONE` 电话，`EMAIL` 邮箱，`DORM` 宿舍，`BUDGET` 金额，`GRADE` 成绩，`STUDENT_ID` 学号，`BANK_CARD` 银行卡，`SENSITIVE_ATTR` 敏感个人情况。

## 本包不含的内容

没有模型输出，没有每条的建议动作，也没有训练权重。这些题在装入本包之前没有参与模型训练、调参或候选筛选。
""", encoding="utf-8")
    (DST / "标注模板.json").write_text(json.dumps({
        "unit_id": "",
        "quote": "",
        "category": "",
        "boundary_id": "",
        "recipient_id": "",
        "identity_key": "",
        "user_task": "",
        "annotation": {
            "canonical_action": "",
            "required_facts": "",
            "adjudication": "",
            "notes": "",
            "annotator": "",
            "annotated_at": "",
        },
        "allowed_actions": [
            "DELETE", "LOCAL_AGGREGATE", "GENERALIZE", "PSEUDONYMIZE", "RETAIN", "PAUSE",
        ],
        "if_uncertain": "动作留空，adjudication 填写待裁定",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    returned = DST / "返还"
    returned.mkdir(parents=True, exist_ok=True)
    (returned / "请把填好的文件放这里.txt").write_text(
        "填好的 n01.json 到 n12.json 放在这个文件夹。\n"
        "也可以只交填好的人工盲标表。\n"
        "不要覆盖上一级「题目」里的空白原件。\n",
        encoding="utf-8",
    )


def write_manifest(documents: list[dict]) -> None:
    payload = {
        "created": "2026-11-02",
        "purpose": "可单独拿走的 31 条空白盲标",
        "labels_filled": False,
        "model_predictions_included": False,
        "unit_count": 31,
        "files": [
            {"file": f"题目/{document['_file']}", "sha256": document["_sha256"], "units": len(document["units"])}
            for document in documents
        ],
    }
    (DST / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_zip() -> None:
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DST.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(DST.parent).as_posix())


def main() -> None:
    documents = load_documents()
    DST.mkdir(parents=True, exist_ok=True)
    write_questions(documents)
    write_overview(documents)
    write_parse(documents)
    write_sheet(documents)
    write_html(documents)
    write_docs()
    write_manifest(documents)
    write_zip()
    print(json.dumps({"folder": str(DST), "zip": str(ZIP), "units": 31}, ensure_ascii=False))


if __name__ == "__main__":
    main()
