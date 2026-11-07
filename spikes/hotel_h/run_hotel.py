"""Spike RunAI axe 3 : hotel Accor via un agent H (h/web-surfer-pro).

Un run = une session H. Le script verifie le quota, lance l'agent sur all.accor.com,
envoie une correction en cours de route (send_message), journalise les evenements,
recupere la derniere capture et annule toujours la session a la fin.
Aucun paiement, aucune reservation : l'agent s'arrete avant la saisie de carte.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from hai_agents import Client
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
AGENT = "h/web-surfer-pro"
CORRECTION = (
    "Correction du coureur : l'hotel doit etre a moins de 10 min a pied du depart "
    "(environ 800 m maximum). Si ton choix actuel est plus loin, change d'hotel."
)

CORRECTION_FERME = (
    "STOP, NOUVELLE CONTRAINTE PRIORITAIRE du coureur : l'hotel doit etre a moins de 10 min a pied "
    "du depart (800 m maximum, distance affichee par Accor). Verifie l'hotel que tu as choisi : "
    "s'il est a plus de 800 m, abandonne-le, reviens a la liste des resultats et prends le moins cher "
    "des hotels a 800 m ou moins. Annonce dans ta prochaine reflexion quel hotel tu gardes et pourquoi."
)

PROFILE = {
    "civilite": "Mme",
    "prenom": "Camille",
    "nom": "Martin",
    "email": "camille.martin@example.com",
    "telephone": "+33 6 00 00 00 00",
    "pays": "France",
    "date_naissance": "12/05/1994",
    "nationalite": "Francaise",
    "adresse": "1 rue de l'Exemple, 75011 Paris",
}

CRITERES = {
    "compromis": "Choisis le meilleur compromis distance/prix.",
    "moins_cher": "Choisis le moins cher des hotels compares.",
}


class OptionComparee(BaseModel):
    hotel: str
    distance_estimee_depart: str = Field(
        description="distance et temps a pied estimes jusqu'au depart"
    )
    prix: str = Field(description="prix total du sejour affiche, avec devise")


class HotelAnswer(BaseModel):
    hotel: str
    adresse: str
    distance_estimee_depart: str = Field(
        description="distance et temps a pied estimes jusqu'au depart"
    )
    prix: str = Field(description="prix total du sejour affiche, avec devise")
    conditions_annulation: str
    url_finale: str = Field(description="URL de la page finale atteinte")
    capture: str = Field(
        description="description de ce qui est visible a l'ecran sur la page finale"
    )
    options_comparees: list[OptionComparee] = Field(
        description="les 3 ou 4 hotels compares"
    )
    correction_recue: bool = Field(
        description="true si un message de correction du coureur a ete recu"
    )
    correction_appliquee: str = Field(
        description="comment la correction a ete prise en compte, ou 'aucune'"
    )
    etape_atteinte: str = Field(
        description="ex: page coordonnees remplie, page paiement affichee"
    )
    blocages: list[str] = Field(
        description="captcha, popups, Cloudflare, champs obligatoires bloquants..."
    )


def build_task(race: dict[str, str], critere: str = "compromis") -> str:
    p = PROFILE
    return f"""Tu prepares l'hotel d'un coureur pour {race["course"]} ({race["date_course"]}).
Depart de la course : {race["adresse_depart"]}.
Sejour : arrivee le {race["arrivee"]}, depart le {race["depart"]}, 1 adulte, 1 chambre.

1. Va sur https://all.accor.com et cherche les hotels pres de ce lieu de depart pour ces dates
   (ferme ou refuse les popups cookies/pubs ; refuse les cookies non essentiels).
2. Compare 3 ou 4 hotels disponibles selon la distance a pied jusqu'au depart et le prix total.
   {CRITERES[critere]}
3. Choisis le tarif le plus flexible raisonnable (annulation gratuite si possible) et note les conditions d'annulation.
4. Continue en tant qu'invite (SANS creer de compte, sans te connecter, sans cocher d'adhesion au programme
   de fidelite ni d'opt-in marketing) et remplis les coordonnees avec ce profil FICTIF :
   {p["civilite"]} {p["prenom"]} {p["nom"]}, e-mail {p["email"]}, telephone {p["telephone"]}, pays {p["pays"]},
   nationalite {p["nationalite"]} (liste deroulante triee par ordre alphabetique),
   adresse de facturation {p["adresse"]}.
5. Arrete-toi sur la page de paiement (ou la derniere page avant toute saisie de carte bancaire).
   INTERDIT : saisir des donnees de carte, cliquer sur le bouton final de reservation/paiement,
   creer un compte, cocher des cases de conditions generales ou de consentement (signale-les seulement).
   Si un compte, un vrai e-mail, un captcha ou une verification est exige, arrete-toi et signale-le.
6. Reponds au format JSON demande. Le coureur peut t'envoyer une correction en cours de route : applique-la.
"""


def wait_for_slot(
    client: Client, max_wait_s: int = 600, every_s: int = 60
) -> dict[str, Any]:
    t0 = time.time()
    while True:
        q = client.sessions.get_session_quota()
        info = {
            "limit": q.limit,
            "active": q.active,
            "available": q.available,
            "waited_s": round(time.time() - t0),
        }
        print(f"[quota] {info}", flush=True)
        if (q.available or 0) > 0:
            return info
        if time.time() - t0 >= max_wait_s:
            raise SystemExit(f"Aucun slot H libre apres {max_wait_s}s : {info}")
        time.sleep(every_s)


def short(ev: dict[str, Any]) -> str:
    data = ev.get("data") or {}
    if not isinstance(data, dict):
        return str(data)[:300]
    parts = []
    for key in ("kind", "status", "live_view_url"):
        if data.get(key):
            parts.append(f"{key}={data[key]}")
    for key in ("content", "reasoning_content", "text"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(f"{key}={val.strip()[:400]}")
    for tr in data.get("tool_reqs") or []:
        parts.append(
            f"tool={tr.get('name')} args={json.dumps(tr.get('arguments'), ensure_ascii=False)[:300]}"
        )
    meta = data.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("url"):
        parts.append(f"url={meta['url']}")
    return " | ".join(parts) or json.dumps(data, ensure_ascii=False)[:300]


def find_images(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        if obj.get("type") == "url" and isinstance(obj.get("source"), str):
            out.append(obj["source"])
        for v in obj.values():
            find_images(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_images(v, out)


def find_urls(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "url" and isinstance(v, str) and v.startswith("http"):
                out.append(v)
            else:
                find_urls(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_urls(v, out)


def download(url: str, dest: Path) -> str | None:
    headers = (
        {"Authorization": f"Bearer {os.environ['HAI_API_KEY']}"}
        if "hcompany.ai" in url
        else {}
    )
    try:
        r = httpx.get(url, headers=headers, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        return str(dest.relative_to(HERE))
    except Exception as exc:  # noqa: BLE001
        return f"echec telechargement: {type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="nom du run, ex: run1")
    ap.add_argument("--race", default=str(HERE / "race.json"))
    ap.add_argument(
        "--correction-after-s", type=float, default=90.0, help="<0 pour ne pas corriger"
    )
    ap.add_argument(
        "--correction-on-url",
        default=None,
        help="envoie la correction des qu'une URL contient ce texte",
    )
    ap.add_argument(
        "--correction-ferme",
        action="store_true",
        help="message de correction imperatif",
    )
    ap.add_argument(
        "--pause-avant-correction",
        action="store_true",
        help="pause H puis send_message",
    )
    ap.add_argument("--critere", choices=sorted(CRITERES), default="compromis")
    ap.add_argument("--max-time-s", type=float, default=900.0)
    ap.add_argument("--max-steps", type=int, default=150)
    args = ap.parse_args()

    if not os.environ.get("HAI_API_KEY"):
        print("HAI_API_KEY manquante", file=sys.stderr)
        return 2
    race = json.loads(Path(args.race).read_text())
    out_dir = HERE / "results" / args.run
    out_dir.mkdir(parents=True, exist_ok=True)

    client = Client()
    quota = wait_for_slot(client)
    t_start = time.time()
    handle = client.start_session(
        agent=AGENT,
        messages=build_task(race, args.critere),
        answer_schema=HotelAnswer,
        max_time_s=args.max_time_s,
        max_steps=args.max_steps,
        timezone="Europe/Paris",
        queue=False,
    )
    sid = handle.id
    print(f"[session] {sid}", flush=True)
    events: list[dict[str, Any]] = []
    correction_at: float | None = None
    live_view = None
    status = None
    changes = None
    idx = 0
    url_trigger_hit = False
    pause_latency = None
    correction_text = None
    try:
        with (out_dir / "events.log").open("w") as log:
            while True:
                changes = handle.changes(
                    from_index=idx, include_events=True, wait_for_seconds=10
                )
                if changes is not None:
                    for ev in changes.new_events or []:
                        d = ev.model_dump(mode="json")
                        events.append(d)
                        rel = time.time() - t_start
                        line = f"[{rel:6.1f}s] {d.get('type')} {short(d)}"
                        log.write(line + "\n")
                        log.flush()
                        print(line[:250], flush=True)
                        seen: list[str] = []
                        find_urls(d, seen)
                        if args.correction_on_url and any(
                            args.correction_on_url in u for u in seen
                        ):
                            url_trigger_hit = True
                        if d.get("type") == "LiveViewUrlEvent":
                            live_view = (d.get("data") or {}).get("live_view_url")
                    idx = (changes.first_index or idx) + len(changes.new_events or [])
                    status = changes.status
                    if status in (
                        "completed",
                        "failed",
                        "cancelled",
                        "timed_out",
                        "interrupted",
                        "idle",
                    ):
                        break
                if time.time() - t_start > args.max_time_s + 300:
                    print("[garde-fou] duree max depassee, arret", flush=True)
                    break
                if correction_at is None and (
                    url_trigger_hit
                    if args.correction_on_url
                    else args.correction_after_s >= 0
                    and time.time() - t_start >= args.correction_after_s
                ):
                    text = CORRECTION_FERME if args.correction_ferme else CORRECTION
                    if args.pause_avant_correction:
                        t_p = time.time()
                        handle.pause()
                        for _ in range(60):
                            if handle.status().status == "paused":
                                break
                            time.sleep(1)
                        pause_latency = round(time.time() - t_p, 1)
                        print(
                            f"[pause] statut={handle.status().status} apres {pause_latency}s",
                            flush=True,
                        )
                        log.write(f">>> PAUSE: {pause_latency}s\n")
                    handle.send_message(text)
                    if args.pause_avant_correction:
                        time.sleep(5)
                        st_after = handle.status().status
                        print(
                            f"[pause] statut 5 s apres send_message : {st_after}",
                            flush=True,
                        )
                        log.write(f">>> STATUT 5s APRES MESSAGE: {st_after}\n")
                        if st_after == "paused":
                            handle.resume()
                    correction_text = text
                    correction_at = time.time() - t_start
                    print(f"[correction] envoyee a {correction_at:.1f}s", flush=True)
                    log.write(
                        f"[{correction_at:6.1f}s] >>> CORRECTION ENVOYEE: {text}\n"
                    )
    finally:
        try:
            handle.cancel()
            print("[cancel] ok", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[cancel] {type(exc).__name__}: {exc}", flush=True)

    duration = time.time() - t_start
    st = handle.status().model_dump(mode="json")
    answer = changes.answer if changes is not None else None
    if hasattr(answer, "model_dump"):
        answer = answer.model_dump(mode="json")
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            pass

    images: list[str] = []
    find_images(events, images)
    urls: list[str] = []
    find_urls(events, urls)
    last_capture = (
        download(images[-1], out_dir / "last_screenshot.png") if images else None
    )
    policy_steps = sum(
        1 for e in events if (e.get("data") or {}).get("kind") == "policy_event"
    )
    post_corr_mentions = []
    if correction_at is not None:
        for e in events:
            txt = json.dumps(e.get("data"), ensure_ascii=False).lower()
            if "10 min" in txt or "800 m" in txt or "correction" in txt:
                post_corr_mentions.append(e.get("timestamp"))

    result = {
        "run": args.run,
        "session_id": sid,
        "agent": AGENT,
        "quota_avant": quota,
        "status_final_stream": status,
        "status_api": st,
        "outcome": getattr(changes, "outcome", None),
        "error": getattr(changes, "error", None),
        "duree_s": round(duration, 1),
        "nb_evenements": len(events),
        "nb_etapes_policy": policy_steps,
        "nb_captures": len(images),
        "critere": args.critere,
        "declencheur_correction": args.correction_on_url
        or f"{args.correction_after_s}s",
        "correction_texte": correction_text,
        "pause_latence_s": pause_latency,
        "correction_envoyee_a_s": round(correction_at, 1) if correction_at else None,
        "evenements_mentionnant_correction": post_corr_mentions,
        "live_view_url": live_view,
        "urls_vues": list(dict.fromkeys(u for u in urls if "accor" in u))[-15:],
        "derniere_capture": last_capture,
        "metrics": changes.metrics.model_dump(mode="json")
        if changes is not None and changes.metrics
        else None,
        "answer": answer,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    (out_dir / "events.json").write_text(
        json.dumps(events, ensure_ascii=False, indent=1)
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "status_api"},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
