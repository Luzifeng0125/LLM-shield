"""Constrained decoding must respect BIO transitions and maximize path score."""
from itertools import product

import numpy as np
import pytest

from llm_shield.m2_detect.reviewed_ner import constrained_bio_labels


def test_optimal_sequence_cannot_start_with_inside_label_or_change_its_type():
    labels = {0: "O", 1: "B-ORG", 2: "I-ORG", 3: "B-PHONE", 4: "I-PHONE"}
    probabilities = np.array([[.4, .1, .45, .04, .01], [.1, .1, .05, .25, .5], [.6, .1, .1, .1, .1]])
    scores = np.log(probabilities)
    result = constrained_bio_labels(scores, labels)
    legal = []
    for path in product(labels, repeat=3):
        if labels[path[0]].startswith("I-"):
            continue
        if any(labels[path[i]].startswith("I-") and labels[path[i - 1]] not in
               {"B-" + labels[path[i]][2:], labels[path[i]]} for i in range(1, 3)):
            continue
        legal.append((sum(scores[index, label] for index, label in enumerate(path)), path))
    optimum = max(score for score, _ in legal)
    assert sum(scores[index, label] for index, label in enumerate(result)) == pytest.approx(optimum)
    assert any(tuple(result) == path for _, path in legal)


def test_valid_sequence_and_empty_text_preserved():
    labels = {0: "O", 1: "B-ORG", 2: "I-ORG"}
    assert constrained_bio_labels(np.log([[.01, .98, .01], [.01, .01, .98], [.98, .01, .01]]), labels) == [1, 2, 0]
    assert constrained_bio_labels([], labels) == []


@pytest.mark.parametrize("scores", [[[float("nan"), 0, 0]], [[0, float("inf"), 0]], [[0, 0]]])
def test_invalid_score_array_fails_closed(scores):
    with pytest.raises(ValueError):
        constrained_bio_labels(scores, {0: "O", 1: "B-ORG", 2: "I-ORG"})
