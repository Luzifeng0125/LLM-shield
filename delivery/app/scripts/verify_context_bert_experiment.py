"""Reload saved research checkpoints and verify provenance without fitting."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.run_context_bert_experiment import (
    APP, AutoTokenizer, ChunkClassifier, build_chunks, evaluate, load, load_file,
    old_case, sha, torch, training_pairs, write_json,
)


def verify(out: Path):
    report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    protocol = report['protocol']
    for name, expected in protocol['inputs_before'].items():
        assert sha(Path(name)) == expected, f'Changed input or active model: {name}'
    assert report['inputs_after'] == protocol['inputs_before']
    assert not protocol['production_promoted']
    assert not protocol['gold_entity_type_features']
    for name, expected in protocol['code_hashes'].items():
        snapshot = out / 'source_snapshot' / Path(name).name
        current = APP / name
        assert sha(snapshot if snapshot.exists() else current) == expected, f'Code hash: {name}'
    case_path = next(Path(p) for p in protocol['inputs_before'] if Path(p).name == 'cases.jsonl')
    old_path = next(Path(p) for p in protocol['inputs_before'] if Path(p).name == 'confirmed_cases.jsonl')
    base = next(Path(p).parent for p in protocol['inputs_before'] if Path(p).name == 'model.safetensors')
    new, old = load(case_path), [old_case(c) for c in load(old_path)]
    all_cases = {c['case_id']: c for c in new + old}
    assert len(all_cases) == len(new) + len(old)
    split_groups = {s: {c['scenario_group'] for c in all_cases.values() if c['split'] == s}
                    for s in ['train', 'validation', 'test']}
    assert not (split_groups['train'] & split_groups['validation'])
    assert not (split_groups['train'] & split_groups['test'])
    assert not (split_groups['validation'] & split_groups['test'])
    assert set(protocol['validation_cases']) == {c['case_id'] for c in new if c['split'] == 'validation'}
    assert set(protocol['development_cases']) == {c['case_id'] for c in new if c['split'] == 'test'}
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    encoded, stats = {}, {}
    for cid, case in all_cases.items():
        encoded[cid], stats[cid] = build_chunks(case, tokenizer)
    assert stats == json.loads((out / 'token_coverage.json').read_text(encoding='utf-8'))
    assert all(s['all_body_tokens_covered'] and s['max_chunk_tokens'] <= 512 for s in stats.values())
    device = torch.device(protocol['device'])
    results = {}
    selection = json.loads((out / 'selection_before_development.json').read_text(encoding='utf-8'))
    assert selection['selected'] == report['selected']
    for condition, selected in report['selected'].items():
        train = [all_cases[cid] for cid in protocol['training_cases'][condition]]
        assert all(c['split'] == 'train' for c in train)
        expected_train = [c for c in new if c['split'] == 'train']
        if condition == 'mixed':
            expected_train += [c for c in old if c['split'] == 'train']
        assert {c['case_id'] for c in train} == {c['case_id'] for c in expected_train}
        pairs = training_pairs(train) if protocol.get('separate_prefix_encoding', False) else []
        pair_ids = [[a['case_id'], b['case_id']] for a, b in pairs]
        history = json.loads((out / f'{condition}_history.json').read_text(encoding='utf-8'))
        assert all(row.get('contrast_pairs', []) == pair_ids for row in history)
        best = max(history, key=lambda row: (row['validation']['macro_f1'], row['validation']['accuracy']))
        assert best['epoch'] == selected['epoch']
        checkpoint = out / selected['checkpoint']
        assert sha(checkpoint) == selected['sha256']
        model = ChunkClassifier(base, protocol.get('separate_prefix_encoding', False)).to(device)
        state = load_file(str(checkpoint))
        required = {name for name, param in model.named_parameters() if param.requires_grad}
        assert set(state) == required, 'Checkpoint must contain every and only trainable parameter'
        incompatible = model.load_state_dict(state, strict=False)
        assert not incompatible.unexpected_keys
        assert not (set(incompatible.missing_keys) & required)
        checks = {}
        max_delta = 0.0
        for split_name, cases, expected in [
            ('validation', [c for c in new if c['split'] == 'validation'], selected['validation']),
            ('development', [c for c in new if c['split'] == 'test'], report['results'][condition]['development']),
            ('old_development', [c for c in old if c['split'] == 'test'], report['results'][condition]['old_development']),
        ]:
            actual = evaluate(model, cases, encoded, tokenizer, device)
            assert [(r['case_id'], r['predicted']) for r in actual['rows']] == [(r['case_id'], r['predicted']) for r in expected['rows']]
            assert actual['macro_f1'] == expected['macro_f1']
            for row, saved in zip(actual['rows'], expected['rows']):
                max_delta = max(max_delta, *(abs(row['scores'][a] - saved['scores'][a]) for a in row['scores']))
            checks[split_name] = {'n': actual['n'], 'correct': actual['correct'], 'macro_f1': actual['macro_f1']}
        assert max_delta < 1e-6
        results[condition] = {'checkpoint_sha256': sha(checkpoint), 'all_trainable_keys_loaded': True,
                              'train_cases': len(train), 'training_context_pairs': pair_ids,
                              'reloaded_scores_max_absolute_delta': max_delta, 'checks': checks}
        del model
        if device.type == 'cuda':
            torch.cuda.empty_cache()
    result = {'passed': True, 'fitted_again': False, 'split_group_overlap': 0,
              'all_inputs_and_active_models_unchanged': True, 'token_coverage_cases': len(stats),
              'all_body_tokens_covered': True, 'max_chunk_tokens': max(s['max_chunk_tokens'] for s in stats.values()),
              'verification_code_sha256': sha(Path(__file__)),
              'current_runner_sha256': sha(APP / 'scripts/run_context_bert_experiment.py'),
              'results': results}
    write_json(out / 'verification.json', result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', required=True, type=Path)
    verify(parser.parse_args().experiment)
