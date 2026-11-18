"""Local Presidio pattern recognizers mapped to Shield's existing categories."""
from functools import lru_cache

from .. import config as C
from ..integrations import Presidio
from ..schema import Span


class PresidioDetector:
    name = "presidio"

    def __init__(self, settings: Presidio):
        from presidio_analyzer import Pattern, PatternRecognizer

        self.recognizers = []
        for spec in settings.patterns:
            if spec.category not in C.rules()["categories"]:
                raise ValueError("Presidio 配置包含未知类别")
            recognizer = PatternRecognizer(
                supported_entity=spec.category, name=spec.name,
                patterns=[Pattern(name=spec.name, regex=spec.regex, score=spec.score)],
            )
            self.recognizers.append((spec, recognizer))

    def detect(self, text, columns=None, rows=None):
        spans = []
        for spec, recognizer in self.recognizers:
            for result in recognizer.analyze(text=text, entities=[spec.category]):
                spans.append(Span(result.start, result.end, text[result.start:result.end],
                                  spec.category, result.score, self.name, spec.name))
        return spans


@lru_cache(maxsize=4)
def detector(settings_json: str):
    return PresidioDetector(Presidio.model_validate_json(settings_json))
