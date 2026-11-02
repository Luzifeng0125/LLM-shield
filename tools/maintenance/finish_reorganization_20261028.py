"""Relocation support only: repair links, retain model/data bytes, write navigation."""
from pathlib import Path
import ast
import hashlib
import html
import json
import os
import re

ROOT = Path("D:/challenge_AI/LLM-Shield")
OLD = Path("D:/challenge_AI")
PLANS = Path("C:/Users/nicholas/.codex/visualizations/2026/10/26/01a176d0-0c9a-77c3-a5f9-8127b00c6443")
AUDIT = ROOT / "04_技术文档/整理记录/目录整理审计_20261028.json"
audit = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
moves = [(Path(m["from"]), Path(m["to"])) for m in audit["moves"]]

def mapped(path):
    path = Path(os.path.abspath(path))
    for source, target in moves:
        if path == source or source in path.parents:
            path = target / path.relative_to(source)
    return path

def original(path):
    path = Path(os.path.abspath(path))
    for source, target in reversed(moves):
        if path == target or target in path.parents:
            path = source / path.relative_to(target)
    return path

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest().upper()

# Verify original user/model/data bytes before touching documentation or path-only scripts.
missing, mismatched = [], []
for item in audit["protected_before"]:
    path = mapped(Path(item["old_path"]))
    if not path.exists():
        if any(d["path"].lower() == str(path).lower() for d in audit["deleted"]):
            continue
        missing.append(str(path))
    elif digest(path) != item["sha256"]:
        mismatched.append(str(path))
if missing or mismatched:
    raise RuntimeError(json.dumps({"missing": missing, "mismatched": mismatched}, ensure_ascii=False))
audit["protected_relocation_check"] = {"missing": 0, "mismatched": 0, "verified_before_path_updates": True}
changed = []

def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8-sig") != content:
        path.write_text(content, encoding="utf-8", newline="\r\n" if path.suffix == ".cmd" else "\n")
        changed.append(str(path.relative_to(ROOT)))

def update_absolute_text(text):
    # All replacement values are deferred, avoiding prefix replacement inside a new path.
    tokens = {}
    for index, (source, _) in enumerate(sorted(moves, key=lambda pair: len(str(pair[0])), reverse=True)):
        target = mapped(source)
        for variant, replacement in ((str(source), str(target)), (source.as_posix(), target.as_posix())):
            token = f"__RELOCATION_PATH_{index}_{len(tokens)}__"
            if variant in text:
                text = text.replace(variant, token)
                tokens[token] = replacement
    text = re.sub(r"D:/challenge_AI(?!/LLM-Shield)(?=$|[\s，。；：、\x60\"<>])", ROOT.as_posix(), text)
    for token, value in tokens.items():
        text = text.replace(token, value)
    return text

link_pattern = re.compile(r"(!?\[[^\]\n]*\]\()(<[^>]+>|[^)\s]+)(\))")
for path in ROOT.rglob("*.md"):
    rel = path.relative_to(ROOT)
    if any(part in {"runtime", "outputs", "models", ".git"} for part in rel.parts):
        continue
    text = path.read_text(encoding="utf-8-sig")
    old_path = original(path)
    def repair_link(match):
        url = match.group(2).strip("<>")
        if re.match(r"^(https?://|mailto:|#|data:)", url):
            return match.group(0)
        target_text, separator, fragment = url.partition("#")
        target_text = re.sub(r"^/([A-Za-z]:/)", r"\1", target_text)
        line = ""
        line_match = re.search(r":\d+$", target_text)
        if line_match:
            line = line_match.group()
            target_text = target_text[:line_match.start()]
        absolute = bool(re.match(r"^[A-Za-z]:[/\\]", target_text))
        old_target = Path(target_text) if absolute else old_path.parent / target_text
        target = mapped(old_target)
        if absolute:
            new_url = target.as_posix()
        else:
            new_url = os.path.relpath(target, path.parent).replace("\\", "/")
        new_url += line + (separator + fragment if separator else "")
        return match.group(1) + "<" + new_url + ">" + match.group(3)
    text = link_pattern.sub(repair_link, text)
    text = update_absolute_text(text)
    text = text.replace("delivery/数据集", "03_数据与人工复核").replace("delivery\\数据集", "03_数据与人工复核")
    text = text.replace("delivery/提交材料", "02_提交材料").replace("delivery\\提交材料", "02_提交材料")
    text = re.sub(r"(?<![A-Za-z0-9:/])docs/", "04_技术文档/", text)
    text = re.sub(r"(?<![./])\.\./数据集", "../../03_数据与人工复核", text)
    text = text.replace("../../runtime/training_env", "../../delivery/runtime/training_env")
    text = text.replace("..\\..\\runtime\\training_env", "..\\..\\delivery\\runtime\\training_env")
    write(path, text)

# The dataset packages moved one level away from delivery/app; preserve their protections.
package_scripts = ROOT / "03_数据与人工复核/复核与训练执行包_20261014/scripts"
for name in ("evaluate_gold_ner.py", "train_transformer_ner.py", "train_gold_policy.py"):
    path = package_scripts / name
    text = path.read_text(encoding="utf-8")
    text = text.replace('ROOT.parents[1] / "app"', 'ROOT.parents[1] / "delivery" / "app"')
    text = text.replace("ROOT.parents[1] / 'app'", "ROOT.parents[1] / 'delivery' / 'app'")
    write(path, text)
path = package_scripts / "package_execution.py"
write(path, path.read_text(encoding="utf-8").replace("ROOT.parents[2]/", "ROOT.parents[1]/"))
path = ROOT / "tools/qa/optimization_qa.cjs"
write(path, path.read_text(encoding="utf-8").replace("delivery/数据集/", "03_数据与人工复核/"))
path = ROOT / "delivery/运行验证.cmd"
write(path, path.read_text(encoding="utf-8").replace("..\\数据集\\", "..\\..\\03_数据与人工复核\\"))
path = ROOT / "03_数据与人工复核/任务必要性复核_20261026_v2/打开复核页面.cmd"
write(path, '@echo off\nstart "" "%~dp0..\\..\\delivery\\app\\scripts\\action_review.html"\n')
path = ROOT / "delivery/运行Python.cmd"
text = path.read_text(encoding="utf-8")
text = text.replace('echo Python environment missing.', 'if exist "%~dp0runtime\\training_env\\Scripts\\python.exe" set "SHIELD_PYTHON=%~dp0runtime\\training_env\\Scripts\\python.exe"\nif defined SHIELD_PYTHON goto configured\necho Python environment missing.')
write(path, text)

# Rebase activation/config paths without reinstalling or changing package versions.
venv = ROOT / "delivery/runtime/training_env"
for path in (venv / "pyvenv.cfg", *(venv / "Scripts").glob("activate*"), venv / "Scripts/Activate.ps1"):
    if path.is_file():
        text = path.read_text(encoding="utf-8-sig")
        text = text.replace(str(OLD / "delivery"), str(ROOT / "delivery"))
        text = text.replace((OLD / "delivery").as_posix(), (ROOT / "delivery").as_posix())
        write(path, text)

# Preserve credentials byte-for-byte; report stale local path setting names only.
env = ROOT / "delivery/app/.env"
stale_env_keys = []
if env.exists():
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() in {"SHIELD_MODEL_DIR", "SHIELD_ACTION_MODEL_PATH", "SHIELD_GLINER_MODEL_PATH", "SHIELD_UPLOAD_DIR"}:
            if str(OLD / "delivery") in value or (OLD / "delivery").as_posix() in value:
                stale_env_keys.append(key.strip())
audit["stale_env_path_keys"] = stale_env_keys

path = ROOT / ".gitignore"
text = path.read_text(encoding="utf-8")
text = text.replace("!/docs/", "!/04_技术文档/\n!/01_优化方案/\n!/02_提交材料/\n!/03_数据与人工复核/\n!/00_文件导航.html\n!/打开文件导航.cmd\n!/打开人工复核.cmd")
text = text.replace("/delivery/数据集/", "/03_数据与人工复核/")
text += "\n# Local reorganization audit and generated download copies.\n/04_技术文档/整理记录/*.json\n/01_优化方案/*.zip\n/02_提交材料/99_历史版本/**/build/\n"
write(path, text)
state_path = ROOT / "04_技术文档/执行状态.json"
state = json.loads(state_path.read_text(encoding="utf-8-sig"))
state["workspace"] = ROOT.as_posix()
state["directory_organization"] = {
    "at": "2026-10-28",
    "scope": "file relocation, path repair, navigation, disposable-cache cleanup",
    "plans": "01_优化方案",
    "submissions": "02_提交材料",
    "review_data": "03_数据与人工复核",
    "technical_documents": "04_技术文档",
    "application": "delivery/app",
    "runtime": "delivery/runtime",
    "models_or_labels_retrained": False,
}
for key in ("report", "review_entry"):
    if key in state.get("optimization_20261026", {}):
        value = state["optimization_20261026"][key]
        state["optimization_20261026"][key] = value.replace("docs/", "04_技术文档/").replace("delivery/数据集/", "03_数据与人工复核/")
write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

for path in (ROOT / "03_数据与人工复核/复核与训练执行包_20261014/开始这里.md",
             ROOT / "03_数据与人工复核/复核与训练执行包_20261014/人工gold接入说明.md",
             ROOT / "04_技术文档/本地模型联调_20261016.md",
             ROOT / "04_技术文档/清理结果_20261017.md"):
    old_text = path.read_text(encoding="utf-8")
    banner = "> 历史记录：下文配置与数字属于当时阶段，不是当前启动依据。当前操作先看项目根目录 README.md 和 01_优化方案。\n\n"
    if not old_text.startswith("> 历史记录"):
        write(path, banner + old_text)

write(ROOT / "delivery/先读我.md", """# 程序与运行环境

本目录保留英文 app/runtime 路径，避免模型分词器与运行脚本因目录重命名失效。

- app：应用源码、当前模型、配置、测试与验证证据。
- runtime：现有 Python 3.12 与训练基础模型，不属于可随意删除的缓存。
- 启动隐盾.cmd：标准启动入口；会检查真实 GLiNER 权重。
- 运行Python.cmd：自动寻找本目录的 Python 环境，支持显式 SHIELD_PYTHON 配置。
- 运行验证.cmd：软件验证入口，不等于真实 GLiNER 和真实生成验收。

人工数据已移到项目根目录 03_数据与人工复核；提交材料在 02_提交材料。
当前缺少 gliner_v3/pytorch_model.bin，整理文件不会自动补齐权重。
""")

write(ROOT / "README.md", """# 隐盾 LLM-Shield｜从这里开始

整理日期：2026-10-28。唯一维护目录：D:/challenge_AI/LLM-Shield。

双击 [打开文件导航.cmd](打开文件导航.cmd)，或打开 [可点击文件导航](00_文件导航.html)。

## 我现在要找什么

- 看下一步优化安排：[01_优化方案](01_优化方案/开始这里.md)。
- 找我需要亲自做的事：[人工执行手册](01_优化方案/隐盾优化方案-02人工执行手册.md)，优先 H01/H02/H06。
- 交接给 AI：[AI 分阶段任务书](01_优化方案/隐盾优化方案-03AI任务书.md)。
- 找申报书、报告、PPT：[02_提交材料](02_提交材料/使用说明.md)。
- 做人工复核、找数据：[03_数据与人工复核](03_数据与人工复核/开始这里.md)。
- 看技术文档、现状和清理记录：[04_技术文档](04_技术文档/开始这里.md)。
- 找源码：[delivery/app](delivery/app)；找模型：[模型清单](delivery/app/models/ACTIVE_MODELS.json)。
- 找运行环境：[delivery/runtime](delivery/runtime)；找辅助工具：[tools](tools/README.md)。

## 当前应当知道

1. 这次只整理文件、修复路径和清理可重建内容，没有重新训练或替换活动模型。
2. 真实 GLiNER 权重仍未补齐，标准启动可能明确报告缺少权重；这不是文件整理新增的模型问题。
3. 当前复核入口为 20261026_v2；已有 336 条机器草稿不等于本轮人工金标。
4. 优化方案仍是方案，任务书不代表已经实施。
5. 提交材料是编辑基础，文件名含“最终”不代表已经覆盖最新研究证据。
6. 本项目没有提交、推送或部署；原有工作区修改与 Git 历史保留。

## 常用入口

- [启动隐盾.cmd](启动隐盾.cmd)
- [打开人工复核.cmd](打开人工复核.cmd)
- [软件验证](delivery/运行验证.cmd)
- [安装与验证说明](04_技术文档/从GitHub安装与验证.md)
- [原技术说明](04_技术文档/项目原说明.md)

“个人资料”是同级目录中的其他课程材料，未纳入隐盾，也未删除。
""")
write(ROOT / "01_优化方案/开始这里.md", """# 优化方案与分工

当前使用这三份 2026-10-27 定稿的方案；2026-10-28 只更新整理后的路径，不改变其研究结论。

1. [总方案](隐盾优化方案-01总方案.md)：目标、步骤、模型、设备、验收。
2. [人工执行手册](隐盾优化方案-02人工执行手册.md)：你先读 H01/H02/H06。
3. [AI 任务书](隐盾优化方案-03AI任务书.md)：未来按指定工作包执行。

文中“已有证据”与“未来步骤”不可混淆。先完善复核协议，再做全量标注。
""")
write(ROOT / "02_提交材料/使用说明.md", """# 申报、报告与答辩材料

- 01_申报书：保留的项目申报书。
- 02_报告：现有报告编辑基础，以及 20261017 的修改建议。
- 03_答辩PPT：目前保留的 20261017 内容修订版。
- 99_历史版本：旧版 PPT 和制作过程原件；相似文件经校验内容不同，因此保留。

这些文件没有在本次整理中改写正文。最终提交前需按最新优化方案和真实验收结果更新。
历史 source_report.docx/source_deck.pptx 是不同内容的原件；已清除可重建渲染图，未删除原件和制作脚本。
""")
write(ROOT / "03_数据与人工复核/开始这里.md", """# 数据与人工复核

## 当前优先

[任务必要性复核_20261026_v2](任务必要性复核_20261026_v2/开始这里.md)：当前 336 条机器草稿与首批 28 题入口。
请先读 [人工手册](../01_优化方案/隐盾优化方案-02人工执行手册.md)，复核工具待完善事项以该方案为准。

## 保留的基础与历史

- 隐盾数据集_v1：基础数据及来源说明，仍被历史复核脚本引用。
- 复核与训练执行包_20261014：历史复核、训练工具与来源证据，不代表当前活动模型已通过本轮人工验收。
- 任务必要性复核_20261026：第一版开发实验资料，仅供追溯，日常请用 v2。

人工 reviews/reviewed 文件保留在本机且应继续被 Git 忽略；不要把裁决员答案提前交给独立 A/B。
""")
write(ROOT / "04_技术文档/开始这里.md", """# 技术文档

优先阅读：

- [执行状态](执行状态.json)：包含历史与当前状态，注意每条证据的日期和模式。
- [首轮优化记录](优化记录与人工事项_20261026.md)：已做改动及第一轮验证边界。
- [安装与验证](从GitHub安装与验证.md)。
- [项目原说明](项目原说明.md)：迁移前技术 README，链接已更新；历史性能和“已验证”表述仍须结合日期理解。
- [本次整理记录](整理记录/整理完成说明_20261028.md)。

其余 20261016/20261017 文档、插图和测量数据保留用于追溯，不作为当前配置或新的独立盲测成绩。
下一步以 [总方案](../01_优化方案/隐盾优化方案-01总方案.md) 为准。
""")
write(ROOT / "tools/README.md", """# 辅助工具

- qa/optimization_qa.cjs：最近一次工程浏览器验证工具；mock + rules-only，不能替代真实 GLiNER 验收。
- qa/browser_qa.cjs：历史 BERT 候选阶段脚本，当前不作为默认启动或验收入口。
- maintenance：本次目录迁移与路径维护记录。

应用自己的脚本位于 ../delivery/app/scripts。完整执行任务请看 ../01_优化方案。
""")
write(ROOT / "打开文件导航.cmd", '@echo off\nstart "" "%~dp000_文件导航.html"\n')
write(ROOT / "打开人工复核.cmd", '@echo off\nstart "" "%~dp0delivery\\app\\scripts\\action_review.html"\n')

cards = [
    ("01", "优化方案与分工", "先看人工事项，再按阶段交给 AI。", [
        ("总方案", "01_优化方案/隐盾优化方案-01总方案.md"),
        ("人工执行手册 · 优先读", "01_优化方案/隐盾优化方案-02人工执行手册.md"),
        ("AI 任务书", "01_优化方案/隐盾优化方案-03AI任务书.md"),
        ("打开方案文件夹", "01_优化方案/")]),
    ("02", "申报、报告与 PPT", "当前编辑基础与历史原件分开。", [
        ("项目申报书", "02_提交材料/01_申报书/隐盾项目申报书.docx"),
        ("报告与修改建议", "02_提交材料/02_报告/"),
        ("最新保留的答辩 PPT", "02_提交材料/03_答辩PPT/隐盾-隐私保护对话系统-苹果风-20261017内容修订.pptx"),
        ("历史版本与原件", "02_提交材料/99_历史版本/")]),
    ("03", "数据与人工复核", "当前使用 v2；旧数据保留为来源证据。", [
        ("当前复核说明", "03_数据与人工复核/任务必要性复核_20261026_v2/开始这里.md"),
        ("打开离线复核页面", "delivery/app/scripts/action_review.html"),
        ("首批 28 题文件", "03_数据与人工复核/任务必要性复核_20261026_v2/review-first-batch.json"),
        ("全部数据文件夹", "03_数据与人工复核/")]),
    ("04", "技术、运行与证据", "程序保持英文路径；模型状态单独核对。", [
        ("技术文档导航", "04_技术文档/开始这里.md"),
        ("应用源码", "delivery/app/"),
        ("活动模型清单", "delivery/app/models/ACTIVE_MODELS.json"),
        ("运行环境", "delivery/runtime/"),
        ("本次整理说明", "04_技术文档/整理记录/整理完成说明_20261028.md")]),
]
sections=[]
for num, title, intro, links in cards:
    anchors="".join(f'<li><a href="{html.escape(href, quote=True)}">{html.escape(label)}</a></li>' for label, href in links)
    sections.append(f'<section><span class="number">{num}</span><h2>{title}</h2><p>{intro}</p><ul>{anchors}</ul></section>')
page = r"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>隐盾 · 文件导航</title><style>
*{box-sizing:border-box}body{margin:0;background:#f6f7f9;color:#202936;font:16px/1.7 "Microsoft YaHei",sans-serif}
main{max-width:1100px;margin:0 auto;padding:40px 24px}header{border-bottom:2px solid #263e59;padding-bottom:22px;margin-bottom:26px}
h1{font-size:30px;margin:6px 0}header p{margin:6px 0;color:#586475}.tag{font-size:13px;letter-spacing:2px;color:#49627e}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}section{background:white;border:1px solid #dce1e7;padding:24px;border-radius:8px}
h2{font-size:20px;margin:3px 0}section p{font-size:14px;color:#5f6876;margin:8px 0 14px}.number{font-size:13px;font-weight:bold;color:#506782}
ul{padding-left:20px;margin:0}li{margin:7px 0}a{color:#174b80;text-underline-offset:3px}a:hover{color:#0a2e55}
aside{margin-top:24px;padding:16px 20px;border-left:3px solid #9a762c;background:#fffaf0}
footer{font-size:13px;color:#596574;margin-top:24px}@media(max-width:650px){main{padding:22px 14px}.grid{grid-template-columns:1fr}h1{font-size:25px}section{padding:18px}}
</style><main><header><div class="tag">LLM-SHIELD / 本机文件导航</div><h1>隐盾资料，从这里找</h1>
<p>方案、人工复核、提交材料、程序与证据集中管理。</p><p>目录：D:\challenge_AI\LLM-Shield · 整理日期：2026-10-28</p></header><div class="grid">"""
page += "".join(sections)
page += """</div><aside><strong>当前状态</strong><br>优化方案尚待分阶段实施；336 条复核题仍需真人判断。真实 GLiNER 大权重尚缺，启动前请先核对模型清单。<br>本次只整理文件和路径，没有训练、替换模型或部署。</aside>
<footer>双击根目录“启动隐盾.cmd”启动应用；“打开人工复核.cmd”进入离线标注页面。<br>本页完全离线，不加载外部脚本。若浏览器不直接打开文件夹，请在资源管理器进入同名目录。<br>个人课程资料保留在同级“个人资料”文件夹，未改动。</footer></main></html>"""
write(ROOT / "00_文件导航.html", page)

ai_plan = ROOT / "AI_EXECUTION_PLAN.md"
text=ai_plan.read_text(encoding="utf-8")
write(ai_plan, "# 目录整理后的交接入口（2026-10-28）\n\n唯一维护根目录为 D:/challenge_AI/LLM-Shield；源码仍在 delivery/app。\n先读 01_优化方案/隐盾优化方案-03AI任务书.md。下面保留先前阶段记录，不把历史验证当作当前完整验收。\n\n"+text)

audit["path_updates"] = changed
audit["navigation"] = "00_文件导航.html"
AUDIT.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"protected_files_verified":len(audit["protected_before"]),"updated_text_files":len(changed),"stale_env_path_keys":stale_env_keys,"navigation":str(ROOT/"00_文件导航.html")},ensure_ascii=False))
