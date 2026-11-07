"""Resume un ou plusieurs fichiers results/*.json : duree, etapes, tokens, outils, reponse."""

import json
import sys
from collections import Counter
from pathlib import Path


def summarize(path: Path) -> dict:
    r = json.loads(path.read_text())
    events = r.get("events") or []
    tools: Counter = Counter()
    steps = 0
    tokens = {}
    captcha_mentions = 0
    for e in events:
        d = e.get("data") or {}
        if e.get("type") == "MetricsUpdateEvent":
            m = d.get("metrics") or {}
            steps = max(steps, m.get("steps") or 0)
            for c in m.get("cost_per_model") or []:
                tokens = {k: c.get(k) for k in ("input_tokens", "cached_tokens", "output_tokens")}
        if d.get("kind") == "policy_event":
            for t in d.get("tool_reqs") or []:
                tools[t.get("tool_name")] += 1
            text = f"{d.get('reasoning_content') or ''} {d.get('content') or ''}".lower()
            if "captcha" in text or "robot" in text:
                captcha_mentions += 1
    status = (r.get("session") or {}).get("status") or {}
    return {
        "fichier": path.name,
        "session_id": r.get("session_id"),
        "statut": r.get("status"),
        "outcome": r.get("outcome"),
        "duree_mur_s": r.get("wall_s"),
        "debut": (r.get("session") or {}).get("started_at"),
        "fin": (r.get("session") or {}).get("finished_at"),
        "etapes": status.get("steps") or steps,
        "tokens": tokens,
        "outils": dict(tools),
        "mentions_captcha_ou_robot": captcha_mentions,
        "attente_slot_s": (r.get("quota_wait") or {}).get("waited_s"),
        "annulee": r.get("cancelled"),
        "reponse": r.get("answer"),
    }


if __name__ == "__main__":
    files = [Path(p) for p in sys.argv[1:]] or sorted((Path(__file__).parent / "results").glob("*.json"))
    for f in files:
        print(json.dumps(summarize(f), ensure_ascii=False, indent=2))
