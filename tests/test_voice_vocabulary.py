import dataclasses
import typing

from gladiaio_sdk import LiveV2InitRequest
from gladiaio_sdk.v2.live import generated_types

from runai.contracts.common import Provenance, ProvenanceKind
from runai.contracts.framing import RaceCandidate
from runai.voice.commands import extract_race
from runai.voice.live import build_live_options
from runai.voice.vocabulary import (
    GENERIC_TERM_INTENSITY,
    MAX_ENTRIES,
    MAX_INTENSITY,
    PROPER_NAME_INTENSITY,
    custom_spelling_for,
    gladia_vocabulary,
    vocabulary_for,
)

LANGUAGE_CODES = set(typing.get_args(generated_types.LiveV2TranscriptionLanguageCode))


def candidate(name="Kyoto Ekiden Run", city="Kyoto", country="JP", index=0):
    return RaceCandidate(
        id=f"c{index}", name=name, city=city, country=country,
        provenance=Provenance(kind=ProvenanceKind.linkup, url="https://race.example/facts"),
    )


def values(entries):
    return [entry["value"] for entry in entries]


def test_backward_compatible_static_vocabulary():
    assert gladia_vocabulary() == vocabulary_for()
    assert {"Lisbonne", "Lisboa", "Meia Maratona de Lisboa", "Milano Marathon", "Njuko"} <= set(
        values(gladia_vocabulary())
    )


def test_english_terms_present():
    vocab = set(values(vocabulary_for()))
    assert {"half marathon", "10K", "bib pickup", "start corral", "medical certificate",
            "Booking.com", "Accor", "Njuko", "Klikego", "PPS", "London", "Barcelona"} <= vocab


def test_candidates_seed_first_with_language_from_country():
    entries = vocabulary_for(
        [candidate("Maratón de Valencia Trinidad Alfonso", "Valencia", "ES"),
         candidate("London Landmarks Half Marathon", "London", "GB", 1),
         candidate("Maratona do Porto", "Porto", "pt", 2)],
        origin="Lyon", extra=["Sub 1h45 pacer"],
    )
    head = values(entries)[:8]
    assert head == ["Maratón de Valencia Trinidad Alfonso", "Valencia",
                    "London Landmarks Half Marathon", "London",
                    "Maratona do Porto", "Porto", "Lyon", "Sub 1h45 pacer"]
    by_value = {entry["value"]: entry for entry in entries}
    assert "language" not in by_value["Valencia"]
    assert by_value["London Landmarks Half Marathon"]["language"] == "en"
    assert by_value["Maratona do Porto"]["language"] == "pt"
    assert "language" not in by_value["Lyon"]


def test_dedupe_is_case_and_accent_insensitive():
    entries = vocabulary_for(
        [candidate("Praca do Comercio", "LISBOA", "PT")], extra=["njuko", "  Njuko ", "Meia  Maratona"],
    )
    keys = [value.casefold() for value in values(entries)]
    assert keys.count("lisboa") == 1
    assert "praça do comércio" not in keys
    assert keys.count("njuko") == 1
    assert "meia maratona" in keys and "meia  maratona" not in keys
    assert len(keys) == len(set(keys))


def test_dedupe_merges_hints_from_static_duplicates():
    entries = vocabulary_for([candidate("Corrida", "Lisbonne", "PT")], extra=["njuko", "half marathon"])
    by_value = {entry["value"].casefold(): entry for entry in entries}
    assert "language" not in by_value["lisbonne"]
    assert by_value["njuko"]["pronunciations"] == ["nyouko", "niouko"]
    assert by_value["njuko"]["intensity"] == PROPER_NAME_INTENSITY
    assert by_value["corrida"]["language"] == "pt"


def test_cap_keeps_dynamic_entries_first():
    many = [candidate(f"Race {i}", f"Town {i}", "US", i) for i in range(60)]
    entries = vocabulary_for(many)
    assert len(entries) == MAX_ENTRIES
    assert values(entries)[:2] == ["Race 0", "Town 0"]
    assert "Njuko" not in values(entries)


def test_intensity_bounds_and_plain_pronunciations():
    entries = vocabulary_for([candidate()], origin="Nantes")
    by_value = {entry["value"]: entry for entry in entries}
    assert by_value["Kyoto Ekiden Run"]["intensity"] == PROPER_NAME_INTENSITY
    assert by_value["half marathon"]["intensity"] == GENERIC_TERM_INTENSITY
    assert all(0 < entry["intensity"] <= MAX_INTENSITY for entry in entries)
    for entry in entries:
        for pronunciation in entry.get("pronunciations", []):
            assert "/" not in pronunciation and "ˈ" not in pronunciation
        assert entry.get("language") in (None, "fr", "en", "pt")


def test_custom_spelling():
    spelling = custom_spelling_for()["spelling_dictionary"]
    assert spelling["Njuko"] == ["nyouko", "niouko"]
    assert spelling["Klikego"] == ["clic ego", "click ego"]
    assert spelling["RunAI"] == ["run a i", "run ai"]
    assert "half marathon" not in spelling
    assert all(isinstance(v, list) and v for v in spelling.values())


def test_extract_race_still_understands_english_aliases():
    assert extract_race("the Lisbon half marathon").city == "Lisbon"
    assert extract_race("a 10K in Barcelona").city == "Barcelona"
    assert extract_race("running in London").country == "GB"
    assert extract_race("the Milan marathon").name == "Milano Marathon"


def _unknown_fields(obj, path="request"):
    found = []
    if dataclasses.is_dataclass(obj):
        if obj._unknown_fields:
            found.append((path, obj._unknown_fields))
        for f in dataclasses.fields(obj):
            if f.name != "_unknown_fields":
                found += _unknown_fields(getattr(obj, f.name), f"{path}.{f.name}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            found += _unknown_fields(item, f"{path}[{i}]")
    return found


def test_payload_validates_against_sdk():
    options = build_live_options(16000, vocabulary=vocabulary_for([candidate()], origin="Lyon"))
    options["realtime_processing"]["custom_spelling"] = True
    options["realtime_processing"]["custom_spelling_config"] = custom_spelling_for()
    request = LiveV2InitRequest.from_dict(options)
    assert _unknown_fields(request) == []
    realtime = request.realtime_processing
    entries = realtime.custom_vocabulary_config.vocabulary
    assert all(isinstance(e, generated_types.LiveV2CustomVocabularyEntry) for e in entries)
    assert all(e.language is None or e.language in LANGUAGE_CODES for e in entries)
    assert all(isinstance(e.value, str) and e.value for e in entries)
    assert isinstance(realtime.custom_spelling_config, generated_types.LiveV2CustomSpellingConfig)
    assert realtime.custom_spelling_config.spelling_dictionary["Njuko"] == ["nyouko", "niouko"]
