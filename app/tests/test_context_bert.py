"""Check body coverage and input isolation without a downloaded neural model."""
import copy

import pytest

from llm_shield.m4_necessity.context_bert import build_chunks


class CharacterTokenizer:
    """Deterministic tokenizer: ordinary characters have IDs >= 1000."""
    unk_token_id = 100

    def encode(self, text, add_special_tokens=False):
        assert add_special_tokens is False
        return [ord(c) + 1000 for c in text]

    def convert_tokens_to_ids(self, token):
        return {'[unused1]': 2, '[unused2]': 3}.get(token, self.unk_token_id)

    def build_inputs_with_special_tokens(self, prefix, body):
        return [101] + prefix + [102] + body + [102]

    def create_token_type_ids_from_sequences(self, prefix, body):
        return [0] * (len(prefix) + 2) + [1] * (len(body) + 1)


def sample():
    return {'task_description': '整理一下给接班的人。', 'context': '晚班在工单里接着处理。',
            'text': '张青提交了记录。' + '春夏秋冬' * 400 + '附件末尾有张青的新回复。', 'target': '张青'}


def merged_body(chunks, stats):
    """Recover body IDs from the external pair format, not the chunk builder."""
    body = []
    for index, chunk in enumerate(chunks):
        ids = chunk['input_ids'][stats['prefix_tokens'] + 2:-1]
        body.extend(ids if index == 0 else ids[stats['overlap']:])
    return body


def test_long_document_covers_tail_and_has_bounded_chunks():
    case = sample()
    tok = CharacterTokenizer()
    chunks, stats = build_chunks(case, tok)
    recovered = merged_body(chunks, stats)
    expected = []
    for index, segment in enumerate(case['text'].split(case['target'])):
        if index:
            expected += [2] + tok.encode(case['target']) + [3]
        expected += tok.encode(segment)
    assert recovered == expected
    assert stats['chunks'] > 3 and stats['all_body_tokens_covered']
    assert stats['body_tokens_covered'] == len(expected)
    assert all(len(c['input_ids']) <= 512 for c in chunks)
    assert all(len(c['attention_mask']) == len(c['token_type_ids']) == len(c['input_ids']) for c in chunks)
    assert all(all(m == 1 for m in c['attention_mask']) for c in chunks)


def test_labels_entity_type_and_scenario_metadata_never_enter_inputs():
    case = sample()
    poisoned = copy.deepcopy(case)
    poisoned.update(annotation={'action': 'DELETE', 'reason': '秘密答案'}, entity_type='INVENTED_LABEL',
                    scenario_group='answer_is_delete', review={'status': 'human'}, source_ids=['teacher'])
    assert build_chunks(case, CharacterTokenizer()) == build_chunks(poisoned, CharacterTokenizer())


def test_long_prior_is_rejected_instead_of_silently_truncated():
    case = sample()
    case['context'] = '前序中仍待核对的授权条件。' * 60
    with pytest.raises(ValueError, match='不能静默截断'):
        build_chunks(case, CharacterTokenizer())


def test_selected_individual_mention_does_not_mark_the_same_name_inside_a_list():
    case = {'task_description': '接着这份走。', 'context': '下面两段属于不同的工作记录。',
            'text': '参会名单：张青、李禾。张青在后续工单中领取设备。', 'target': '张青'}
    chosen = case['text'].rindex('张青')
    case['target_occurrences'] = [chosen]
    chunks, stats = build_chunks(case, CharacterTokenizer())
    body = merged_body(chunks, stats)
    tok = CharacterTokenizer()
    expected = tok.encode(case['text'][:chosen]) + [2] + tok.encode('张青') + [3] + tok.encode(case['text'][chosen + 2:])
    assert body == expected and body.count(2) == body.count(3) == 1
    assert stats['selected_target_occurrences'] == [chosen]


@pytest.mark.parametrize('positions', [[-1], [0, 0], [1], [True]])
def test_inconsistent_selected_positions_are_rejected(positions):
    case = sample()
    case['target_occurrences'] = positions
    with pytest.raises(ValueError, match='位置'):
        build_chunks(case, CharacterTokenizer())


def test_overlapping_selected_targets_are_rejected():
    case = {'task_description': '整理', 'context': '记录', 'text': '哈哈哈', 'target': '哈哈', 'target_occurrences': [0, 1]}
    with pytest.raises(ValueError, match='重叠'):
        build_chunks(case, CharacterTokenizer())


def test_ablations_remove_only_the_requested_sources():
    tok = CharacterTokenizer()
    case = sample()
    _, full = build_chunks(case, tok)
    _, no_prior = build_chunks(case, tok, 'no_prior')
    no_context_chunks, no_context = build_chunks(case, tok, 'no_context')
    target_only_chunks, target_only = build_chunks(case, tok, 'target_only')
    assert no_prior['body_tokens'] == full['body_tokens']
    assert no_prior['prefix_tokens'] < full['prefix_tokens']
    expected = [2] + tok.encode(case['target']) + [3]
    assert merged_body(no_context_chunks, no_context) == expected
    assert merged_body(target_only_chunks, target_only) == expected
    assert target_only['prefix_tokens'] < no_context['prefix_tokens']


def test_invalid_overlap_cannot_make_the_chunk_loop_repeat_forever():
    with pytest.raises(ValueError, match='overlap'):
        build_chunks(sample(), CharacterTokenizer(), overlap=1000)


@pytest.fixture(scope='module')
def bert_runner():
    # Import the real selector; model downloads and fitting are never invoked.
    from scripts import run_context_bert_experiment
    return run_context_bert_experiment


def contrast_fixture():
    first = {**sample(), 'case_id': 'automated-pair-a', 'document_id': 'automated-document-a',
             'scenario_group': 'automated-group', 'split': 'train',
             'context_pair_id': 'automated-pair', 'annotation': {'action': 'RETAIN'},
             'target_occurrences': [0]}
    second = copy.deepcopy(first)
    second.update(case_id='automated-pair-b', document_id='automated-document-b',
                  context='月底提交的是面向所有来访者的说明。', annotation={'action': 'DELETE'})
    return first, second


def test_training_pairs_accept_controlled_training_context_change(bert_runner):
    a, b = contrast_fixture()
    assert bert_runner.training_pairs([a, b]) == [(a, b)]


@pytest.mark.parametrize('split', ['validation', 'test'])
def test_training_pairs_reject_evaluation_rows_even_without_label_change(bert_runner, split):
    a, b = contrast_fixture()
    a['split'] = b['split'] = split
    b['annotation'] = copy.deepcopy(a['annotation'])
    with pytest.raises(ValueError):
        bert_runner.training_pairs([a, b])


def test_training_pairs_reject_a_lone_development_row(bert_runner):
    a, _ = contrast_fixture()
    a['split'] = 'test'
    with pytest.raises(ValueError):
        bert_runner.training_pairs([a])


@pytest.mark.parametrize('field,value', [('scenario_group', 'different-group'),
                                       ('text', '这是另一份材料，张青也在其中。'),
                                       ('task_description', '换一个不同的要求。')])
def test_training_pairs_reject_changes_beyond_prior_context(bert_runner, field, value):
    a, b = contrast_fixture()
    b[field] = value
    with pytest.raises(ValueError):
        bert_runner.training_pairs([a, b])


def test_training_pairs_reject_contradictory_labels_for_identical_context(bert_runner):
    a, b = contrast_fixture()
    b['context'] = a['context']
    with pytest.raises(ValueError):
        bert_runner.training_pairs([a, b])


def test_training_pairs_reject_different_occurrences_of_the_same_name(bert_runner):
    a, b = contrast_fixture()
    b['target_occurrences'] = [b['text'].rindex('张青')]
    with pytest.raises(ValueError):
        bert_runner.training_pairs([a, b])


def test_contrast_encoder_receives_only_the_unpadded_input_prefix(bert_runner, monkeypatch):
    from types import SimpleNamespace
    import torch
    from torch import nn

    class RecordingEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.config = SimpleNamespace(hidden_size=2)
            self.encoder = nn.Module()
            self.encoder.layer = nn.ModuleList([nn.Linear(2, 2) for _ in range(12)])
            self.calls = []

        def forward(self, **inputs):
            self.calls.append({k: v.clone() for k, v in inputs.items()})
            ids = inputs['input_ids'].float()
            return SimpleNamespace(last_hidden_state=torch.stack([ids, ids + 1], dim=-1))

    encoder = RecordingEncoder()
    monkeypatch.setattr(bert_runner.AutoModel, 'from_pretrained', lambda *a, **k: encoder)
    model = bert_runner.ChunkClassifier('unused-test-path', context_contrast=True).eval()
    case = sample()
    case.update(annotation={'action': 'PAUSE', 'reason': '秘密答案'}, entity_type='PRIVATE_TEACHER_LABEL')
    chunks, stats = build_chunks(case, CharacterTokenizer())
    width = max(len(c['input_ids']) for c in chunks)
    inputs = {key: torch.tensor([c[key] + [0] * (width - len(c[key])) for c in chunks])
              for key in ('input_ids', 'attention_mask', 'token_type_ids')}
    with torch.inference_mode():
        model(inputs)
    assert len(encoder.calls) == 2
    prefix = encoder.calls[1]
    assert prefix['input_ids'].tolist() == [chunks[0]['input_ids'][:stats['prefix_tokens'] + 2]]
    assert prefix['attention_mask'].tolist() == [[1] * (stats['prefix_tokens'] + 2)]
    assert prefix['token_type_ids'].count_nonzero().item() == 0
