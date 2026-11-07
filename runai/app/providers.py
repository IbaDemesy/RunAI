"""Mode de données explicite, santé des fournisseurs et plateformes couvertes par les agents.

`live` utilise uniquement H, Linkup et Gladia : une clé absente produit une erreur explicite,
jamais un repli silencieux vers les fakes. `demo` (fakes) et `replay` (trace rejouée) sont
choisis explicitement et étiquettent chaque `StepResult.data["provenance"]`.
"""

import importlib.util
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


class ProviderStatus(str, Enum):
    ok = "ok"
    missing_key = "missing_key"
    error = "error"


class ProviderUnavailableError(RuntimeError):
    """Fournisseur live inutilisable (clé absente, SDK manquant) : jamais remplacé par un fake."""


PROVIDERS = ("h", "linkup", "gladia")
_KEY_NAMES = {
    "h": "HAI_API_KEY",
    "linkup": "LINKUP_API_KEY",
    "gladia": "GLADIA_API_KEY",
}
_SDK_MODULES = {"h": "hai_agents", "linkup": "linkup", "gladia": "gladiaio_sdk"}
_LABELS = {
    "h": "H (agents navigateur)",
    "linkup": "Linkup (recherche)",
    "gladia": "Gladia (voix)",
}


class ProviderHealth(BaseModel):
    name: str
    status: ProviderStatus
    detail: str


def select_mode(env: Mapping[str, str] | None = None) -> DataMode:
    """`RUNAI_MODE` explicite, sinon `RUNAI_DEMO=1` → demo (compat V1), sinon live."""
    env = os.environ if env is None else env
    raw = (env.get("RUNAI_MODE") or "").strip().lower()
    if raw:
        try:
            return DataMode(raw)
        except ValueError:
            raise ValueError(
                f"RUNAI_MODE={raw!r} invalide : live, demo ou replay attendu"
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
    """Santé locale (sans appel réseau ni valeur de clé) : ok, missing_key ou error (SDK absent)."""
    env = os.environ if env is None else env
    health = {}
    for name in PROVIDERS:
        if not _has_key(name, env):
            status = ProviderStatus.missing_key
            detail = (
                f"{_KEY_NAMES[name]} absente : {_LABELS[name]} indisponible en live."
            )
        elif not _sdk_available(name):
            status = ProviderStatus.error
            detail = f"SDK {_SDK_MODULES[name]} non installé : pip install -r requirements.txt."
        else:
            status = ProviderStatus.ok
            detail = (
                f"{len(_h_key_names(env))} clé(s) H configurée(s)."
                if name == "h"
                else f"{_KEY_NAMES[name]} configurée."
            )
        health[name] = ProviderHealth(name=name, status=status, detail=detail)
    return health


def unavailable_message(name: str, health: ProviderHealth) -> str:
    return f"Mode live : {_LABELS[name]} indisponible ({health.status.value}). {health.detail}"


def provenance_data(
    mode: DataMode, kind: ProvenanceKind, label: str, url: str | None = None
) -> dict[str, Any]:
    """Étiquette posée dans `StepResult.data["provenance"]` : mode + `Provenance` du contrat."""
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


class LabeledRun:
    """Enveloppe un `AgentRun` et étiquette son résultat (demo/fixture par exemple)."""

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
        """Corps de `GET /api/health` (contrat G1)."""
        return {
            "ok": True,
            "mode": self.mode.value,
            "simulated": self.simulated,
            "providers": {name: h.status.value for name, h in self.health.items()},
            "details": {name: h.detail for name, h in self.health.items()},
        }


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
                "Démo : agent simulé, aucune donnée réelle",
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
        from runai.config import ROOT

        path = replay_trace or (
            Path(env["RUNAI_REPLAY_TRACE"]) if env.get("RUNAI_REPLAY_TRACE") else None
        )
        if path is None:
            path = ROOT / "fixtures" / "replay" / "default.json"
            if not path.is_file():
                raise ValueError(
                    "Replay mode: the default replay.v1 trace is missing. "
                    "Set RUNAI_REPLAY_TRACE to a recorded trace file."
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


# --- Plateformes : ce que les agents H ont le droit d'automatiser (interdictions V1 conservées) ---


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
        "site officiel Accor",
        StepKind.accommodation,
        ("all.accor.com", "accor.com"),
        "https://all.accor.com",
    ),
    Platform(
        "trenitalia",
        "trenitalia.com",
        StepKind.transport,
        ("trenitalia.com",),
        "https://www.trenitalia.com",
        transport_modes=frozenset({"train"}),
        countries=frozenset({"IT"}),
    ),
)
FORBIDDEN_HOSTS: dict[str, str] = {
    "klikego.com": "Klikego est interdit (le parcours invité crée un compte coureur)",
    "booking.com": "Booking.com est un agrégateur interdit",
    "expedia.com": "Expedia est un agrégateur interdit",
    "hotels.com": "Hotels.com est un agrégateur interdit",
    "airbnb.com": "Airbnb est interdit",
    "flytap.com": "TAP est interdit",
}
FORBIDDEN_ACCOMMODATION_SITES = ("Booking.com", "Expedia", "Hotels.com", "Airbnb")
_COUNTRY_ALIASES = {"ITALY": "IT", "ITALIE": "IT", "ITALIA": "IT", "ITA": "IT"}
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


def _host(url: str | None) -> str:
    return (urlsplit(str(url)).hostname or "").lower() if url else ""


def host_matches(url: str | None, hosts: tuple[str, ...] | list[str]) -> bool:
    host = _host(url)
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def forbidden_reason(url: str | None) -> str | None:
    return next(
        (
            reason
            for host, reason in FORBIDDEN_HOSTS.items()
            if host_matches(url, (host,))
        ),
        None,
    )


def platform(platform_id: str) -> Platform:
    return next(p for p in PLATFORMS if p.id == platform_id)


def country_code(country: str | None) -> str | None:
    if not country:
        return None
    value = country.strip().upper()
    return _COUNTRY_ALIASES.get(value, value if len(value) == 2 else None)


def normalize_transport_mode(mode: str | None) -> str | None:
    return _TRANSPORT_ALIASES.get((mode or "").strip().lower()) if mode else None


@dataclass
class StepCoverage:
    kind: StepKind
    automation: Automation
    platform: Platform | None = None
    start_url: str | None = None
    limitations: list[Limitation] = field(default_factory=list)


def registration_coverage(race: Race, official_url: str | None = None) -> StepCoverage:
    url = str(race.registration_url) if race.registration_url else None
    njuko = platform("njuko")
    if url and host_matches(url, njuko.hosts):
        return StepCoverage(StepKind.registration, Automation.automated, njuko, url)
    if url and (reason := forbidden_reason(url)):
        message = f"{reason} : inscrivez-vous vous-même via le lien officiel."
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
        message = f"Plateforme d'inscription {host} non automatisée : inscription manuelle via le lien officiel."
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
    message = "Lien d'inscription officiel non trouvé par la recherche : consultez le site de l'organisateur."
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


def accommodation_coverage() -> StepCoverage:
    accor = platform("accor")
    return StepCoverage(
        StepKind.accommodation, Automation.automated, accor, accor.start_url
    )


def transport_coverage(
    transport_mode: str | None,
    destination_country: str | None,
    origin_country: str | None = None,
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
                    message="Aucun transport à préparer (déplacement géré par l'utilisateur).",
                    step="transport",
                )
            ],
        )
    if mode is None:
        message = f"Mode de transport « {transport_mode or 'inconnu'} » non reconnu : à préparer manuellement."
    elif mode == "flight":
        message = "Vols non automatisés (aucun vendeur aérien validé, TAP interdit) : comparez et réservez vous-même sur le site de la compagnie."
    else:
        where = ", ".join(sorted(countries)) or "cette destination"
        message = f"Aucun vendeur {mode} officiel validé pour {where} : recherche manuelle sur le site de l'opérateur."
    return StepCoverage(
        StepKind.transport,
        Automation.manual,
        limitations=[
            Limitation(code="transport_not_covered", message=message, step="transport")
        ],
    )
