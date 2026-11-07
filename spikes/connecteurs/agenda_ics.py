"""Disponibilités du coureur à partir d'un fichier iCal (.ics) et export du week-end de course.

Sans dépendance. Gère : événements datés ou « journée entière », UTC, TZID IANA, heure flottante,
TRANSP:TRANSPARENT et STATUS:CANCELLED ignorés, RRULE DAILY/WEEKLY (INTERVAL, COUNT, UNTIL, BYDAY)
et EXDATE. Les autres récurrences ne gardent que la première occurrence (signalé dans `warnings`).
En production : `icalendar` + `recurring-ical-events`.

Usage :
    python agenda_ics.py --ics fixtures/agenda_camille.ics --debut 2026-11-09 --fin 2027-05-31 \
        --courses fixtures/courses_candidates.json --niveau intermediaire
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from niveau import semaines_preparation_min

TZ_DEFAUT = ZoneInfo("Europe/Paris")
JOURS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


@dataclass
class Occupation:
    debut: datetime
    fin: datetime
    titre: str


@dataclass
class Agenda:
    occupations: list[Occupation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _deplier(texte: str) -> list[str]:
    lignes: list[str] = []
    for brute in texte.replace("\r\n", "\n").split("\n"):
        if brute[:1] in (" ", "\t") and lignes:
            lignes[-1] += brute[1:]
        elif brute:
            lignes.append(brute)
    return lignes


def _propriete(ligne: str) -> tuple[str, dict[str, str], str]:
    tete, _, valeur = ligne.partition(":")
    nom, *params = tete.split(";")
    return nom.upper(), dict(p.split("=", 1) for p in params if "=" in p), valeur


def _date_heure(valeur: str, params: dict[str, str], tz: ZoneInfo) -> tuple[datetime, bool]:
    valeur = valeur.strip()
    if params.get("VALUE") == "DATE" or len(valeur) == 8:
        d = datetime.strptime(valeur[:8], "%Y%m%d")
        return d.replace(tzinfo=tz), True
    if valeur.endswith("Z"):
        return datetime.strptime(valeur, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False
    zone = ZoneInfo(params["TZID"]) if "TZID" in params else tz
    return datetime.strptime(valeur, "%Y%m%dT%H%M%S").replace(tzinfo=zone), False


def _rrule(regle: str) -> dict[str, str]:
    return dict(p.split("=", 1) for p in regle.split(";") if "=" in p)


def _occurrences(debut: datetime, regle: dict[str, str], exdates: set[datetime], jusqua: datetime):
    freq = regle.get("FREQ")
    pas = int(regle.get("INTERVAL", "1"))
    compte = int(regle["COUNT"]) if "COUNT" in regle else None
    until = None
    if "UNTIL" in regle:
        until, _ = _date_heure(regle["UNTIL"], {}, debut.tzinfo)  # type: ignore[arg-type]
    jours = sorted(JOURS[j[-2:]] for j in regle.get("BYDAY", "").split(",") if j) or [debut.weekday()]
    emis = 0
    if freq == "DAILY":
        candidats = (debut + timedelta(days=i * pas) for i in range(100000))
    else:
        lundi = debut - timedelta(days=debut.weekday())

        def _hebdo():
            semaine = 0
            while True:
                for j in jours:
                    yield lundi + timedelta(weeks=semaine * pas, days=j)
                semaine += 1

        candidats = _hebdo()
    for occ in candidats:
        if occ < debut:
            continue
        if (until and occ > until) or occ > jusqua or (compte is not None and emis >= compte):
            return
        emis += 1
        if occ not in exdates:
            yield occ


def lire_ics(texte: str, jusqua: datetime | None = None, tz: ZoneInfo = TZ_DEFAUT) -> Agenda:
    jusqua = jusqua or datetime(2100, 1, 1, tzinfo=tz)
    agenda = Agenda()
    courant: dict | None = None
    for ligne in _deplier(texte):
        nom, params, valeur = _propriete(ligne)
        if nom == "BEGIN" and valeur == "VEVENT":
            courant = {"exdates": set()}
        elif nom == "END" and valeur == "VEVENT" and courant is not None:
            _ajouter(agenda, courant, jusqua)
            courant = None
        elif courant is not None:
            if nom in ("DTSTART", "DTEND"):
                courant[nom] = _date_heure(valeur, params, tz)
            elif nom == "DURATION":
                courant[nom] = valeur
            elif nom == "EXDATE":
                for v in valeur.split(","):
                    courant["exdates"].add(_date_heure(v, params, tz)[0])
            elif nom in ("SUMMARY", "RRULE", "TRANSP", "STATUS"):
                courant[nom] = valeur
    return agenda


def _ajouter(agenda: Agenda, ev: dict, jusqua: datetime) -> None:
    if ev.get("TRANSP", "").upper() == "TRANSPARENT" or ev.get("STATUS", "").upper() == "CANCELLED":
        return
    if "DTSTART" not in ev:
        return
    debut, journee = ev["DTSTART"]
    if "DTEND" in ev:
        fin = ev["DTEND"][0]
    elif journee:
        fin = debut + timedelta(days=1)
    else:
        fin = debut
    duree = fin - debut
    titre = ev.get("SUMMARY", "(occupé)")
    if "RRULE" not in ev:
        agenda.occupations.append(Occupation(debut, fin, titre))
        return
    regle = _rrule(ev["RRULE"])
    if regle.get("FREQ") not in ("DAILY", "WEEKLY") or any(
        k in regle for k in ("BYMONTHDAY", "BYSETPOS", "BYMONTH")
    ):
        agenda.warnings.append(f"RRULE non gérée ({ev['RRULE']}) pour « {titre} » : 1re occurrence seule")
        agenda.occupations.append(Occupation(debut, fin, titre))
        return
    for occ in _occurrences(debut, regle, ev["exdates"], jusqua):
        agenda.occupations.append(Occupation(occ, occ + duree, titre))


def _samedis(debut: date, fin: date):
    d = debut + timedelta(days=(5 - debut.weekday()) % 7)
    while d <= fin:
        yield d
        d += timedelta(days=7)


def week_ends(
    agenda: Agenda,
    debut: date,
    fin: date,
    tz: ZoneInfo = TZ_DEFAUT,
    plage: tuple[time, time] = (time(6, 0), time(20, 0)),
) -> list[dict]:
    """Un week-end est libre si rien n'occupe samedi `plage[0]` -> dimanche `plage[1]` (heure locale)."""
    resultat = []
    for samedi in _samedis(debut, fin):
        dimanche = samedi + timedelta(days=1)
        fenetre = (datetime.combine(samedi, plage[0], tz), datetime.combine(dimanche, plage[1], tz))
        vendredi = (datetime.combine(samedi - timedelta(days=1), time(17, 0), tz), fenetre[0])
        conflits = [o.titre for o in agenda.occupations if o.debut < fenetre[1] and o.fin > fenetre[0]]
        conflits_vendredi = [o.titre for o in agenda.occupations if o.debut < vendredi[1] and o.fin > vendredi[0]]
        resultat.append(
            {
                "samedi": samedi.isoformat(),
                "libre": not conflits,
                "vendredi_soir_libre": not conflits_vendredi,
                "conflits": sorted(set(conflits)),
            }
        )
    return resultat


def filtrer_courses(courses: list[dict], weekends: list[dict], aujourdhui: date, niveau: str) -> list[dict]:
    par_samedi = {w["samedi"]: w for w in weekends}
    sortie = []
    for c in courses:
        jour = date.fromisoformat(c["date"])
        samedi = (jour - timedelta(days=(jour.weekday() - 5) % 7)).isoformat()
        semaines = (jour - aujourdhui).days // 7
        mini = semaines_preparation_min(c["distance_km"], niveau, c.get("d_plus_m", 0))
        w = par_samedi.get(samedi)
        if w is None:
            statut, raison = "hors_fenetre", "date hors de la fenêtre d'agenda lue"
        elif not w["libre"]:
            statut, raison = "conflit_agenda", "week-end pris : " + ", ".join(w["conflits"])
        elif semaines < mini:
            statut, raison = "trop_tot", f"{semaines} semaines de préparation, il en faut au moins {mini}"
        else:
            statut = "compatible"
            raison = f"week-end libre, {semaines} semaines de préparation (minimum {mini})"
            if w["vendredi_soir_libre"]:
                raison += ", départ possible vendredi soir"
        sortie.append({**c, "statut": statut, "raison": raison})
    return sorted(sortie, key=lambda c: (c["statut"] != "compatible", c["date"]))


def _echapper(texte: str) -> str:
    return texte.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _plier(ligne: str) -> str:
    brut = ligne.encode("utf-8")
    morceaux, courant = [], b""
    for ch in ligne:
        b = ch.encode("utf-8")
        if len(courant) + len(b) > (75 if not morceaux else 74):
            morceaux.append(courant)
            courant = b""
        courant += b
    morceaux.append(courant)
    return "\r\n ".join(m.decode("utf-8") for m in morceaux) if len(brut) > 75 else ligne


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def construire_ics(evenements: list[dict], nom: str = "RunAI - week-end de course") -> str:
    """evenements : {titre, debut, fin (datetime aware), lieu?, description?, rappel_min?}."""
    maintenant = _utc(datetime.now(UTC))
    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RunAI//spike connecteurs//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_echapper(nom)}",
    ]
    for ev in evenements:
        uid = hashlib.sha1(f"{ev['titre']}{ev['debut'].isoformat()}".encode()).hexdigest()[:16]
        lignes += [
            "BEGIN:VEVENT",
            f"UID:{uid}@runai.example",
            f"DTSTAMP:{maintenant}",
            f"DTSTART:{_utc(ev['debut'])}",
            f"DTEND:{_utc(ev['fin'])}",
            f"SUMMARY:{_echapper(ev['titre'])}",
        ]
        if ev.get("lieu"):
            lignes.append(f"LOCATION:{_echapper(ev['lieu'])}")
        if ev.get("description"):
            lignes.append(f"DESCRIPTION:{_echapper(ev['description'])}")
        if ev.get("rappel_min"):
            lignes += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{_echapper(ev['titre'])}",
                f"TRIGGER:-PT{int(ev['rappel_min'])}M",
                "END:VALARM",
            ]
        lignes.append("END:VEVENT")
    lignes.append("END:VCALENDAR")
    return "\r\n".join(_plier(lg) for lg in lignes) + "\r\n"


def evenements_week_end(recap: dict, tz: ZoneInfo = TZ_DEFAUT) -> list[dict]:
    """Transforme le récap RunAI (aller, retrait dossard, course, retour) en événements d'agenda."""
    def dt(s: str) -> datetime:
        return datetime.fromisoformat(s).replace(tzinfo=tz)

    evs = []
    for cle, titre in (("aller", "Trajet aller"), ("retrait_dossard", "Retrait du dossard"),
                       ("course", "Course"), ("retour", "Trajet retour")):
        if cle in recap:
            e = recap[cle]
            evs.append({
                "titre": f"{titre} - {recap['nom_course']}" if cle == "course" else titre,
                "debut": dt(e["debut"]),
                "fin": dt(e["fin"]),
                "lieu": e.get("lieu", ""),
                "description": e.get("description", ""),
                "rappel_min": e.get("rappel_min"),
            })
    if "hotel" in recap:
        h = recap["hotel"]
        evs.append({"titre": f"Hôtel : {h['nom']}", "debut": dt(h["arrivee"]), "fin": dt(h["depart"]),
                    "lieu": h.get("adresse", ""), "description": "Réservation à confirmer par le coureur."})
    return evs


def main() -> None:
    ici = Path(__file__).parent
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ics", default=str(ici / "fixtures/agenda_camille.ics"))
    p.add_argument("--debut", default="2026-11-09")
    p.add_argument("--fin", default="2027-05-31")
    p.add_argument("--courses", default=str(ici / "fixtures/courses_candidates.json"))
    p.add_argument("--niveau", default="intermediaire")
    p.add_argument("--recap", default=str(ici / "fixtures/recap_weekend.json"))
    p.add_argument("--out", default=str(ici / "out"))
    a = p.parse_args()
    debut, fin = date.fromisoformat(a.debut), date.fromisoformat(a.fin)
    agenda = lire_ics(Path(a.ics).read_text(encoding="utf-8"), datetime.combine(fin, time(23, 59), TZ_DEFAUT))
    wk = week_ends(agenda, debut, fin)
    courses = filtrer_courses(json.loads(Path(a.courses).read_text(encoding="utf-8")), wk, debut, a.niveau)
    Path(a.out).mkdir(exist_ok=True)
    ics = construire_ics(evenements_week_end(json.loads(Path(a.recap).read_text(encoding="utf-8"))))
    (Path(a.out) / "weekend.ics").write_text(ics, encoding="utf-8", newline="")
    print(json.dumps({
        "occupations_lues": len(agenda.occupations),
        "warnings": agenda.warnings,
        "week_ends_libres": [w["samedi"] for w in wk if w["libre"]],
        "nb_week_ends": len(wk),
        "courses": [{k: c[k] for k in ("nom", "date", "statut", "raison")} for c in courses],
        "ics_exporte": str(Path(a.out) / "weekend.ics"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
