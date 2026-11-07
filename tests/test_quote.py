import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from runai.quote import (
    Devis,
    KlikegoError,
    NjukoError,
    OptionPayante,
    Palier,
    devis_answer_schema,
    fetch_klikego_quote,
    fetch_njuko_quote,
    fetch_njuko_quotes,
    fetch_quote,
    resolve_options,
    slug_from_url,
    verifier_devis,
    verifier_prix,
    weekend_cost,
)
from runai.quote.njuko import build_devis

FIX = Path(__file__).parent / "fixtures" / "quote"
SLUG = "wizz-air-milano-marathon-20271776152378557"
NOW = datetime(2026, 11, 7, 15, tzinfo=UTC)


def _json(name):
    return json.loads((FIX / name).read_text())


def njuko_transport(calls=None, remaining=None):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "front-api.njuko.com"
        if calls is not None:
            calls.append((req.method, req.url.path))
        p = req.url.path
        if p == f"/edition/url/{SLUG}":
            return httpx.Response(200, json=_json("njuko_milan_edition.json"))
        if p.startswith("/fields/"):
            return httpx.Response(200, json=_json("njuko_milan_fields.json"))
        if p.startswith("/prices-for-competition/"):
            return httpx.Response(200, json=_json("njuko_milan_prices.json"))
        if p.startswith("/competition/remaining/") and req.method == "POST":
            return httpx.Response(
                200, json=remaining or _json("njuko_milan_remaining.json")
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def milan() -> Devis:
    return fetch_njuko_quote(SLUG, "non comp", client=njuko_transport(), now=NOW)


def test_slug_from_url():
    assert slug_from_url(f"https://in.njuko.com/{SLUG}") == SLUG
    assert slug_from_url(f"https://in.njuko.com/{SLUG}/select_competition?x=1") == SLUG
    assert slug_from_url(SLUG) == SLUG
    with pytest.raises(NjukoError):
        slug_from_url("https://in.njuko.com/")


def test_njuko_milan_quote(milan):
    assert milan.plateforme == "njuko" and milan.source == "api"
    assert milan.course == "Wizz Air Milano Marathon 2027"
    assert "non compétitifs" in milan.epreuve
    assert str(milan.date_epreuve) == "2027-04-04"
    assert milan.url == f"https://in.njuko.com/{SLUG}"
    assert milan.palier_actuel.prix_eur == 114
    assert str(milan.palier_actuel.date_fin) == "2026-12-31"  # 22:59Z = 23:59 à Milan
    assert [(p.prix_eur, str(p.date_fin)) for p in milan.paliers_suivants] == [
        (124, "2027-02-28"),
        (131, "2027-04-03"),
    ]
    assert milan.places_restantes == 7974 and not milan.complet
    assert milan.frais_service_eur == 5 and milan.frais_inclus_dans_prix is None
    assert milan.total_minimal_eur == 114
    assert milan.rien_soumis and milan.etape_arret == "page_course"
    assert any("frais de service 5 €" in a for a in milan.avertissements)


def test_njuko_options(milan):
    assert len(milan.options) == 25
    by_cat = {o.categorie for o in milan.options}
    assert {
        "t_shirt",
        "assurance_annulation",
        "pass_participation",
        "merchandising",
    } <= by_cat
    assurance = next(o for o in milan.options if o.categorie == "assurance_annulation")
    assert assurance.prix_eur == 10 and assurance.etape == "Services" and assurance.id
    tourisme = next(o for o in milan.options if o.categorie == "pass_participation")
    assert tourisme.prix_eur == 5 and tourisme.etape == "Participation requirements"
    assert not any(o.obligatoire for o in milan.options)


def test_njuko_calls_are_read_only_and_few():
    calls = []
    fetch_njuko_quote(SLUG, "non comp", client=njuko_transport(calls), now=NOW)
    assert len(calls) == 4
    assert [m for m, _ in calls].count(
        "POST"
    ) == 1  # competition/remaining, comme la page publique
    assert all("cart" not in p and "register" not in p for _, p in calls)


def test_njuko_competition_choice():
    devis = fetch_njuko_quotes(SLUG, client=njuko_transport(), now=NOW)
    assert len(devis) == 2
    d = fetch_njuko_quote(SLUG, client=njuko_transport(), now=NOW)
    assert any("2 épreuves correspondent" in a for a in d.avertissements)
    assert (
        "RUNCARD"
        in fetch_njuko_quote(SLUG, "runcard", client=njuko_transport(), now=NOW).epreuve
    )
    with pytest.raises(NjukoError):
        fetch_njuko_quote(SLUG, "trail 100 km", client=njuko_transport(), now=NOW)


def test_njuko_tier_moves_with_time():
    d = fetch_njuko_quote(
        SLUG,
        "non comp",
        client=njuko_transport(),
        now=datetime(2027, 1, 15, tzinfo=UTC),
    )
    assert d.palier_actuel.prix_eur == 124 and [
        p.prix_eur for p in d.paliers_suivants
    ] == [131]
    # 31/12 23:30 heure de Milan = encore le palier à 114 €
    d = fetch_njuko_quote(
        SLUG,
        "non comp",
        client=njuko_transport(),
        now=datetime(2026, 12, 31, 22, 30, tzinfo=UTC),
    )
    assert d.palier_actuel.prix_eur == 114


def test_njuko_sold_out_and_closed():
    d = fetch_njuko_quote(
        SLUG, "non comp", client=njuko_transport(remaining={"remaining": 0}), now=NOW
    )
    assert d.complet and d.places_restantes == 0
    edition = _json("njuko_milan_edition.json")
    comp = edition["competitions"][0]
    with pytest.raises(NjukoError):
        build_devis(
            SLUG,
            edition,
            comp,
            _json("njuko_milan_prices.json"),
            {},
            [],
            now=datetime(2027, 5, 1, tzinfo=UTC),
        )
    late = build_devis(
        SLUG,
        edition,
        comp,
        _json("njuko_milan_prices.json"),
        {},
        [],
        now=datetime(2027, 4, 2, tzinfo=UTC),
    )
    assert late.complet and "inscriptions closes" in late.avertissements


def test_weekend_cost_milan(milan):
    cout = weekend_cost(
        milan,
        ["assurance d'annulation", "t-shirt blanc"],
        hotel_eur=94,
        transport_eur=150,
    )
    assert [x.eur for x in cout.lignes] == [114, 10, 25, 94, 150]
    assert cout.total_eur == 393
    assert cout.total_par_source == {"mesure": 149, "estime": 244}
    assert "jusqu'au 31/12/2026" in cout.lignes[0].poste
    assert any("frais de service 5 € non comptés" in a for a in cout.avertissements)


def test_weekend_cost_partial_and_agent_sources(milan):
    cout = weekend_cost(milan, hotel_eur=185.41, hotel_source="agent")
    assert cout.total_eur == 299.41
    assert cout.total_par_source == {"mesure": 114, "agent": 185.41}
    assert any("transport non chiffré" in a for a in cout.avertissements)


def test_resolve_options(milan):
    assurance = next(o for o in milan.options if o.categorie == "assurance_annulation")
    assert resolve_options(milan, [assurance.id]) == [assurance]
    assert resolve_options(milan, [assurance.nom.upper()]) == [assurance]
    with pytest.raises(ValueError, match="ambiguë"):
        resolve_options(milan, ["t-shirt"])  # blanc, bleau, technique
    with pytest.raises(ValueError, match="inconnue"):
        resolve_options(milan, ["pasta party"])


def test_mandatory_options_and_fees_out_of_price():
    d = Devis(
        plateforme="njuko",
        course="X",
        epreuve="10 km",
        url="https://in.njuko.com/x",
        palier_actuel=Palier(prix_eur=20),
        frais_service_eur=1.5,
        frais_inclus_dans_prix=False,
        options=[
            OptionPayante(
                nom="Licence journée",
                categorie="pass_participation",
                prix_eur=3,
                obligatoire=True,
            ),
            OptionPayante(nom="Repas", categorie="repas", prix_eur=None),
        ],
        total_minimal_eur=24.5,
        etape_arret="panier",
        raison_arret="paiement",
        rien_soumis=True,
        source="api",
    )
    assert verifier_devis(d).ok
    cout = weekend_cost(d, ["repas"])
    assert cout.total_eur == 24.5
    assert any("sans prix" in a for a in cout.avertissements)
    assert verifier_prix(24.5, d).ok and not verifier_prix(23, d).ok


def test_verifier_prix(milan):
    assert verifier_prix(114, milan).ok
    v = verifier_prix(119, milan)  # frais de 5 € peut-être ajoutés au panier
    assert v.ok and any("inclut les frais" in a for a in v.avertissements)
    v = verifier_prix(124, milan)
    assert not v.ok and "palier suivant (fin 2027-02-28)" in v.ecarts[0]
    assert verifier_prix(149, milan, ["assurance d'annulation", "t-shirt blanc"]).ok


def _agent(milan: Devis, **kw) -> Devis:
    d = milan.model_copy(
        deep=True, update={"source": "agent_h", "etape_arret": "panier", **kw}
    )
    return d


def test_verifier_devis_against_source(milan):
    assert verifier_devis(_agent(milan), milan).ok
    agent = _agent(
        milan,
        palier_actuel=Palier(prix_eur=131),
        total_minimal_eur=131,
        options=[
            OptionPayante(
                nom="Souhaitez-vous acheter l'assurance d'annulation de participation?",
                prix_eur=12,
            )
        ],
    )
    v = verifier_devis(agent, milan)
    assert not v.ok and v.attendu_eur == 114
    assert any("agent 131 €, source 114 €" in e and "2027-04-03" in e for e in v.ecarts)
    assert any("agent 12 €, source 10 €" in e for e in v.ecarts)


def test_verifier_devis_internal_checks(milan):
    v = verifier_devis(_agent(milan, total_minimal_eur=100, rien_soumis=False))
    assert len(v.ecarts) == 2
    v = verifier_devis(_agent(milan, palier_actuel=Palier(prix_eur=114), complet=True))
    assert v.ok and len(v.avertissements) == 2


def test_answer_schema_is_json_schema():
    s = devis_answer_schema()
    assert s["type"] == "object" and "palier_actuel" in s["required"]
    assert json.dumps(s)


def klikego_client(calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if req.url.path.startswith("/inscription/"):
            return httpx.Response(
                200, text=(FIX / "klikego_royan_event.html").read_text()
            )
        if req.url.path == "/v8/evenement/epreuve.jsp":
            assert req.url.params["heat"] == "1447756132652"
            return httpx.Response(
                200, text=(FIX / "klikego_royan_fiche_marathon.html").read_text()
            )
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_klikego_royan():
    calls = []
    url = "https://www.klikego.com/inscription/11eme-marathon-royan-u-cote-de-beaute-2027/running-course-a-pied/1446588740963-17"
    d = fetch_quote(url, "Marathon Royan", client=klikego_client(calls), now=NOW)
    assert len(calls) == 2
    assert d.plateforme == "klikego" and d.epreuve == "Marathon Royan U Côte de Beauté"
    assert d.palier_actuel.prix_eur == 65 and [
        p.prix_eur for p in d.paliers_suivants
    ] == [70]
    assert d.frais_service_eur == 3 and d.frais_inclus_dans_prix is False
    assert d.total_minimal_eur == 68 and not d.complet
    assert {(o.categorie, o.prix_eur) for o in d.options} == {
        ("assurance_annulation", 8),
        ("t_shirt", 12),
    }
    cout = weekend_cost(
        d, ["assurance annulation", "t-shirt"], hotel_eur=63, transport_eur=180
    )
    assert cout.total_eur == 331  # même total que le spike
    assert verifier_prix(68, d).ok


def test_fetch_quote_dispatch():
    with pytest.raises(ValueError):
        fetch_quote("https://www.example.com/race")
    with pytest.raises(ValueError):
        fetch_quote("https://evilklikego.com/x")
    with pytest.raises(ValueError):
        fetch_quote("https://evilnjuko.com/x")
    with pytest.raises(KlikegoError):
        fetch_klikego_quote("http://169.254.169.254/latest", client=klikego_client([]))


def test_klikego_does_not_follow_redirects():
    def handler(req):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})

    with pytest.raises(httpx.HTTPStatusError):
        fetch_klikego_quote(
            "https://www.klikego.com/inscription/x/y/1-1",
            client=httpx.Client(
                transport=httpx.MockTransport(handler), follow_redirects=True
            ),
        )


@pytest.mark.skipif(
    os.getenv("RUNAI_NETWORK_TESTS") != "1",
    reason="réseau : RUNAI_NETWORK_TESTS=1 pour lancer",
)
def test_network_milan():
    d = fetch_njuko_quote(SLUG, "non comp")
    assert d.palier_actuel.prix_eur > 0 and d.options


def test_njuko_fee_inclusion_negation():
    from runai.quote.njuko import _frais

    assert _frais(["5 euros de frais de service non inclus dans le prix"]) == (
        5.0,
        False,
    )
    assert _frais(["frais de service inclus (5 euros)"]) == (5.0, True)


def test_njuko_hidden_sections_and_free_choices():
    from runai.quote.njuko import _options

    paid = {
        "data": {"values": [{"price": 5}]},
        "validateOptionsFormGroup": {"required": True},
    }
    forms = [
        {
            "fields": [
                {
                    "label": "cache",
                    "validateOptionsFormGroup": {"visible": False},
                    "fields": [dict(paid, label="enfant caché")],
                },
                dict(paid, label="obligatoire"),
                {
                    "label": "dossard",
                    "validateOptionsFormGroup": {"required": True},
                    "data": {"values": [{"price": 5}, {"price": 0}]},
                },
            ]
        }
    ]
    opts = {o.nom: o for o in _options(forms, "c1")}
    assert set(opts) == {"obligatoire", "dossard"}
    assert opts["obligatoire"].obligatoire and not opts["dossard"].obligatoire
