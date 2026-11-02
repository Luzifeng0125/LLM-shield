import copy
from llm_shield.m4_necessity.context_research import model_input,pipeline
from scripts.run_context_action_experiment import contrast
from scripts.build_context_review import compile_cases

def test_annotation_and_source_metadata_cannot_enter_features():
    case={'text':'陈予在会场处理设备。','target':'陈予','entity_type':'PERSON_NAME',
          'context':'收到给参展商的邮件线程。','task_description':'接着弄一下。',
          'annotation':{'action':'DELETE','reason':'特有答案词'},'scenario_group':'答案组','source_ids':['source']}
    before=model_input(case)
    case['annotation']={'action':'RETAIN','reason':'另一份答案'}
    case.update(scenario_group='换组',source_ids=['new'],expected_rendering='答案')
    assert model_input(case)==before
    assert '特有答案词' not in str(before) and '答案组' not in str(before)

def test_context_change_is_visible_and_ablation_removes_it():
    a={'text':'陶杉签收材料。','target':'陶杉','entity_type':'PERSON_NAME','context':'轮到外部顾问阅览。','task_description':'按这个接着做。'}
    b={**a,'context':'轮到有权限的档案核验员在本机核对。'}
    assert model_input(a)!=model_input(b)
    assert model_input(a,'no_prior')==model_input(b,'no_prior')
    assert model_input(a,'target_only')['document']==''

def test_context_flip_is_not_counted_correct_just_because_prediction_changed():
    cases=[{'case_id':'a','context_pair_id':'pair','target':'甲','annotation':{'action':'DELETE'}},
           {'case_id':'b','context_pair_id':'pair','target':'甲','annotation':{'action':'RETAIN'}}]
    result={'rows':[{'case_id':'a','predicted':'GENERALIZE','correct':False},
                    {'case_id':'b','predicted':'RETAIN','correct':True}]}
    r=contrast(cases,result)
    assert r['changed_target_pairs']==1 and r['both_correct']==0
    assert r['rows'][0]['changed_with_context']

def test_individual_target_does_not_take_ownership_of_a_separately_aggregated_roster():
    doc={'document_id':'testdoc','text':'沈晴提交反馈。名单：沈晴、李宁。',
         'decisions':[{'target':'沈晴','entity_type':'PERSON_NAME','action':'PSEUDONYMIZE'},
                      {'target':'沈晴、李宁','entity_type':'MULTI_PERSON','action':'LOCAL_AGGREGATE'}]}
    rows=compile_cases([doc])
    assert rows[0]['target_occurrences']==[0]
    assert rows[1]['target_occurrences']==[10]

def test_artificial_type_hint_cannot_change_fitted_predictions():
    cases=[{'text':'上午展厅迎接来宾','target':'展厅','entity_type':'LOCATION',
            'task_description':'接上刚才那版','context':'预约页明天发布'},
           {'text':'工单附着客户号码','target':'客户号码','entity_type':'PHONE',
            'task_description':'给来访者看看','context':'给大厅公告使用'}]
    inputs=[model_input(c) for c in cases]
    model=pipeline();model.fit(inputs,['RETAIN','DELETE'])
    before=model.predict_proba(inputs)
    changed=[{**r,'entity_type':'TEACHER_ANSWER_PAUSE'} for r in inputs]
    assert (model.predict_proba(changed)==before).all()
