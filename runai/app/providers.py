"""Explicit data modes, provider health and platforms supported by agents.

Live mode uses only H, Linkup and Gladia: missing keys cause explicit errors,
never a silent fallback to fakes. Demo and replay are explicitly selected
and label every StepResult with provenance.
"""

import importlib.util
import os
import re
import unicodedata
from collections.abc import AsyncIterable, AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote, unquote, urlencode, urlsplit

from pydantic import BaseModel

from runai.app.ports import (
    AgentRun,
    AskUser,
    BrowserAgents,
    EventSink,
    RaceSearch,
    Transcriber,
)
from runai.contracts.common import (
    Automation,
    DataMode,
    Limitation,
    Provenance,
    ProvenanceKind,
)
from runai.models import Race, RunnerProfile, StepKind, StepResult

if TYPE_CHECKING:
    from runai.app.tasks import TripBrief


class ProviderStatus(str, Enum):
    ok = "ok"
    missing_key = "missing_key"
    error = "error"


class ProviderUnavailableError(RuntimeError):
    """Unavailable live provider (missing key or SDK): never replaced by a fake."""


PROVIDERS = ("h", "linkup", "gladia")
DEFAULT_REPLAY_TRACE = Path(__file__).resolve().parents[2] / "fixtures/replay/demo-marathon.replay.json"
_KEY_NAMES = {
    "h": "HAI_API_KEY",
    "linkup": "LINKUP_API_KEY",
    "gladia": "GLADIA_API_KEY",
}
_SDK_MODULES = {"h": "hai_agents", "linkup": "linkup", "gladia": "gladiaio_sdk"}
_LABELS = {
    "h": "H (browser agents)",
    "linkup": "Linkup (search)",
    "gladia": "Gladia (voice)",
}


class ProviderHealth(BaseModel):
    name: str
    status: ProviderStatus
    detail: str


def select_mode(env: Mapping[str, str] | None = None) -> DataMode:
    """Use explicit RUNAI_MODE, otherwise RUNAI_DEMO=1 for demo, otherwise live."""
    env = os.environ if env is None else env
    raw = (env.get("RUNAI_MODE") or "").strip().lower()
    if raw:
        try:
            return DataMode(raw)
        except ValueError:
            raise ValueError(
                f"RUNAI_MODE={raw!r} invalid: expected live, demo or replay"
            ) from None
    if env.get("RUNAI_DEMO") == "1":
        return DataMode.demo
    return DataMode.live


def _h_key_names(env: Mapping[str, str]) -> list[str]:
    names = ["HAI_API_KEY"]
    index = 2
    while env.get(f"HAI_API_KEY_{index}"):
        names.append(f"HAI_API_KEY_{index}")
        index += 1
    return [name for name in names if env.get(name)]


def _has_key(name: str, env: Mapping[str, str]) -> bool:
    if name == "h":
        return bool(_h_key_names(env))
    return bool(env.get(_KEY_NAMES[name]))


def _sdk_available(name: str) -> bool:
    return importlib.util.find_spec(_SDK_MODULES[name]) is not None


def provider_health(env: Mapping[str, str] | None = None) -> dict[str, ProviderHealth]:
    """Local health without network calls or key values: ok, missing_key or error."""
    env = os.environ if env is None else env
    health = {}
    for name in PROVIDERS:
        if not _has_key(name, env):
            status = ProviderStatus.missing_key
            detail = (
                f"{_KEY_NAMES[name]} missing: {_LABELS[name]} unavailable in live mode."
            )
        elif not _sdk_available(name):
            status = ProviderStatus.error
            detail = f"SDK {_SDK_MODULES[name]} not installed: pip install -r requirements.txt."
        else:
            status = ProviderStatus.ok
            detail = (
                f"{len(_h_key_names(env))} H key(s) configured."
                if name == "h"
                else f"{_KEY_NAMES[name]} configured."
            )
        health[name] = ProviderHealth(name=name, status=status, detail=detail)
    return health


def unavailable_message(name: str, health: ProviderHealth) -> str:
    return f"Live mode: {_LABELS[name]} unavailable ({health.status.value}). {health.detail}"


def provenance_data(
    mode: DataMode, kind: ProvenanceKind, label: str, url: str | None = None
) -> dict[str, Any]:
    """StepResult provenance label: data mode plus contract Provenance."""
    return {
        "mode": mode.value,
        **Provenance(kind=kind, url=url, label=label).model_dump(mode="json"),
    }


class UnavailableRaceSearch:
    def __init__(self, message: str):
        self.message = message

    async def find_race(self, query: str) -> Race:
        raise ProviderUnavailableError(self.message)


class UnavailableBrowserAgents:
    def __init__(self, message: str):
        self.message = message

    async def start(
        self, kind: StepKind, task: str, *args: Any, **kwargs: Any
    ) -> AgentRun:
        raise ProviderUnavailableError(self.message)


class UnavailableTranscriber:
    def __init__(self, message: str):
        self.message = message

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        raise ProviderUnavailableError(self.message)

    def stream(self, chunks: AsyncIterable[bytes], sample_rate: int) -> AsyncIterator[BaseModel]:
        raise ProviderUnavailableError("Gladia is unavailable in live mode. Check the provider configuration.")


class LabeledRun:
    """Wrap an AgentRun and label its result (for example, demo/fixture)."""

    def __init__(self, run: AgentRun, mode: DataMode, kind: ProvenanceKind, label: str):
        self.run = run
        self.mode = mode
        self.kind = kind
        self.label = label
        self.session_id = run.session_id

    @property
    def live_view_url(self) -> str | None:
        return self.run.live_view_url

    async def pause(self) -> None:
        await self.run.pause()

    async def resume(self) -> None:
        await self.run.resume()

    async def send_message(self, text: str) -> None:
        await self.run.send_message(text)

    async def wait(self) -> StepResult:
        result = await self.run.wait()
        result.data = {
            **result.data,
            "provenance": provenance_data(self.mode, self.kind, self.label),
        }
        return result


class LabeledBrowserAgents:
    def __init__(
        self, agents: BrowserAgents, mode: DataMode, kind: ProvenanceKind, label: str
    ):
        self.agents = agents
        self.mode = mode
        self.kind = kind
        self.label = label

    async def start(
        self,
        kind: StepKind,
        task: str,
        race: Race,
        profile: RunnerProfile,
        on_event: EventSink,
        ask_user: AskUser,
        mission_id: str | None = None,
        query: str = "",
        **kwargs: Any,
    ) -> LabeledRun:
        run = await self.agents.start(
            kind,
            task,
            race,
            profile,
            on_event,
            ask_user,
            mission_id=mission_id,
            query=query,
            **kwargs,
        )
        return LabeledRun(run, self.mode, self.kind, self.label)


def agents_lifecycle(agents: Any):
    """H lifecycle behind the agents (also through a `LabeledBrowserAgents` wrapper)."""
    return getattr(agents, "lifecycle", None) or getattr(getattr(agents, "agents", None), "lifecycle", None)


@dataclass
class ProviderSet:
    mode: DataMode
    search: RaceSearch
    agents: BrowserAgents
    transcriber: Transcriber
    health: dict[str, ProviderHealth] = field(default_factory=dict)

    @property
    def simulated(self) -> bool:
        return self.mode is not DataMode.live

    def health_payload(self) -> dict[str, Any]:
        """Response body for GET /api/health (G1 contract)."""
        payload = {
            "ok": True,
            "version": (os.getenv("RENDER_GIT_COMMIT") or os.getenv("RUNAI_GIT_COMMIT") or "dev")[:7],
            "service": os.getenv("RENDER_SERVICE_NAME"),
            "mode": self.mode.value,
            "simulated": self.simulated,
            "providers": {name: h.status.value for name, h in self.health.items()},
            "details": {name: h.detail for name, h in self.health.items()},
        }
        if lifecycle := agents_lifecycle(self.agents):
            payload["h_slots"] = sorted(lifecycle.slots())
            payload["h_queued"] = len(lifecycle.queued())
        return payload


def build_providers(
    mode: DataMode | None = None,
    *,
    env: Mapping[str, str] | None = None,
    replay_trace: Path | None = None,
    delay: float | None = None,
    traces_dir: Path | None = None,
) -> ProviderSet:
    env = os.environ if env is None else env
    mode = mode or select_mode(env)
    health = provider_health(env)
    delay = float(env.get("RUNAI_DEMO_DELAY", "1.5")) if delay is None else delay

    if mode is DataMode.demo:
        from runai.app.fakes import FakeBrowserAgents, FakeRaceSearch, FakeTranscriber

        return ProviderSet(
            mode,
            FakeRaceSearch(delay=delay),
            LabeledBrowserAgents(
                FakeBrowserAgents(delay=delay),
                DataMode.demo,
                ProvenanceKind.fixture,
                "Demo: simulated agent, no real data",
            ),
            FakeTranscriber(delay=delay / 3),
            health,
        )

    if mode is DataMode.replay:
        from runai.app.replay import (
            ReplayBrowserAgents,
            ReplayRaceSearch,
            ReplayTrace,
            ReplayTranscriber,
        )

        path = replay_trace or (
            Path(env["RUNAI_REPLAY_TRACE"]) if env.get("RUNAI_REPLAY_TRACE") else None
        )
        if path is None:
            path = DEFAULT_REPLAY_TRACE
            health["replay"] = ProviderHealth(
                name="replay", status=ProviderStatus.ok, detail="Default demo replay trace"
            )
        trace = ReplayTrace.load(path)
        return ProviderSet(
            mode,
            ReplayRaceSearch(trace),
            ReplayBrowserAgents(trace, delay=delay),
            ReplayTranscriber(trace),
            health,
        )

    def ready(name: str) -> bool:
        return health[name].status is ProviderStatus.ok

    if ready("linkup"):
        from runai.app.real import RealRaceSearch

        search: RaceSearch = RealRaceSearch()
    else:
        search = UnavailableRaceSearch(unavailable_message("linkup", health["linkup"]))
    if ready("h"):
        from runai.app.real import RealBrowserAgents

        agents: BrowserAgents = RealBrowserAgents(traces_dir=traces_dir)
    else:
        agents = UnavailableBrowserAgents(unavailable_message("h", health["h"]))
    if ready("gladia"):
        from runai.app.real import RealTranscriber

        transcriber: Transcriber = RealTranscriber()
    else:
        transcriber = UnavailableTranscriber(
            unavailable_message("gladia", health["gladia"])
        )
    return ProviderSet(mode, search, agents, transcriber, health)


# --- Platforms H agents may automate (V1 restrictions retained) ---


@dataclass(frozen=True)
class Platform:
    id: str
    name: str
    kind: StepKind
    hosts: tuple[str, ...]
    start_url: str | None = None
    transport_modes: frozenset[str] = frozenset()
    countries: frozenset[str] = frozenset()


PLATFORMS: tuple[Platform, ...] = (
    Platform("njuko", "Njuko", StepKind.registration, ("njuko.com",)),
    Platform(
        "accor",
        "official Accor site",
        StepKind.accommodation,
        ("all.accor.com", "accor.com"),
        "https://all.accor.com",
    ),
    Platform(
        "trenitalia",
        "trenitalia.com",
        StepKind.transport,
        ("trenitalia.com",),
        "https://www.trenitalia.com/en.html",
        transport_modes=frozenset({"train"}),
        countries=frozenset({"IT"}),
    ),
)
FORBIDDEN_HOSTS: dict[str, str] = {
    "klikego.com": "Klikego is forbidden (the guest flow creates a runner account)",
    "booking.com": "Booking.com is a forbidden aggregator",
    "expedia.com": "Expedia is a forbidden aggregator",
    "hotels.com": "Hotels.com is a forbidden aggregator",
    "airbnb.com": "Airbnb is forbidden",
    "flytap.com": "TAP is forbidden",
}
FORBIDDEN_ACCOMMODATION_SITES = ("Booking.com", "Expedia", "Hotels.com", "Airbnb")
_COUNTRY_ALIASES = {"ITALY": "IT", "ITALIE": "IT", "ITALIA": "IT", "ITA": "IT"}
_COUNTRY_NAMES_EN = {
    "AT": "austria",
    "BE": "belgium",
    "BR": "brazil",
    "CA": "canada",
    "CH": "switzerland",
    "DE": "germany",
    "DK": "denmark",
    "ES": "spain",
    "FR": "france",
    "GB": "united-kingdom",
    "GR": "greece",
    "IE": "ireland",
    "IT": "italy",
    "JP": "japan",
    "MA": "morocco",
    "NL": "netherlands",
    "PL": "poland",
    "PT": "portugal",
    "US": "united-states",
}
_ACCOR_SEARCH = "https://all.accor.com/booking/en/accor/hotels/"
_TRANSPORT_ALIASES = {
    "train": "train",
    "rail": "train",
    "flight": "flight",
    "plane": "flight",
    "avion": "flight",
    "vol": "flight",
    "bus": "bus",
    "car": "car",
    "voiture": "car",
    "none": "none",
    "aucun": "none",
    "local": "none",
}


_HOST_DOTS = str.maketrans({"。": ".", "．": ".", "｡": "."})
# Brand labels forbidden whatever the TLD (booking.fr, expedia.co.uk, airbnb.fr, ...).
_FORBIDDEN_BRANDS: dict[str, str] = {
    "booking": "Booking.com is a forbidden aggregator",
    "expedia": "Expedia is a forbidden aggregator",
    "hotels": "Hotels.com is a forbidden aggregator",
    "airbnb": "Airbnb is forbidden",
    "klikego": "Klikego is forbidden (the guest flow creates a runner account)",
    "flytap": "TAP is forbidden",
    "trainline": "Trainline is forbidden",
    "thetrainline": "Trainline is forbidden",
}
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "ac"})


def _host(url: str | None) -> str:
    """Normalized host, as a browser would read it (backslashes, dots, case, percent-encoding)."""
    if not url:
        return ""
    text = unicodedata.normalize("NFKC", str(url)).strip()
    text = re.sub(r"[\t\r\n]", "", text).replace("\\", "/")
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        return ""
    host = unquote(host).translate(_HOST_DOTS).lower().rstrip(".")
    try:
        return host.encode("idna").decode("ascii") if not host.isascii() else host
    except UnicodeError:
        return host


def host_matches(url: str | None, hosts: tuple[str, ...] | list[str]) -> bool:
    host = _host(url)
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def forbidden_reason(url: str | None) -> str | None:
    reason = next(
        (
            reason
            for host, reason in FORBIDDEN_HOSTS.items()
            if host_matches(url, (host,))
        ),
        None,
    )
    if reason:
        return reason
    labels = _host(url).split(".")
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL:
        return _FORBIDDEN_BRANDS.get(labels[-3])
    return _FORBIDDEN_BRANDS.get(labels[-2]) if len(labels) >= 2 else None


def platform(platform_id: str) -> Platform:
    return next(p for p in PLATFORMS if p.id == platform_id)


def country_code(country: str | None) -> str | None:
    if not country:
        return None
    value = country.strip().upper()
    return _COUNTRY_ALIASES.get(value, value if len(value) == 2 else None)


def normalize_transport_mode(mode: str | None) -> str | None:
    return _TRANSPORT_ALIASES.get((mode or "").strip().lower()) if mode else None


StartUrlKind = Literal["deep_link", "home"]


def _slug(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _country_slug(country: str | None) -> str:
    code = country_code(country)
    if code and code in _COUNTRY_NAMES_EN:
        return _COUNTRY_NAMES_EN[code]
    if country and len(country.strip()) > 2:
        return _slug(country)
    return ""


def accor_search_url(
    city: str | None,
    country: str | None,
    arrival: date | None,
    departure: date | None,
    adults: int = 1,
) -> str | None:
    """English Accor results page, verified in a browser:
    `https://all.accor.com/booking/en/accor/hotels/<city>-<country>?dateIn=YYYY-MM-DD&nights=N&compositions=<adults>`
    (the legacy `/ssr/app/accor/hotels/<slug>/index.en.shtml` form 301-redirects there).
    The slug is the English city and country names, lowercase ASCII joined by dashes."""
    city_slug = _slug(city or "")
    country_slug = _country_slug(country)
    if not (city_slug and country_slug and arrival and departure):
        return None
    nights = (departure - arrival).days
    if nights < 1 or adults < 1:
        return None
    query = urlencode(
        {"dateIn": arrival.isoformat(), "nights": nights, "compositions": adults}
    )
    return f"{_ACCOR_SEARCH}{quote(f'{city_slug}-{country_slug}')}?{query}"


def trenitalia_search_url(
    origin: str | None,
    destination: str | None,
    outbound: date | None,
    inbound: date | None = None,
    adults: int = 1,
) -> str | None:
    """Always None: trenitalia.com runs its search as a single-page app (form state only,
    results under lefrecce.it after a POST) with no stable shareable deep link, so the
    agent starts on the English home page `https://www.trenitalia.com/en.html`."""
    return None


@dataclass
class StepCoverage:
    kind: StepKind
    automation: Automation
    platform: Platform | None = None
    start_url: str | None = None
    limitations: list[Limitation] = field(default_factory=list)
    start_url_kind: StartUrlKind | None = None

    def __post_init__(self) -> None:
        if self.start_url and self.start_url_kind is None:
            self.start_url_kind = "home"


def registration_coverage(race: Race, official_url: str | None = None) -> StepCoverage:
    url = str(race.registration_url) if race.registration_url else None
    njuko = platform("njuko")
    if url and host_matches(url, njuko.hosts):
        return StepCoverage(StepKind.registration, Automation.automated, njuko, url)
    if url and (reason := forbidden_reason(url)):
        message = f"{reason}: register manually via the official link."
        return StepCoverage(
            StepKind.registration,
            Automation.manual,
            limitations=[
                Limitation(
                    code="registration_platform_forbidden",
                    message=message,
                    step="registration",
                    manual_url=url,
                )
            ],
        )
    if url:
        host = _host(url)
        message = f"Registration platform {host} not automated: register manually via the official link."
        return StepCoverage(
            StepKind.registration,
            Automation.manual,
            limitations=[
                Limitation(
                    code="registration_platform_unsupported",
                    message=message,
                    step="registration",
                    manual_url=url,
                )
            ],
        )
    message = "Official registration link not found by search: check the organizer's site."
    return StepCoverage(
        StepKind.registration,
        Automation.not_covered,
        limitations=[
            Limitation(
                code="registration_link_missing",
                message=message,
                step="registration",
                manual_url=official_url,
            )
        ],
    )


def _departure(brief: "TripBrief") -> date | None:
    if brief.departure:
        return brief.departure
    if brief.arrival and brief.nights:
        return brief.arrival + timedelta(days=brief.nights)
    return None


def accommodation_coverage(brief: "TripBrief | None" = None) -> StepCoverage:
    accor = platform("accor")
    deep_link = (
        accor_search_url(brief.city, brief.country, brief.arrival, _departure(brief))
        if brief
        else None
    )
    if (
        deep_link
        and host_matches(deep_link, accor.hosts)
        and not forbidden_reason(deep_link)
    ):
        return StepCoverage(
            StepKind.accommodation,
            Automation.automated,
            accor,
            deep_link,
            start_url_kind="deep_link",
        )
    return StepCoverage(
        StepKind.accommodation, Automation.automated, accor, accor.start_url
    )


def transport_coverage(
    transport_mode: str | None,
    destination_country: str | None,
    origin_country: str | None = None,
    brief: "TripBrief | None" = None,
) -> StepCoverage:
    mode = normalize_transport_mode(transport_mode)
    countries = {
        c
        for c in (country_code(destination_country), country_code(origin_country))
        if c
    }
    for candidate in PLATFORMS:
        if (
            candidate.kind is StepKind.transport
            and mode in candidate.transport_modes
            and countries & candidate.countries
        ):
            deep_link = (
                trenitalia_search_url(
                    brief.origin, brief.city, brief.arrival, brief.departure
                )
                if brief and candidate.id == "trenitalia"
                else None
            )
            if deep_link and host_matches(deep_link, candidate.hosts):
                return StepCoverage(
                    StepKind.transport,
                    Automation.automated,
                    candidate,
                    deep_link,
                    start_url_kind="deep_link",
                )
            return StepCoverage(
                StepKind.transport, Automation.automated, candidate, candidate.start_url
            )
    if mode == "none":
        return StepCoverage(
            StepKind.transport,
            Automation.not_covered,
            limitations=[
                Limitation(
                    code="transport_not_needed",
                    message="No transport to prepare (travel handled by the user).",
                    step="transport",
                )
            ],
        )
    if mode is None:
        message = f"Unrecognized transport mode {transport_mode or 'unknown'}: prepare manually."
    elif mode == "flight":
        message = "Flights not automated (no approved airline vendor, TAP forbidden): compare and book yourself on the airline's site."
    else:
        where = ", ".join(sorted(countries)) or "this destination"
        message = f"No approved official {mode} vendor for {where}: search manually on the operator's site."
    return StepCoverage(
        StepKind.transport,
        Automation.manual,
        limitations=[
            Limitation(code="transport_not_covered", message=message, step="transport")
        ],
    )
