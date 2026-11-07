import json

import pytest

from runai.h.answers import (
    AccommodationAnswer,
    RegistrationAnswer,
    StepAnswer,
    TransportAnswer,
    answer_schema_for,
    parse_answer,
)
from runai.models import StepKind


@pytest.mark.parametrize("kind,model", [
    (StepKind.search, StepAnswer),
    (StepKind.registration, RegistrationAnswer),
    (StepKind.accommodation, AccommodationAnswer),
    (StepKind.transport, TransportAnswer),
])
def test_schema_selection_and_optional_fields(kind, model):
    assert answer_schema_for(kind) is model
    assert model.model_json_schema()["required"] == ["stop_screen"]
    assert isinstance(parse_answer(kind, {"stop_screen": "payment"}), model)
    assert isinstance(parse_answer(kind, json.dumps({"stop_screen": "payment"})), model)


@pytest.mark.parametrize("raw", [None, [], 42, "garbage", "[]", {},
                                      {"stop_screen": "unknown"},
                                      {"stop_screen": "payment", "summary": "x" * 601},
                                      {"stop_screen": "payment", "options": [{}] * 4}])
def test_invalid_answers_return_none(raw):
    assert parse_answer(StepKind.accommodation, raw) is None
