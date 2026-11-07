"""Boucle Devin : run H en échec -> trace -> réparation -> nouvelle révision du skill -> relance.

Usage : python boucle.py setup|run LABEL|trace LABEL|repair LABEL|update|report
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import devin_repair
import h_api
import httpx

HERE = Path(__file__).parent
RESULTS = HERE / "results"
SKILL = "runai-books-runbook"
AGENT = "runai-boucle-books"
SKILL_DESC = (
    "Use when the task is about books.toscrape.com: RunAI runbook with the allowed pages "
    "and where each field is read. Always load it before acting on this site."
)
BOOK = "A Light in the Attic"
PRODUCT_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
TASK = (
    f"Sur https://books.toscrape.com/, trouve le livre « {BOOK} » et rends son titre, son prix, "
    "son UPC et le nombre d'exemplaires en stock. Applique le runbook RunAI de ce site."
)
ANSWER_FORMAT = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok", "bloque"]},
        "titre": {"type": ["string", "null"]},
        "prix": {"type": ["string", "null"]},
        "upc": {"type": ["string", "null"]},
        "stock": {"type": ["integer", "null"]},
        "raison": {"type": "string"},
    },
    "required": ["status", "titre", "prix", "upc", "stock", "raison"],
}
AGENT_SPEC = {
    "name": AGENT,
    "description": "RunAI spike: lit une fiche livre en suivant le runbook versionné du site.",
    "environments": ["h/browser"],
    "model": "holo4-27b",
    "skills": ["h/answering", "h/planning", SKILL],
    "instructions": (
        f"Tu travailles pour RunAI. Avant toute action, charge le skill {SKILL} et applique-le "
        "strictement, y compris sa liste blanche de pages. Lecture seule : ne remplis aucun formulaire, "
        "n'ajoute rien au panier. Ne demande rien à l'utilisateur."
    ),
    "answer_format": ANSWER_FORMAT,
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def journal(step: str, **data) -> None:
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / "journal.jsonl").open("a") as f:
        f.write(json.dumps({"step": step, **data}, ensure_ascii=False) + "\n")


def ground_truth() -> dict:
    html = httpx.get(PRODUCT_URL, timeout=30).text
    return {
        "upc": re.search(r"<th>UPC</th><td>([^<]+)</td>", html).group(1),
        "stock": int(re.search(r"In stock \((\d+) available\)", html).group(1)),
    }


def validate(answer) -> dict:
    gt = ground_truth()
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            answer = {}
    answer = answer or {}
    checks = {
        "status_ok": answer.get("status") == "ok",
        "upc_ok": answer.get("upc") == gt["upc"],
        "stock_ok": answer.get("stock") == gt["stock"],
    }
    return {"success": all(checks.values()), "checks": checks, "ground_truth": gt, "answer": answer}


def cmd_setup() -> None:
    c = h_api.client()
    t0 = now()
    body = (HERE / "skills/books_runbook_v1.md").read_text()
    rev = h_api.put_skill(c, SKILL, SKILL_DESC, body, "v1: runbook initial (liste blanche incomplète)")
    arev = h_api.put_agent(c, AGENT_SPEC, "agent du spike boucle_devin, skill en révision latest")
    journal("setup", t_start=t0, t_end=now(), skill_revision=rev, agent_revision=arev)
    print("skill", SKILL, "revision", rev, "| agent", AGENT, "revision", arev)


def cmd_run(label: str) -> None:
    c = h_api.client()
    t0 = now()
    quota = h_api.wait_for_slot(c)
    print("quota", quota)
    s = h_api.run_session(c, AGENT, TASK, max_steps=40, max_time_s=420)
    v = validate(s.get("latest_answer"))
    out = {
        "label": label,
        "session_id": s["id"],
        "status": s["status"],
        "duration_s": s["_duration_s"],
        "agent_revision": s.get("agent_revision"),
        "dependency_revisions": s.get("dependency_revisions"),
        "agent_view_url": s.get("agent_view_url"),
        "created_at": s.get("created_at"),
        "finished_at": s.get("finished_at"),
        "validation": v,
        "quota_before": quota,
    }
    (RESULTS / f"{label}_session.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    journal("run", label=label, t_start=t0, t_end=now(), session_id=s["id"], status=s["status"]["status"],
            success=v["success"], dependency_revisions=s.get("dependency_revisions"))
    print(json.dumps(out, indent=2, ensure_ascii=False))


def _short(x, n=300):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def summarize(events: list[dict]) -> dict:
    steps, urls, shots, errors, cost = [], [], [], [], None
    for e in events:
        d = e.get("data") or {}
        kind = d.get("kind")
        if kind == "policy_event":
            steps.append({
                "t": e.get("timestamp"),
                "pensee": _short(d.get("reasoning_content") or d.get("content") or "", 400),
                "actions": [_short({"tool": t.get("tool_name"), "args": t.get("args")}, 300)
                            for t in d.get("tool_reqs", [])],
            })
        elif kind == "tool_result":
            res = d.get("result")
            if isinstance(res, str) and ("rror" in res or "Input should" in res):
                errors.append(_short({"tool": (d.get("tool_req") or {}).get("tool_name"), "result": res}, 600))
        elif kind == "observation_event":
            url = (d.get("metadata") or {}).get("url")
            if url and (not urls or urls[-1] != url):
                urls.append(url)
            img = d.get("image") or {}
            if img.get("type") == "url":
                shots.append(img["source"])
        elif kind == "error_event":
            errors.append(_short({k: v for k, v in d.items() if k != "kind"}, 600))
        if e.get("type") == "MetricsUpdateEvent":
            cost = (d.get("metrics") or {}).get("total_cost")
        elif e.get("type") == "AgentErrorEvent":
            errors.append(_short(d, 600))
    return {"n_events": len(events), "steps": steps, "urls": urls, "screenshots": shots,
            "errors": errors, "cost_usd": cost}


def cmd_trace(label: str) -> None:
    c = h_api.client()
    t0 = now()
    run = json.loads((RESULTS / f"{label}_session.json").read_text())
    events = h_api.all_events(c, run["session_id"])
    raw = json.dumps(events, ensure_ascii=False)
    raw = re.sub(r'"source": "[A-Za-z0-9+/=]{200,}"', '"source": "<base64>"', raw)
    (RESULTS / f"{label}_events.json").write_text(raw)
    tr = summarize(events)
    saved = []
    for i, url in enumerate(tr["screenshots"][-1:]):
        full = url if url.startswith("http") else h_api.BASE.rsplit("/api/v2", 1)[0] + url
        r = c.get(full, follow_redirects=True)
        if r.status_code == 200:
            p = RESULTS / f"{label}_capture_{i + 1}.png"
            p.write_bytes(r.content)
            saved.append(p.name)
    tr["captures_sauvees"] = saved
    (RESULTS / f"{label}_trace.json").write_text(json.dumps(tr, indent=2, ensure_ascii=False))
    skill_body = c.get(f"/skills/{SKILL}").json()["body"]
    prompt = build_repair_prompt(run, tr, skill_body)
    (RESULTS / f"{label}_repair_prompt.md").write_text(prompt)
    journal("trace", label=label, t_start=t0, t_end=now(), n_events=tr["n_events"],
            n_steps=len(tr["steps"]), captures=saved)
    print(prompt)


def build_repair_prompt(run: dict, tr: dict, skill_body: str) -> str:
    v = run["validation"]
    last_steps = tr["steps"][-8:]
    lines = [
        "# Réparation d'un skill H RunAI (boucle Devin)",
        "",
        (f"Un agent H (`{AGENT}`) a échoué sur une tâche déterministe. Corrige le skill `{SKILL}` "
        "pour que la relance réussisse, sans affaiblir les garde-fous (lecture seule, liste blanche "
        "de pages, aucun formulaire, aucun paiement)."),
        "",
        "## Tâche",
        TASK,
        "",
        "## Critère de réussite (vérifié par script, vérité terrain lue sur la fiche produit)",
        f"status == ok, upc == {v['ground_truth']['upc']}, stock == {v['ground_truth']['stock']}",
        "",
        "## Résultat du run",
        (f"- session H : {run['session_id']} (statut {run['status']['status']}, "
        f"{run['status']['steps']} étapes, {run['duration_s']} s, {tr['cost_usd']} USD)"),
        f"- révisions utilisées : {json.dumps(run['dependency_revisions'], ensure_ascii=False)}",
        f"- réponse : {json.dumps(v['answer'], ensure_ascii=False)}",
        f"- contrôles : {json.dumps(v['checks'])}",
        f"- erreurs : {tr['errors'] or 'aucune'}",
        f"- URL visitées : {tr['urls']}",
        f"- captures : {tr['captures_sauvees']}",
        "",
        f"## Dernières étapes ({len(last_steps)}/{len(tr['steps'])})",
    ]
    for s in last_steps:
        lines.append(f"- {s['t']} : {s['pensee']} -> {s['actions']}")
    lines += [
        "",
        f"## Skill actuel ({SKILL}, dernière révision)",
        "```markdown",
        skill_body.strip(),
        "```",
        "",
        "## Rendu attendu",
        ("Le nouveau corps Markdown complet du skill (`skill_body`) et une ligne `change_message` "
        "qui explique la correction. Modifie aussi `spikes/boucle_devin/skills/` dans une PR."),
    ]
    return "\n".join(lines) + "\n"


def cmd_repair(label: str) -> None:
    t0 = now()
    prompt = (RESULTS / f"{label}_repair_prompt.md").read_text()
    fix = devin_repair.repair(prompt, HERE / "skills/books_runbook_v2.md")
    (RESULTS / "repair.json").write_text(json.dumps(fix, indent=2, ensure_ascii=False))
    journal("repair", t_start=t0, t_end=now(), mode=fix["mode"], devin_session=fix.get("devin_session_id"))
    print(json.dumps({k: v for k, v in fix.items() if k != "skill_body"}, indent=2, ensure_ascii=False))


def cmd_update() -> None:
    c = h_api.client()
    t0 = now()
    fix = json.loads((RESULTS / "repair.json").read_text())
    rev = h_api.put_skill(c, SKILL, SKILL_DESC, fix["skill_body"], fix["change_message"][:500])
    revs = h_api.skill_revisions(c, SKILL)
    (RESULTS / "skill_revisions.json").write_text(json.dumps(revs, indent=2, ensure_ascii=False))
    journal("update", t_start=t0, t_end=now(), skill_revision=rev)
    print("nouvelle révision", rev)
    print(json.dumps(revs, indent=2, ensure_ascii=False))


def cmd_report() -> None:
    rows = [json.loads(x) for x in (RESULTS / "journal.jsonl").read_text().splitlines()]
    runs = [r for r in rows if r["step"] == "run"]
    first_fail = next(r for r in runs if not r["success"])
    last_ok = next(r for r in reversed(runs) if r["success"])
    ts = lambda s: datetime.fromisoformat(s).timestamp()
    total = ts(last_ok["t_end"]) - ts(first_fail["t_start"])
    auto = sum(ts(r["t_end"]) - ts(r["t_start"]) for r in rows if r["step"] != "setup")
    rep = {
        "run_echec": first_fail["session_id"],
        "run_succes": last_ok["session_id"],
        "boucle_totale_s": round(total),
        "somme_etapes_automatiques_s": round(auto),
        "etapes": rows,
    }
    (RESULTS / "report.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False))
    print(json.dumps(rep, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    {"setup": cmd_setup, "run": cmd_run, "trace": cmd_trace, "repair": cmd_repair,
     "update": cmd_update, "report": cmd_report}.get(cmd, lambda *a: print(__doc__))(*args)

