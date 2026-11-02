import copy
import json

import pytest

from llm_shield.m4_necessity.research import annotation_for, case_hash, training_sample, validate_cases
from scripts.build_action_review import build_cases
from scripts.natural_action_data import (
    audit_documents, build_natural_cases, first_document_batch, load_documents,
    normalized_document, review_task, write_natural_pack,
)


def test_default_pack_uses_full_natural_documents_and_machine_drafts():
    documents = load_documents()
    cases = build_cases()
    audit = audit_documents(documents)
    assert audit['passed'], audit['errors']
    assert len(documents) >= 24 and len(audit['document_types']) >= 8
    assert len(cases) == sum(len(d['decisions']) for d in documents)
    assert validate_cases(cases)['sources'] == len(documents)
    assert {c['review']['status'] for c in cases} == {'machine_draft'}
    for case in cases:
        assert len(case['context']) > len(case['text'])
        assert case['text'] in case['context']
        annotation_for(case, allow_drafts=True)
    with pytest.raises(ValueError, match='人工复核'):
        annotation_for(cases[0], allow_drafts=False)


def test_renamed_entity_and_number_clone_cannot_evade_quality_gate():
    docs = load_documents()
    clone = copy.deepcopy(next(d for d in docs if not d.get('context_pair_id')))
    original = copy.deepcopy(clone)
    clone['document_id'] = 'renumbered-new-id'
    clone['scenario_group'] = 'pretend-new-family'
    value = clone['decisions'][0]['entities'][0]['text']
    # Replace consistently everywhere: changing the entity spelling is not new content.
    clone = json.loads(json.dumps(clone, ensure_ascii=False).replace(value, '另一处虚构实体'))
    assert normalized_document(original) == normalized_document(clone)
    report = audit_documents(docs + [clone])
    assert not report['passed']
    assert report['unapproved_near_duplicates']
    with pytest.raises(ValueError, match='重复材料'):
        build_natural_cases(docs + [clone])


def test_same_scenario_and_context_pairs_never_cross_splits():
    docs = load_documents()
    pair = next(d for d in docs if d.get('context_pair_id'))
    mate = next(d for d in docs if d is not pair and d.get('context_pair_id') == pair['context_pair_id'])
    assert pair['text'] == mate['text'] and pair['task_description'] == mate['task_description']
    assert pair['context'] != mate['context']
    assert pair['split'] == mate['split']
    mate['split'] = 'test' if pair['split'] != 'test' else 'train'
    report = audit_documents(docs)
    assert not report['passed'] and any('跨拆分' in e for e in report['errors'])


def test_short_prompt_needs_real_material_and_pause_needs_answerable_question():
    docs = load_documents()
    paused = next(s for d in docs for s in d['decisions'] if s['action'] == 'PAUSE')
    paused.pop('clarification_question')
    assert any('追问' in e for e in audit_documents(docs)['errors'])
    docs = load_documents()
    for doc in docs:
        doc['task_description'] = '删除姓名和手机号，只保留机构名称。'
    assert any('指令' in e for e in audit_documents(docs)['errors'])


def test_labels_evidence_and_phenomena_never_enter_model_or_blind_review_input():
    cases = build_cases()
    original = cases[0]
    altered = copy.deepcopy(original)
    altered['proposal']['reason'] = '禁止进入输入的答案解释_8675309'
    altered['proposal']['evidence'] = ['禁止进入输入的证据标记_2468']
    altered['proposal']['clarification_question'] = '禁止进入输入的提议追问_1357'
    assert case_hash(original) == case_hash(altered)
    assert training_sample(original, allow_drafts=True)['feature'] == training_sample(altered, allow_drafts=True)['feature']
    assert review_task([original]) == review_task([altered])
    public = review_task(cases)['cases']
    assert all(not {'proposal', 'annotation', 'review', 'split', 'phenomena', 'evidence'} & c.keys() for c in public)


@pytest.mark.parametrize('field', ['task_description', 'context', 'text'])
def test_answer_hints_in_any_model_input_field_are_rejected(field):
    docs = load_documents()
    docs[0][field] += '\n标注答案提示：PSEUDONYMIZE、DELETE。'
    report = audit_documents(docs)
    assert not report['passed']
    assert {'document_id': docs[0]['document_id'], 'field': field} in report['answer_cues_in_model_input']
    with pytest.raises(ValueError, match='标注答案提示'):
        build_natural_cases(docs)


def test_first_batch_contains_whole_documents_and_all_six_actions():
    docs, cases = load_documents(), build_cases()
    first = first_document_batch(docs, cases)
    selected = {c['document_id'] for c in first}
    assert len(selected) == 6
    assert len({c['proposal']['action'] for c in first}) == 6
    assert {c['case_id'] for c in first} == {c['case_id'] for c in cases if c['document_id'] in selected}
    assert all(c['split'] == 'train' for c in first)


def test_pack_rebuild_is_reproducible_but_cannot_be_submitted_as_next_batch(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    manifest = write_natural_pack(a)
    assert manifest['supervision'] == 'machine_draft_not_gold'
    with pytest.raises(ValueError, match='历史批次'):
        write_natural_pack(b)
    reproduced = write_natural_pack(b, rebuild_frozen=True)
    assert reproduced['build_mode'] == 'frozen_reproduction_not_new_data'
    assert (a / 'cases.jsonl').read_bytes() == (b / 'cases.jsonl').read_bytes()
    with pytest.raises(ValueError, match='历史批次'):
        write_natural_pack(tmp_path / 'next', history_paths=[a / 'documents.jsonl'])
    assert not (tmp_path / 'next').exists()
    with pytest.raises(ValueError, match='已存在'):
        write_natural_pack(a)


def test_every_repeated_entity_in_a_segment_gets_a_span():
    docs = load_documents()
    doc = next(d for d in docs if not d.get('context_pair_id'))
    decision = doc['decisions'][0]
    entity = decision['entities'][0]['text']
    old = decision['segment']
    new = old + '\n补记：' + entity + '与上文为同一对象。'
    doc['text'] = doc['text'].replace(old, new)
    decision['segment'] = new
    cases = build_natural_cases(docs)
    case = next(c for c in cases if c['case_id'] == doc['document_id'] + '-s01')
    assert sum(e['text'] == entity for e in case['entities']) == new.count(entity)
