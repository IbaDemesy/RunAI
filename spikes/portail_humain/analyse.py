"""Résume un run : python spikes/portail_humain/analyse.py runs/<session>.summary.json"""

import json
import statistics
import sys
from pathlib import Path

s = json.loads(Path(sys.argv[1]).read_text())
print(f"session {s['session_id']} mode={s['mode']} statut={s['status']} demandes={len(s['history'])}")
for key in ("send_api_s", "resume_seen_s", "next_policy_s"):
    vals = [h[key] for h in s["history"] if h.get(key) is not None]
    if vals:
        print(f"  {key}: n={len(vals)} min={min(vals)} médiane={statistics.median(vals)} max={max(vals)}")
for h in s["history"]:
    print(f"  - [{h['categorie']}] {h['champ'][:60]} -> {h['decision']} ({h['decided_by']}) "
          f"attente={h['human_wait_s']}s 1re_action={h.get('next_policy_s')}s : {(h.get('agent_next_action') or '')[:120]}")
print("notes:", s["notes"])
print("réponse:", (s["answer"] or "")[:1500])
