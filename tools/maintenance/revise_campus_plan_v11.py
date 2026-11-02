"""Materialize the user-requested protocol revision; no corpus generation or fitting."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'delivery/app/data/campus_action_v5'


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    if (DATA / 'protocol_freeze_v1.1.json').exists():
        raise SystemExit('v1.1 is frozen; create a new protocol version instead of overwriting it.')
    original = (ROOT / '01_优化方案/历史版本/校园场景80到98执行方案_v1.0_20261031.md').read_text(encoding='utf-8')
    sources = original.split('## 3. GitHub优先检索结果与采用方式\n', 1)[1].split('## 4. 新一轮校园数据怎么做\n', 1)[0]
    introduction = '''# 校园最小必要披露：11月4日原型与80%—98%研究路线

版本v1.1；修订日期2026-10-31。当前目标明确为：**在保证任务必要事实完整的前提下，正确判断并执行最小必要披露**。六类动作准确率是主要量化指标之一，不能代表全部隐私处理能力。

已按用户提出的8项问题修订任务、标注、评测与进度，配套[标注与验收协议v1.1](校园最小披露标注与验收协议_v1.1.md)和[机器可读计划](../delivery/app/data/campus_action_v5/plan.json)。原方案已存[历史v1.0](历史版本/校园场景80到98执行方案_v1.0_20261031.md)。本次完成协议冻结；新校园语料、R0、复核新UI和新轮训练仍待实施，不能写成已具备能力。

范围继续限定同学、老师、班委、辅导员、学生会、社团和校内办事部门，暂按现有高校项目语境处理。停止企业及跨行业扩量。**11月4日交付目标是可运行、可人工审核、可复现成绩的校园决策原型；不以该日期承诺80%或98%。当前不启动400篇大规模生成。**

## 1. 保留方向，调整优先级

保留数据和标注先行、六类任务、分组防泄漏、BERT渐进实验与用户返还默认人审。把整链路测试从“分类达到80%之后”提前到首批：协议→少量完整材料→识别/决策/输出回归与AI初审并行→人工校准→基线比较→独立试测。

现有训练只有少量隐私追问和用途变化样本，重复拟合不足以解决；但增加样本前也要保证答案对应明确的边界和任务。旧138题与跨行业实验继续留档，不能自动继承为新边界协议下的正确训练标签。

本次核查还发现当前代码不是完整纯规则动作系统：`delivery/app/llm_shield/m3_decide/decision.py`由模型选动作，硬检查仅放行或暂停。因此R0是基于现有规则组件建立的、需冻结行为的离线基线，不将其误写成已经存在的纯规则模型。

## 2. 三层评测与80%—98%定义

L1评已知信息对象的六类动作，L2评从全文自动发现并正确决策，L3评每个实际边界的最终输出是否安全且完成任务。L2不得使用人工目标位置；漏识别必须计入漏检。L3同时检验必要事实、禁止事实、映射回填和任务完成，不能由L1分数推断。

正式评测拆成三份：

- **N近自然任务测试**：至少100篇，判断数随内容产生，约600处。按预先登记的任务采样规则收集，不按动作类别补额。没有实际使用频率时，明确称校园代理分布，并公布构成。
- **D均衡诊断**：另外预算约100篇、至少300个计分单元，每类至少50个，PAUSE按问题组去重后计。用于macro-F1、各类召回和困难边界定位，不与N混算自然准确率。
- **C用途反转挑战**：至少40对目标，两种情境都正确才通过一对。可从D中构造并登记共享来源，不跨训练与测试，不把共享部分说成第二套独立证据。

80%的研究验收条件：N六类严格准确率≥80%；D macro-F1≥0.78、每类召回≥0.70，任务级必要澄清召回≥0.80；C成对全对≥0.80。还要公布原始答案与可接受替代答案的分别得分、误留、过度删除、整篇全对率和任务级追问质量。达到L1阈值可以如实报告该项成绩，但未通过安全和效用门槛时，不能宣称整个原型已可自动发布。

相同原因导致10个字段不确定，只计一个PAUSE决策组；受影响字段仍保留追踪，不作为10个独立训练/评测样本。已知权限禁止、缺少关键信息、模型低置信转人工分开记录，不能互相替代。协议D节给出任务级计数和问题质量规则。

98%保留为长期研究目标：另需全新至少400篇、2000个判断及人工最终标签，给出文档/来源族相关性修正后的95%置信区间。六分类98%不称“阻止98%的泄露”，自动部分98%不替代全量98%。近自然分布改变时，解释变化并重测基线，不能直接拼接前后百分比。

**独立发布红线**：任何S3未经授权的实际披露、关键挑战中任何S2泄露、或可信权限硬禁止被绕过，即否决自动发布；严重告警未裁决或关键检查未运行也不能通过。S3/S2定义、候选泄露与出站前拦截的区别、正式S2任务风险≤1%的点估计与置信上界要求均见协议F节。效用还须满足任务完成率≥90%、必要事实保留率≥95%、无必要暂停率≤10%，防止全部删除或全部暂停刷安全分。短期只做人工审核原型，不以20篇“未观察到泄露”证明真实风险为零。

## 3. 公开资源筛选：保留原筛选，补充CI-Work

'''
    ci_work = '''补充[CI-Work（ACL 2026 Industry）](https://aclanthology.org/2026.acl-industry.103/)：其评测关注不同信息流方向中必要内容的传达与敏感内容的保留边界。借鉴其同时评安全与任务效用、干扰上下文和多接收方的设计，转化为校园工作流；不把企业数据加入本轮训练。

论文关联的[Microsoft ACV仓库](https://github.com/microsoft/ACV)可作代码入口线索。本轮未核实完整种子数据的可下载版本，暂登记为“评测设计参考、数据可用性待核”，不把下载成功或已复现写成完成。所有来源仍按原许可、版本和来源族核验规则执行。

'''
    remainder = '''## 4. 先冻结标注，再生成首批

每条信息必须绑定实际处理边界、接收对象、用途和授权依据。外部AI处理、获准校内交付、公开发布分别标注；“最终交给老师”不能代替“当前发送给外部服务”的接收方。标注协议把真实可用的系统上下文、人工监督目标、审计元数据分开，避免把人工答案放进模型输入。

同一姓名可以在获准实名核对时保留，在外部生成只需关联个体时代号化，在公开总体总结只需人数时汇总。每个答案都需要任务必要事实和对应输出约束；删除人数虽然不泄露，却不能完成统计任务。

六类统一规则详见协议B/C：先保留必要事实与许可约束，再选择最少披露；固定首选动作，必要时预先登记合理替代及输出约束；争议在看模型预测前集中裁决。不能把标注员分歧一律改成PAUSE，也不能按模型错误事后扩充“可接受答案”。

首批40篇主要校准口径及开发，建议先按来源组分28篇训练、12篇开发验证；具体划分在样本写作前登记。包括班级协作、课程沟通、师生事务、社团管理、活动宣传、奖助材料、校园服务、纪要统计。八类是工作范围，不是八套固定模板，正文与请求不能明示处置答案。

40篇中选20篇做全文穷尽标注与整链路开发回归，覆盖三种边界和高风险反例。它们不是新增20篇，不是独立验收集。另准备12篇新的独立试测，来源/事件/模板族与40篇隔离，实际判断数随材料产生；该规模仅作试点证据。近期计划约52篇不同材料，不能据此宣称正式80%可靠达标。

后续正式80%数据预算仍以训练240篇、开发验证60篇、N测试100篇约400篇为主，**另列D约100篇及必要的额外挑战**。40篇及已暴露试测可纳入后续训练/开发预算，N/D正式测试须保持未见。原“主测试每类50条”取消，只在D要求配额；训练配额按学习需要调整，PAUSE不得通过字段复制凑数。

正文继续保留短群聊、中等文档、长邮件或多附件组合，约25%/50%/25%覆盖100—400、401—1600、1601—4000字；该分布指导训练设计，不强行改造近自然测试。材料数量、独立来源族数和计分单元数分别报告。

## 5. 保留默认人审返还，测试先独立作答

用户返还的新一轮有效结果仍默认已人审，不重复索要确认或新增必需的第二位真人。[复核约定](../03_数据与人工复核/校园场景复核约定_20261031.md)已同步更新。

训练/校准材料可以显示AI建议；AI对所有材料仍先审一遍。独立试测、N/D/C在首次人工判断时隐藏AI动作、理由、必要事实和预期输出；初答保存后再允许看AI建议，保留初答和最终答。争议集中复核，不向审稿人展示模型预测后再定标准答案。

“默认人审”证明本次返还的来源，不自动证明人审过程独立。缺少初答记录时仍接收有效答案，按AI辅助复核标记；独立评测另补隐藏建议的判断或如实降级证据，不补造时间/点击/复核人。哈希、题号、边界版本和结果完整性检查继续保留。

新复核入口与接收器列入11月4日前交付，当前旧工具不会因为文档修改就自动获得这些功能。

## 6. 实验比较与整链路同步启动

近期必做R0、B0、R0+B0：R0使用冻结规则及可解析的真实输入；B0使用当前BERT结构加人工确认的校园材料；R0+B0先定义规则可处理范围、分歧仲裁和硬权限否决，再与B0比较。三者使用同版输入与目标；规则同样不能读取人工必要事实或正确授权结论。分别报告原始模型动作、规则介入后的最终动作、覆盖率和安全阻断。

B1（目标相关分块聚合）与B2（辅助监督及用途对照）保留为后续候选，由首轮错误决定是否值得做，避免挤占近期闭环。现有活动系统再作为P-current保留对照，不将其模型加门控结构冒称R0。

从第一轮就做20篇成对轨道：同一材料分别走已知目标决策和自动识别决策，再走真实转换/输出链路。日志记录识别漏项、错误动作、改写丢事实、最终残留及实际边界。外部请求在发出前检查，不能只看最后的可见文本。

GLiNER匹配权重仍是实际识别条件；若未恢复，必须明确启用的识别器及模式，计入相应漏检，不以人工目标补位。规则识别演示与完整语义识别验收分开；mock生成只证明软件流程，不代表真实生成器安全与任务完成。近期优先修复会绕过边界或漏掉关键信息的问题，暂不换大型底座。

## 7. 11月4日前交付与长期预算

按北京时间安排，以下是工作目标和依赖，不是已经完成的结果：

- **10月31日**：完成v1.1方案、输入/标注/评测协议、来源更新、版本与冻结清单。本轮已完成文档部分；R0和评分器仍待实现。
- **11月1日**：完成40篇AI初审材料、复核入口和有效返还导入；从中选20篇标全信息并开始整链路回归。先交可审批次，不等全包才开发工具。
- **11月2日**：接收人工校准，集中处理歧义；完善12篇额外试测及隐藏建议的人审流程，冻结首轮数据和规则。人工反馈未到时继续工具和离线回归，不伪造人工完成状态。
- **11月3日**：运行R0/B0/R0+B0、20篇整链路回归，修复主要失败，保存模型、规则、输入协议及训练来源清单。人工标签不足时，B0弱监督结果单列为AI标签开发成绩。
- **11月4日**：在候选冻结后运行独立试测，交付可运行原型、复核导入工具、完整命令、数据/权重哈希、错误清单和三层报告。保留人工审核后交付；若人审或权重条件未完成，明确降级为流程演示及未完成项，不写成独立人审验收通过。

近期52篇按每篇4—8分钟粗估为3.5—7人时基础审阅，隐藏建议初答和争议复核另计，以首5篇实测修正。20篇穷尽标注及整链路调试是额外工程工作，不能算在这段人审时间里。

后续正式80%阶段约400篇主数据＋约100篇诊断；98%阶段另需至少400篇全新材料。累计约900份材料起，额外挑战和迭代再增加，独立来源族另计。仅按4—8分钟估算已约60—120人时，不含工程、全篇标注和争议；这些明确属于长期研究预算，不包含在11月4日原型交付中。

扩到400篇的条件是：v1.1输入和动作规则落地、40篇完成校准或争议有去向、R0/B0/组合基线跑通、20篇整链路问题有记录、测试隐藏建议与默认人审接收互不冲突。若发现协议需修改，先版本化并修订首批，避免用错误口径大量造题。

通过试点后再按80→90→95→98迭代，新增材料由错误分布决定，保留随机常见任务。测试暴露后转为开发回归，新验收用新材料。当前原始复核、历史模型和活动配置不覆盖。

## 8. 八项修改核对

1. 处理边界：协议A，三个边界＋真实接收方＋用途＋权限来源，推理字段与人工标签隔离。
2. 动作重叠：协议B/C，必要事实优先、首选与可接受表达、争议审计及版本化。
3. 分布冲突：第2节与协议E，N不补类别配额，D均衡，C反转单列。
4. 整链路太晚：第4/6/7节，第一轮20篇，与已知目标轨道成对比较。
5. 泄露红线：协议F，严重披露或权限绕过否决自动发布，安全与效用同时验收。
6. AI确认偏差：第5节与协议G，测试人工先答，AI建议后展示；默认人审约定保留。
7. 消融不足：第6节，R0/B0/R0+B0为近期，B1/B2按证据后置，并纠正现有代码身份。
8. 节点和规模：第7节，11月4日原型与长期80%/98%拆开，列清新增诊断及最终测试工作量。
'''
    (ROOT / '01_优化方案/校园场景80到98执行方案_20261031.md').write_text(introduction + sources + ci_work + remainder, encoding='utf-8')
    plan = {
        'schema': 'campus-action-execution-plan-v1.1', 'date': '2026-10-31',
        'status': 'protocol_frozen_implementation_pending',
        'objective': 'Execute minimum necessary disclosure while preserving required task facts and trusted boundary permissions',
        'scope': 'Chinese university student, teacher and campus organization workflows',
        'enterprise_expansion': False,
        'protocol': '../../../../01_优化方案/校园最小披露标注与验收协议_v1.1.md',
        'source_registry': 'source_registry.json',
        'actions': ['DELETE', 'GENERALIZE', 'LOCAL_AGGREGATE', 'PAUSE', 'PSEUDONYMIZE', 'RETAIN'],
        'boundaries': ['external_generation', 'authorized_local_delivery', 'public_release'],
        'inference_input_regions': ['runtime_input'],
        'excluded_from_inference': ['annotation', 'audit_metadata', 'human_resolved_purpose', 'human_required_facts', 'gold_permission_conclusions'],
        'decision_key': ['task_id', 'information_unit_id', 'boundary_id', 'recipient_id', 'purpose_id', 'policy_version'],
        'annotation_required': ['information_scope', 'purpose_and_source', 'permission_basis_refs', 'required_facts', 'canonical_action', 'acceptable_actions', 'expected_output_constraints', 'evidence_refs', 'annotation_status'],
        'ambiguity': {'canonical_action_before_model_prediction': True, 'acceptable_actions_separate_metric': True, 'unresolved_test_labels_allowed': False, 'annotation_disagreement_is_not_pause': True},
        'pause': {'unit': 'one_shared_missing_condition_group_per_task_boundary', 'duplicate_field_counting': False, 'training_group_normalized': True, 'kinds': ['clarification', 'policy_block', 'human_handoff'], 'question_quality_scored_for': 'clarification_only', 'unnecessary_abstention_counts_as_error': True},
        'review_policy': {
            'ai_first_review_all_materials': True,
            'training_ui': 'suggestions_visible',
            'test_ui': 'human_initial_answer_before_optional_ai_reveal',
            'user_return_is_human_review_declaration': True,
            'accept_valid_return_without_additional_human_confirmation': True,
            'missing_independent_first_answer': 'accept_human_provenance_but_do_not_claim_independence',
            'preserve_original_bytes_initial_and_final_answers': True,
            'fabricate_missing_review_metadata': False,
            'second_human_reviewer_mandatory': False,
            'new_ui_and_importer_status': 'to_implement'
        },
        'near_term': {
            'deadline': '2026-11-04', 'timezone': 'Asia/Shanghai',
            'deliverable': 'human_reviewable_reproducible_campus_decision_prototype',
            'formal_accuracy_claim_allowed': False,
            'calibration_documents': 40, 'calibration_train_documents': 28, 'calibration_validation_documents': 12,
            'e2e_regression_documents': 20, 'e2e_is_subset_of_calibration': True,
            'independent_pilot_documents': 12, 'total_distinct_documents_target': 52,
            'large_scale_generation_started': False,
            'models_required': ['R0', 'B0', 'R0+B0'], 'models_deferred': ['B1', 'B2'],
            'first_round_e2e_required': True,
            'human_or_detector_dependency_incomplete': 'report_flow_demo_or_draft_label_results_and_explicit_incomplete_acceptance',
            'schedule': {
                '2026-10-31': 'protocol_and_plan_freeze',
                '2026-11-01': 'AI_reviewed_calibration_pack_UI_import_and_begin_20_e2e_cases',
                '2026-11-02': 'human_calibration_disputes_pilot_labels_and_rule_freeze',
                '2026-11-03': 'baseline_experiments_and_e2e_repairs',
                '2026-11-04': 'frozen_candidate_pilot_evaluation_and_reproducible_delivery'
            }
        },
        'long_term_data': {
            'primary_documents_target': 400, 'split_documents': {'train': 240, 'validation': 60, 'natural_test': 100},
            'primary_decisions_estimate': 2400,
            'natural_test': {'class_quota': None, 'decisions_estimate': 600, 'sampling': 'pre_registered_task_window_channels_and_inclusion_rules_not_action_balancing', 'proxy_if_real_traffic_unknown': True},
            'balanced_diagnostic': {'additional_documents_estimate': 100, 'decision_units_min': 300, 'per_action_units_min': 50, 'pause_groups_deduplicated': True},
            'context_challenge': {'target_pairs_min': 40, 'scored_separately': True, 'may_share_with_diagnostic': True, 'must_disclose_overlap': True},
            'stage98_additional_new_documents_min': 400, 'stage98_new_decisions_min': 2000,
            'cumulative_document_budget_floor_estimate': 900,
            'additional_challenge_and_iteration_materials_not_in_floor': True,
            'near_term_materials_can_join_later_train_dev_not_fresh_test': True,
            'split_group_keys': ['source_family', 'scenario_family', 'event_id', 'context_pair_id'],
            'length_bands_apply_to_training_not_natural_test': [
                {'characters': [100, 400], 'share': 0.25}, {'characters': [401, 1600], 'share': 0.5}, {'characters': [1601, 4000], 'share': 0.25}
            ],
            'workflows': ['class_coordination', 'coursework_grades', 'teacher_counselor_handoff', 'club_membership', 'student_events', 'awards_financial_aid', 'campus_services', 'minutes_reports_statistics']
        },
        'evaluation': {
            'levels': ['L1_given_target_action', 'L2_automatic_detection_and_decision', 'L3_output_safety_and_utility'],
            'primary_metric': 'strict_canonical_six_action_accuracy_on_natural_set_with_pause_group_deduplication',
            'mix_natural_and_balanced_scores': False,
            'stage80': {'natural_accuracy_min': 0.80, 'diagnostic_macro_f1_min': 0.78, 'diagnostic_each_class_recall_min': 0.70, 'clarification_task_recall_min': 0.80, 'challenge_both_correct_min': 0.80},
            'stage98': {'natural_accuracy_target': 0.98, 'claim': 'research_target_not_promise', 'confidence_interval': '95_percent_document_or_source_clustered'},
            'task_pause_metrics': ['precision', 'recall', 'unnecessary_questions', 'missed_questions', 'repeated_questions_per_task', 'question_quality'],
            'raw_and_rule_intervened_predictions_separate': True,
            'unnecessary_abstention_is_wrong': True,
            'automatic_subset_accuracy_is_not_full_model_accuracy': True,
            'final_candidate_selection': 'development_validation_only',
            'exposed_test_becomes_development': True,
            'heldout_from_small_model_not_authoring_ai': True
        },
        'release_gate': {
            'separate_from_action_accuracy': True,
            's3_unauthorized_crossed_boundary_max': 0,
            's2_crossed_boundary_in_critical_challenges_max': 0,
            'trusted_hard_permission_bypass_max': 0,
            'unresolved_serious_findings_max': 0,
            'missing_critical_tests_allowed': False,
            'natural_s2_leakage_task_rate_max': 0.01,
            'statistical_deployment_claim_requires_one_sided_95_percent_upper_bound_at_most': 0.01,
            'natural_task_completion_min': 0.90,
            'required_fact_retention_min': 0.95,
            'unnecessary_pause_on_answerable_tasks_max': 0.10,
            'candidate_attempt_and_actual_egress_separate': True,
            'zero_observed_is_not_zero_population_risk': True,
            'near_term_mode': 'human_review_before_delivery'
        },
        'models': [
            {'id': 'R0', 'scope': 'new_offline_deterministic_baseline_from_existing_components', 'already_complete': False},
            {'id': 'B0', 'scope': 'existing_bert_structure_plus_reviewed_campus_inputs'},
            {'id': 'R0+B0', 'scope': 'predefined_rule_coverage_and_arbitration_plus_bert'},
            {'id': 'B1', 'scope': 'target_conditioned_chunk_aggregation', 'phase': 'after_pilot_error_review'},
            {'id': 'B2', 'scope': 'auxiliary_context_supervision_and_training_contrast', 'phase': 'after_pilot_error_review'}
        ],
        'current_system_control': 'P-current_model_actions_with_allow_or_pause_guards_not_R0',
        'expansion_gate': ['protocol_v1.1_implemented', '40_document_calibration_and_dispute_log', 'R0_B0_hybrid_runnable', '20_document_e2e_findings', 'test_first_answer_and_user_return_import_compatible'],
        'completed': {'campus_documents_generated': 0, 'human_reviewed_decisions': 0, 'new_models_trained': 0, 'new_e2e_runs': 0},
        'production_promoted': False
    }
    write_json(DATA / 'plan.json', plan)
    registry = json.loads((DATA / 'source_registry.json').read_text(encoding='utf-8'))
    registry['sources'] = [s for s in registry['sources'] if s['source_id'] != 'ci_work']
    registry['sources'].append({
        'source_id': 'ci_work', 'url': 'https://aclanthology.org/2026.acl-industry.103/',
        'repository_entry': 'https://github.com/microsoft/ACV', 'publication': 'ACL 2026 Industry',
        'priority': 'evaluation_design_reference_only', 'use': 'essential_content_utility_sensitive_context_and_multiple_information_flow_directions',
        'campus_training_admission': False, 'enterprise_expansion': False,
        'inspection_scope': 'official_abstract_and_paper_search_excerpt_plus_repository_landing',
        'data_download_verified': False, 'code_license_observed_at_repository_root': 'MIT',
        'dataset_license_and_pinned_data_version': 'not_verified',
        'admission': 'reference_only_data_availability_pending'
    })
    write_json(DATA / 'source_registry.json', registry)
    print(json.dumps({'revision': 'v1.1', 'near_term_documents': 52, 'e2e_subset': 20, 'long_term_budget_floor': 900, 'sources': len(registry['sources']), 'training_or_generation_performed': False}))


if __name__ == '__main__':
    main()
