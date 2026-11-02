"""Package the explicitly requested AI first review for a person's second review."""
from pathlib import Path
import copy
import hashlib
import json
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'delivery/app'))
from llm_shield.m4_necessity.research import annotation_for, case_hash

PACK = ROOT / '03_数据与人工复核/任务必要性复核_自然文档_v3_20261029'
OUT = PACK / 'AI初审_20261030'

# These changes record the contextual review, rather than bulk accepting proposals.
DELETE_CHANGES = {
    'na06-s04': ('当前回收基质的咨询事项与校内协调渠道', '旧借用单位没有被指定为本周回收责任方；后文已提供校内统一协调的背景，旧机构名连泛称也不必再保留。'),
    'na08-s02': ('本周通过统一平台调剂工具的安排', '旧借尺窗口已被统一平台替代，回访者不再按旧纸单找人；删除旧机构名即可，不能把泛称误作现行借尺去处。'),
    'na11-s03': ('下次标签的制作条件及由平台分派承接窗口', '旧标签工单已经结单，本轮承接单位尚未确定；后文提供新需求，旧机构名不支撑新的指定关系。'),
    'na17-s03': ('本期静音间统一预约及按可用时段分派', '这是上一期的预约抬头，原房间还在检修；本期由平台另行分派，不应保留旧机构或据此指派任务。'),
    'nb01-s04': ('本班漏水现场的处理与交接', '前次借用手续另有台账且明确不归本班处理；当前待办不需要识别旧借用单位，删除名称即可。'),
    'nb02-s02': ('轮椅转弯半径与通行体验建议', '路线介绍需要保留通行建议，不需要建议者的机构身份；原文明确没有合作单位名单，删除机构名不影响路线或建议。'),
    'nb11-s03': ('缓存机制及排查步骤', '缓存说明不涉及平台专属操作，也不登录该中心后台；解释本身可以保留，来源单位的名称及泛称均非排查必要条件。'),
    'nb13-s01': ('适合初学者的教学思路和课程体验', '来访者需要理解课堂内容，正文不介绍、推荐或致谢该单位；删除具体来源名称仍能保留参考练习流程的事实。'),
}
NOTES = {
    'na01-s01': '原理由把地点称为公开活动地点，但全文说这是内部试走。请二审确认外部整理的地点披露范围，不能把内部工作地点等同公开许可。',
    'na09-s04': '泛化后两人都会变成“某同学”。本题仅解释试验过程，可不区分人；若二审认为必须追踪先后执行者，应改代号化。',
    'nb08-s01': '“校内实践教学背景”是否确为介绍所需？初审暂保留粗粒度；如果只需体验内容，直接删除机构身份也可完成任务，请定口径。',
    'nb15-s03': '用户本次要的是追缺项清单，而非最终报道。校内场景是否需要进入这次清单尚可商榷；暂保留泛化，二审可改删除。',
    'nb18-s03': '材料实验教学背景与参观介绍有关，但其来源单位类型是否必须出现有取舍；初审保留粗粒度，二审可选删除。',
    'nb17-s01': '系统已给可信的六份分组汇总，无需再按姓名聚合；保留汇总及分母范围，删除名单姓名。',
}

def main():
    if OUT.exists():
        raise ValueError('输出已存在，不覆盖已交付初稿')
    cases = [json.loads(s) for s in (PACK/'cases.jsonl').read_text(encoding='utf8').splitlines() if s.strip()]
    tasks = json.loads((PACK/'review-task.json').read_text(encoding='utf8'))
    by_id = {c['case_id']: c for c in tasks['cases']}
    rows = []
    for c in cases:
        cid = c['case_id']
        assert by_id[cid]['case_sha256'] == case_hash(c)
        a = copy.deepcopy(c['proposal'])
        a['reason'] = a['reason'].replace('可删除除', '可删除')
        note = NOTES.get(cid, '')
        if cid in DELETE_CHANGES:
            facts, reason = DELETE_CHANGES[cid]
            a.update(action='DELETE', minimum_representation='none', allowed_actions=['DELETE'],
                     required_facts=facts, reason=reason)
            note = '本次初审将原 GENERALIZE 改为 DELETE。请重点确认：本任务是否需要保留来源机构的类型。'
        if cid == 'na01-s01':
            a['reason'] = '当前场地已变更，准确点位及门禁时间支撑内部执行安排；原文没有说明此内部排练地点可向公众发布，不能用公开地点作为理由。'
        if a['action'] == 'PAUSE':
            question = a.get('clarification_question', '')
            a['reason'] += ' 仅暂停这项不确定事实的认定或使用，已确认的其他事项可以先整理。'
            if question:
                a['reason'] += ' 待确认：' + question
            note = (note + ' 请二审确认该缺口是否确实阻碍本项输出；不应因此停止整篇所有已确认事项。').strip()
        probe = {**c, 'proposal': a}
        annotation_for(probe, allow_drafts=True)
        rows.append({'case_id':cid, 'case_sha256':case_hash(c), 'annotation':a,
                     'reviewer_kind':'ai', 'human_reviewed':False,
                     'ai_review_status':'ai_first_review_pending_human',
                     'original_proposal_action':c['proposal']['action'],
                     'changed_action':a['action'] != c['proposal']['action'],
                     'priority':bool(note), 'review_note':note or '已对照本篇任务、全文和目标实体，初审保留此项处置；依据见下方判断理由。'})
    response = {'schema':'action-review-response-v1', 'reviewer':'Codex-AI初审-待用户二审',
                'role':'ai_draft', 'reviewer_kind':'ai', 'human_reviewed':False,
                'review_status':'ai_pre_review_pending_human', 'date':'2026-10-30',
                'machine_suggestions_consulted_before_decisions':True,
                'scope':'user_requested_ai_first_review_not_independent_human_gold', 'reviews':rows}
    summary = {'cases':len(rows), 'documents':len({c['document_id'] for c in cases}),
               'changed_actions':sum(r['changed_action'] for r in rows),
               'priority_cases':sum(r['priority'] for r in rows),
               'actions':dict(Counter(r['annotation']['action'] for r in rows)),
               'source_cases_sha256':hashlib.sha256((PACK/'cases.jsonl').read_bytes()).hexdigest(),
               'human_reviewed':0}
    OUT.mkdir()
    (OUT/'AI初审_全量138_待二审.json').write_text(json.dumps(response,ensure_ascii=False,indent=2),encoding='utf8')
    first_ids = {c['case_id'] for c in json.loads((PACK/'review-first-batch.json').read_text(encoding='utf8'))['cases']}
    first = {**response,'reviews':[r for r in rows if r['case_id'] in first_ids]}
    (OUT/'AI初审_首批24_待二审.json').write_text(json.dumps(first,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'初审统计.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    template = Path(__file__).with_name('second_review_page.html').read_text(encoding='utf8')
    payload = json.dumps({'task':tasks,'draft':response},ensure_ascii=False).replace('<','\\u003c')
    (OUT/'打开二审.html').write_text(template.replace('/*__PAYLOAD__*/',payload),encoding='utf8')
    note = ('# AI初审稿，供你二审\n\n已对新版36份材料、138处判断做AI初审。直接打开“打开二审.html”，全文和初审答案已经载入。'
            '可以筛选重点项、修改动作/必要事实/理由，逐题点击“确认本题并下一题”。导出时填写你的姓名或编号。\n\n'
            f"本次改了{summary['changed_actions']}处首选动作，另对内部地点理由、暂停范围和可争议的最小表达做了说明。"
            f"页面共标记{summary['priority_cases']}处重点二审项。其余题也已初审，你可以逐题检查。\n\n"
            '导出保留你已确认的题号及尚未确认的AI内容；未点确认的题不会被标为人工完成。可把导出文件载入本页继续二审。'
            '这是看过AI初稿后的二审记录，不是两名真人独立盲标。原始数据和原建议未被覆盖。\n\n'
            'JSON初稿同时保留全量138题和首批24题；推荐使用本目录专用二审页，避免普通独立标注页丢失来源和确认进度。\n')
    (OUT/'开始这里.md').write_text(note,encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False))

if __name__ == '__main__':
    main()
