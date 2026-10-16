"""Apply the 2026-10-17 verified implementation updates to the final report."""
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt, RGBColor


SOURCE = Path(r"D:\APP\Wechat\weixin\xwechat_files\wxid_3472350egxs112_4146\msg\file\2026-10\隐盾项目最终报告_本地模型方案版_更新20261016.docx")
OUTPUT = Path(r"D:\project\隐盾\outputs\隐盾项目最终报告_更新20261017.docx")


def set_text(paragraph, value):
    if paragraph.runs:
        paragraph.runs[0].text = value
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(value)


doc = Document(SOURCE)
p = doc.paragraphs

replacements = {
    0: "隐盾项目最终报告 本地模型方案版",
    3: p[3].text.replace("编制日期：2026年10月14日", "更新日期：2026年10月17日"),
    7: ("现有原型已实现统一对话、六类模型动作、DeepSeek 兼容接口、会话映射与自动化检查，并接入微调后的 GLiNER 识别模型"
        "（独立手写评测集 field_v1 上粒度无关 F1 0.907，见第九章）。2026 年 10 月 17 日已完成公开测试文本的真实 API 连通验证，"
        "以及合成 Excel 的上传、处理和真实模型回答验证；明确的分类人数问题改为本机全表精确统计。独立人工任务评测、"
        "多轮代号一致性验收与第二台电脑部署检查仍待完成，不能据现有工程检查推断真实场景任务完成率。"),
    21: ("用户选择身份、任务和处理要求，输入问题或添加材料。对明确的结构化分类人数问题，系统在本机对完整表格精确统计，"
         "仅在授权与复检通过后展示结果，不将个人明细交给外部模型。其他问题经过本地识别、决策和转换，再与已处理历史合并复检后调用生成服务。"
         "回答通过复检才展示并写入会话；若回答只含少量受限片段，系统先在本机隐藏并再次复检。未通过的轮次不提交历史，保留此前成功内容。"),
    23: ("图 1 2026 年 10 月 16 日统一对话原型截图。截图当时使用离线 mock；"
         "2026 年 10 月 17 日已完成 DeepSeek 真实接口与合成 Excel 问答联调，截图本身不作为真实生成质量证据。"),
    41: ("部署时冻结模型权重与类别规范。GLiNER 按最大长度滑窗切分长文本并保留原文偏移，多个窗口可批量推理，分块结果合并去重。"
         "已启用的 GLiNER 若缺失或推理异常，流程暂停外发，不把识别失败解释为未发现敏感信息。格式类（电话、邮箱、证件、银行卡、密钥、"
         "微信、预算、成绩等）由带校验位的正则底座判定；GLiNER 负责语义类（人名、机构、地点、宿舍、敏感属性）。"),
    65: ("现有客户端通过 OpenAI 兼容接口调用已配置的 DeepSeek 服务，密钥只从本机配置读取。真实模式下，网络、HTTP 或超时失败会明确暂停，"
         "不再伪装成离线演示回答。公开短文本与合成 Excel 的真实调用均已验证；真实业务材料的任务质量仍需独立评测。"),
    90: ("下列已有结果汇总截至 2026 年 10 月 17 日的随包验证与本机联调。识别层（GLiNER）与动作模型已有训练和评测记录；"
         "当前自动化测试与 38 项冒烟检查通过。DeepSeek 真实接口已用公开短文本和合成 Excel 验证，人工任务评测及第二台设备验收仍待补。"),
    94: ("识别层结论：在 87 条独立手写材料（149 个实体、14 类）上，「语义类 GLiNER + 规则底座」取得粒度无关 F1 0.9068、"
         "边界严格 F1 0.8607，较纯规则基线 0.7790 提升 0.128；同源人工 gold（80 条 / 124 实体）上 F1 0.9500。"
         "真实 API 连通已验证，但端到端任务完成率、人工评测与部署资源曲线仍待补，不据此声称完成真实场景验收。"),
    105: ("识别与脱敏画面为真实运行，生成回答可展示当前已接通的 DeepSeek 真实模式；演示时应保留界面的真实 API 标识，"
          "并用公开或合成材料，避免把学生个人明细用于联调。旧版离线 mock 截图只标作历史原型。"
          "视频文件、提交网址、时长限制与命名要求为【待补 赛事要求及最终视频链接】。"),
    127: ("隐盾形成了以统一对话为入口、以本地模型为识别和动作决策核心、以程序安全检查为执行约束的可运行原型。"
          "识别层已接入微调后的 GLiNER 语义模型，动作层采用 TF-IDF + 逻辑回归；附件解析、多轮映射、完整载荷检查、"
          "回答复检和本机全表分类计数共同支持文件问答。"),
    128: ("目前可支持的结论是：识别模型在独立手写集取得粒度无关 F1 0.907，自动化检查已通过，真实 DeepSeek 接口和合成 Excel 问答已连通，"
          "明确的分类人数问题可在本机按完整表格精确计算。人工任务评测、多轮一致性验收、第二台电脑部署和完整资源曲线仍待补；"
          "这些结果不等于实际用户场景的总体完成率。"),
}
for index, value in replacements.items():
    set_text(p[index], value)

set_text(doc.tables[3].cell(2, 1).paragraphs[0],
         "对明确的分类人数问题在本机全表精确统计；其他请求识别、决策并转换")
set_text(doc.tables[3].cell(4, 1).paragraphs[0],
         "回答通过复检后展示；少量受限片段可先隐藏并再次复检")
set_text(doc.tables[4].cell(1, 2).paragraphs[0],
         "外部模型请求复检完整历史与本轮内容；本机精确计数不调用外部模型")
set_text(doc.tables[7].cell(1, 1).paragraphs[0], "截至 2026 年 10 月 17 日，全套自动化检查通过")
set_text(doc.tables[7].cell(1, 2).paragraphs[0],
         "覆盖会话、识别、权限、出站复检、Excel 解析与本机精确计数；与人工任务评测分开解释")
set_text(doc.tables[8].cell(6, 1).paragraphs[0],
         "合成 Excel 的一次端到端实测约 3.85 秒，其中本地识别约 0.44 秒、真实 API 请求约 3.41 秒；"
         "该单次结果不能代替 P50/P95、冷启动、并发或显存峰值。")
set_text(doc.tables[11].cell(5, 1).paragraphs[0],
         "DeepSeek 真实接口已联通；继续完成干净设备部署和资源压测")
set_text(doc.tables[11].cell(5, 2).paragraphs[0],
         "公开短文本与合成 Excel 真实调用记录；第二台电脑验收待补")
set_text(doc.tables[12].cell(5, 1).paragraphs[0],
         "已完成公开短文本和合成 Excel 的真实 API 成功验证；完整多轮录像仍待补")

# The source's formal-results table gave its longest column only 4 cm,
# producing a page of very narrow orange text. Give results adequate space.
results_table = doc.tables[8]
results_table.autofit = False
for column, width in zip(results_table.columns, (Cm(3.4), Cm(7.0), Cm(6.5))):
    column.width = width
for row in results_table.rows:
    for cell, width in zip(row.cells, (Cm(3.4), Cm(7.0), Cm(6.5))):
        cell.width = width
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.size = Pt(10)
for row_index in (1, 2, 6):
    for run in results_table.cell(row_index, 1).paragraphs[0].runs:
        run.font.color.rgb = RGBColor(0, 0, 0)

# Add one focused update beside the conclusion rather than moving sections.
p[130].insert_paragraph_before(
    "结构化文件问答的本机验证还发现，固定取前几条相关行不能回答全表人数问题。"
    "当前实现只对表达明确的专业、学院或校区分类人数请求执行精确计数，先核对读取权限，再由本机遍历完整表格并复检结果；"
    "其他问题仍使用带覆盖范围说明的检索片段。真实学生表格的验证只用于核对本机计数路径，未将个人明细发送给外部模型。",
    style="Normal",
)

title_style = doc.styles["Title"]
title_style.font.color.rgb = RGBColor(0, 0, 0)
for run in p[0].runs:
    run.font.color.rgb = RGBColor(0, 0, 0)
    run.underline = False

# The source forced every chapter onto a new page, leaving many pages with
# only one line. Let chapter headings flow while keeping them with their text.
for paragraph in doc.paragraphs:
    if paragraph.style.name == "Heading 1":
        paragraph.paragraph_format.page_break_before = False
        paragraph.paragraph_format.keep_with_next = True
    if paragraph.text == "参考资料与本地证据":
        paragraph.paragraph_format.page_break_before = True
        paragraph.paragraph_format.keep_with_next = True

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUTPUT)
print(OUTPUT)
