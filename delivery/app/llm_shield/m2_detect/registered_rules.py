"""Shield-owned configurable recognizers sharing the existing Span pipeline."""
import re
from functools import lru_cache

from .. import config
from ..integrations import RecognitionRules
from ..schema import Span


class RegisteredRuleDetector:
    name = "registered_rules"

    def __init__(self, settings: RecognitionRules):
        self.rules = []
        for spec in settings.patterns:
            if spec.category not in config.rules()["categories"]:
                raise ValueError("规则包含未知实体类别")
            expression = re.compile(spec.regex, flags=re.IGNORECASE)
            self.rules.append((spec, expression))

    def detect(self, text, columns=None, rows=None):
        spans = []
        for spec, expression in self.rules:
            for match in expression.finditer(text):
                if match.start() == match.end():
                    continue
                spans.append(Span(match.start(), match.end(), match.group(), spec.category,
                                  spec.score, self.name, spec.name))
        return spans


@lru_cache(maxsize=4)
def detector(settings_json: str):
    return RegisteredRuleDetector(RecognitionRules.model_validate_json(settings_json))
