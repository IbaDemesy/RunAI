import asyncio
from datetime import date
from urllib.parse import urlsplit

import pytest

from runai.app.fakes import FakeRaceSearch, FakeTranscriber
from runai.app.providers import (
    ProviderStatus,
    ProviderUnavailableError,
    UnavailableBrowserAgents,
    UnavailableRaceSearch,
    UnavailableTranscriber,
    accommodation_coverage,
    accor_search_url,
    build_providers,
    forbidden_reason,
    host_matches,
    platform,
    provider_health,
    registration_coverage,
    select_mode,
    transport_coverage,
    trenitalia_search_url,
)
from runai.contracts.common import Automation, DataMode
from runai.models import Race, RunnerProfile, StepKind

ALL_KEYS = {"HAI_API_KEY": "h", "LINKUP_API_KEY": "l", "GLADIA_API_KEY": "g"}


@pytest.mark.parametrize(
    ("env", "mode"),
    [
        ({}, DataMode.live),
        ({"RUNAI_DEMO": "1"}, DataMode.demo),
        ({"RUNAI_MODE": "replay", "RUNAI_DEMO": "1"}, DataMode.replay),
        ({"RUNAI_MODE": "LIVE"}, DataMode.live),
    ],
)
def test_select_mode_is_explicit(env, mode):
    assert select_mode(env) is mode


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError, match="RUNAI_MODE"):
        select_mode({"RUNAI_MODE": "auto"})


def test_health_reports_each_provider_without_secret_values():
    health = provider_health({"LINKUP_API_KEY": "secret-l"})
    assert health["h"].status is ProviderStatus.missing_key
    assert health["linkup"].status is ProviderStatus.ok
    assert health["gladia"].status is ProviderStatus.missing_key
    assert "secret" not in " ".join(h.detail for h in health.values())
    secondary = provider_health({"HAI_API_KEY_2": "secret-h"})
    assert secondary["h"].status is ProviderStatus.ok
    both = provider_health({"HAI_API_KEY": "a", "HAI_API_KEY_2": "b"})
    assert both["h"].status is ProviderStatus.ok and "2 clé(s)" in both["h"].detail


def test_health_error_when_sdk_missing(monkeypatch):
    monkeypatch.setattr(
        "runai.app.providers._sdk_available", lambda name: name != "linkup"
    )
    assert provider_health(ALL_KEYS)["linkup"].status is ProviderStatus.error


@pytest.mark.parametrize(
    ("render_commit", "runai_commit", "service", "version"),
    [
        ("123456789abcdef", "abcdef123456789", "runai-live", "1234567"),
        (None, None, None, "dev"),
        (None, "abcdef123456789", None, "abcdef1"),
        ("", "abcdef123456789", None, "abcdef1"),
    ],
)
def test_health_deployment_metadata(monkeypatch, render_commit, runai_commit, service, version):
    for name, value in {
        "RENDER_GIT_COMMIT": render_commit,
        "RUNAI_GIT_COMMIT": runai_commit,
        "RENDER_SERVICE_NAME": service,
    }.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    payload = build_providers(DataMode.demo, env={}, delay=0).health_payload()
    assert payload["version"] == version
    assert payload["service"] == service


def test_live_without_keys_fails_explicitly_and_never_uses_fakes():
    providers = build_providers(DataMode.live, env={})
    assert providers.mode is DataMode.live and not providers.simulated
    assert isinstance(providers.search, UnavailableRaceSearch)
    assert isinstance(providers.agents, UnavailableBrowserAgents)
    assert isinstance(providers.transcriber, UnavailableTranscriber)
    with pytest.raises(ProviderUnavailableError, match="LINKUP_API_KEY absente"):
        asyncio.run(providers.search.find_race("une course à Lisbonne"))
    with pytest.raises(ProviderUnavailableError, match="HAI_API_KEY absente"):
        asyncio.run(
            providers.agents.start(
                StepKind.transport, "t", None, RunnerProfile(), None, None
            )
        )
    with pytest.raises(ProviderUnavailableError, match="GLADIA_API_KEY absente"):
        asyncio.run(providers.transcriber.transcribe(b"", "audio/wav"))
    payload = providers.health_payload()
    assert payload["mode"] == "live"
    assert payload["providers"] == {
        "h": "missing_key",
        "linkup": "missing_key",
        "gladia": "missing_key",
    }


def test_live_with_keys_builds_real_adapters_without_network():
    from runai.app.real import RealBrowserAgents, RealRaceSearch, RealTranscriber

    providers = build_providers(DataMode.live, env=ALL_KEYS)
    assert isinstance(providers.search, RealRaceSearch)
    assert isinstance(providers.agents, RealBrowserAgents)
    assert isinstance(providers.transcriber, RealTranscriber)
    partial = build_providers(
        DataMode.live, env={"HAI_API_KEY": "h", "LINKUP_API_KEY": "l"}
    )
    assert isinstance(partial.transcriber, UnavailableTranscriber)


def test_demo_results_are_labeled_demo():
    providers = build_providers(DataMode.demo, env={}, delay=0)
    assert providers.simulated
    assert isinstance(providers.search, FakeRaceSearch)
    assert isinstance(providers.transcriber, FakeTranscriber)

    async def scenario():
        async def ask(question, options):
            return options[0] if options else "ok"

        run = await providers.agents.start(
            StepKind.transport, "consigne", None, RunnerProfile(), lambda e: None, ask
        )
        return await run.wait()

    result = asyncio.run(scenario())
    assert result.data["provenance"]["mode"] == "demo"
    assert result.data["provenance"]["kind"] == "fixture"


def test_replay_defaults_to_committed_trace():
    providers = build_providers(DataMode.replay, env={})
    assert providers.health["replay"].detail == "Default demo replay trace"


@pytest.mark.parametrize(
    ("url", "automation", "code"),
    [
        ("https://in.njuko.com/race", Automation.automated, None),
        (
            "https://www.klikego.com/race",
            Automation.manual,
            "registration_platform_forbidden",
        ),
        (
            "https://www.ahotu.com/race",
            Automation.manual,
            "registration_platform_unsupported",
        ),
        (None, Automation.not_covered, "registration_link_missing"),
    ],
)
def test_registration_coverage(url, automation, code):
    coverage = registration_coverage(
        Race(name="R", city="Nairobi", country="KE", registration_url=url)
    )
    assert coverage.automation is automation
    assert [limit.code for limit in coverage.limitations] == ([code] if code else [])


@pytest.mark.parametrize(
    ("mode", "country", "automation"),
    [
        ("train", "Italia", Automation.automated),
        ("train", "JP", Automation.manual),
        ("avion", "IT", Automation.manual),
        ("aucun", "US", Automation.not_covered),
        ("téléportation", "US", Automation.manual),
    ],
)
def test_transport_coverage(mode, country, automation):
    assert transport_coverage(mode, country).automation is automation


ACCOR_MILAN_DEEP_LINK = (
    "https://all.accor.com/booking/en/accor/hotels/milan-italy"
    "?dateIn=2027-04-03&nights=2&compositions=1"
)


def _brief(**changes):
    from runai.app.tasks import TripBrief

    values = {
        "race_label": "Fictive race",
        "city": "Milan",
        "country": "IT",
        "arrival": date(2027, 4, 3),
        "departure": date(2027, 4, 5),
        "nights": 2,
        "origin": "Turin",
        "transport_mode": "train",
    }
    return TripBrief(**{**values, **changes})


def test_accor_search_url_matches_verified_pattern():
    url = accor_search_url("Milan", "IT", date(2027, 4, 3), date(2027, 4, 5))
    assert url == ACCOR_MILAN_DEEP_LINK
    assert "/booking/en/" in url and forbidden_reason(url) is None
    assert host_matches(url, platform("accor").hosts)


def test_accor_search_url_adults_and_country_names():
    url = accor_search_url(
        "Valencia", "Spain", date(2027, 4, 3), date(2027, 4, 6), adults=2
    )
    assert url.endswith("/valencia-spain?dateIn=2027-04-03&nights=3&compositions=2")


@pytest.mark.parametrize(
    ("arrival", "departure"),
    [
        (None, date(2027, 4, 5)),
        (date(2027, 4, 3), None),
        (None, None),
        (date(2027, 4, 5), date(2027, 4, 5)),
    ],
)
def test_accor_search_url_needs_dates(arrival, departure):
    assert accor_search_url("Milan", "IT", arrival, departure) is None


def test_accor_search_url_needs_city_and_country():
    assert accor_search_url("", "IT", date(2027, 4, 3), date(2027, 4, 5)) is None
    assert accor_search_url("Milan", None, date(2027, 4, 3), date(2027, 4, 5)) is None


def test_accor_search_url_encodes_special_characters():
    url = accor_search_url(
        "São Paulo/../x?y#z", "BR", date(2027, 4, 3), date(2027, 4, 4)
    )
    path = urlsplit(url).path
    assert path == "/booking/en/accor/hotels/sao-paulo-x-y-z-brazil"
    assert urlsplit(url).hostname == "all.accor.com"
    assert "#" not in url and url.count("?") == 1


def test_trenitalia_has_no_stable_deep_link():
    assert (
        trenitalia_search_url("Turin", "Milan", date(2027, 4, 3), date(2027, 4, 5))
        is None
    )
    coverage = transport_coverage("train", "IT", brief=_brief())
    assert coverage.start_url == "https://www.trenitalia.com/en.html"
    assert coverage.start_url_kind == "home"


def test_accommodation_coverage_uses_deep_link_when_buildable():
    coverage = accommodation_coverage(_brief())
    assert coverage.start_url == ACCOR_MILAN_DEEP_LINK
    assert coverage.start_url_kind == "deep_link"
    assert forbidden_reason(coverage.start_url) is None


def test_accommodation_coverage_derives_departure_from_nights():
    coverage = accommodation_coverage(_brief(departure=None))
    assert coverage.start_url == ACCOR_MILAN_DEEP_LINK


def test_accommodation_coverage_falls_back_to_home():
    for coverage in (
        accommodation_coverage(),
        accommodation_coverage(_brief(arrival=None)),
    ):
        assert coverage.start_url == "https://all.accor.com"
        assert coverage.start_url_kind == "home"
