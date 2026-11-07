# Spike Axe 6 — « l'agent remplit, l'humain signe »

Un agent H (`h/web-surfer-pro`, SDK `hai-agents==1.4.3`) remplit le vrai formulaire Njuko du
**Wizz Air Milano Marathon 2027** (édition `OPEN`) avec une identité fictive (Camille Martin,
camille.martin@example.com, née le 12/05/1994). Devant chaque case sensible (santé, règlement,
RGPD, droit à l'image, assurance, option payante), il s'arrête ; le portail FastAPI affiche la
capture + le texte verbatim ; l'humain clique **Je valide / Je refuse** ; l'agent reprend.
Arrêt obligatoire avant le bouton PAYER.

## Ce qui est prouvé (mesuré)

Les **deux** mécanismes fonctionnent avec `hai-agents 1.4.3` :

| | Run 1 — outil client | Run 2 — pause + question |
|---|---|---|
| Session H | `a4e8f80e-9c11-4ba1-843d-a57be347bf94` | `52bc4c95-e22d-4a4e-8ece-571678e430af` |
| Mécanisme | `tools=[demander_validation_humaine]` → état `awaiting_tool_results` → `sessions.send_session_tool_results(ToolResultEvent)` | réponse `VALIDATION_REQUISE {json}` + `idle_timeout_s=900` → état `idle` → `session.send_message("APPROUVE/REFUSE …")` |
| Demandes de validation | 9 (3 cliquées par un humain, 6 par la politique auto) | 2 (politique auto) |
| Capture + URL de page dans le portail | 9/9 | 2/2 |
| Délai agent lève la case → affichée au portail | 2,1 – 3,1 s | 2,6 s |
| Appel API d'envoi de la décision | 0,50 – 0,60 s (médiane 0,52) | 0,51 – 0,57 s |
| Décision envoyée → état `running` vu | 0,07 – 0,14 s (médiane 0,10) | 0,03 – 0,05 s |
| Décision envoyée → 1re action de l'agent | 3,5 – 5,8 s (médiane 3,65) | 6,1 – 6,2 s |
| Fin | page **panier** (`?currentPage=cart`, 119,00 €), PAYER **non cliqué**, statut `completed`, 88 étapes, 931 s | **bloqué** par un refus sur case obligatoire, `idle` puis annulée (`interrupted`), 517 s |

Comportement après refus (mesuré) :
- option payante (gravure médaille, assurance annulation) → l'agent coche **« Non »** et continue ;
- consentements marketing / droit à l'image / partage ASICS → **« Je ne consens pas »** ou case laissée décochée, puis continue ;
- case **obligatoire** sans alternative (« Acceptation des conditions & assurance tourisme sportif — Oui (5,00 €) ») refusée (run 2) → l'agent ne la coche pas, ne contourne pas, s'arrête et renvoie un rapport « REGISTRATION BLOCKED ».

Temps d'attente humain mesurés (run 1, clics réels) : 40,4 s (santé), 16,2 s (assurance), 26,1 s (gravure).
Quota vérifié avant chaque run (2 puis 3 slots libres) ; les deux sessions sont terminales à la fin
(quota final 3/3 libres). Aucun compte créé, aucun paiement, aucune soumission.

## Recommandation (estimé, non mesuré)

- **Outil client** pour la démo : contrat typé (catégorie/champ/texte/obligatoire), pas de parsing,
  reprise plus rapide (~3,6 s contre ~6,2 s, sur peu d'échantillons) et la session garde son
  contexte de tâche sans tour de conversation supplémentaire.
- **Pause + question** = plan B si un agent ne supporte pas les outils : marche, mais dépend du
  respect du format `VALIDATION_REQUISE` par le modèle et exige `idle_timeout_s`.
- Une session en attente garde son slot H : prévoir un timeout côté portail.

## Relancer

```bash
pip install fastapi uvicorn httpx   # + requirements.txt du repo ; HAI_API_KEY dans l'env
# portail sans H (plan B démo, 3 demandes fictives) :
python spikes/portail_humain/portail.py --mode mock --port 8765
# run H réel, mécanisme outil (ou --mode message) :
python spikes/portail_humain/portail.py --mode tool --port 8765
# option : décision automatique si personne ne clique après N s
#   --auto "reglement=approve,rgpd=refuse,droit_image=refuse,assurance=refuse,sante=approve,paiement=refuse,*=approve" --auto-delay 30
python spikes/portail_humain/analyse.py spikes/portail_humain/runs/<session>.summary.json
```

Ouvrir http://localhost:8765 : vue live H, case en attente (capture, texte, obligatoire), boutons,
historique et latences. Le script annule la session H en sortie (fin, erreur ou `--max-wall`).

Fichiers : `portail.py` (runner H + API), `validation.html` (page), `analyse.py` (stats),
`runs/` (journaux JSONL et résumés des runs ci-dessus, sans capture ni secret).

## Limites

- 2 runs H seulement : latences indicatives, pas statistiques.
- 6/9 décisions du run 1 et 2/2 du run 2 sont prises par la politique auto (même route HTTP que le bouton).
- Njuko : la liste « Nationalité » (défilement imbriqué) fait perdre ~2 min à l'agent à chaque run.
- Un refus d'une case obligatoire bloque l'inscription : l'UI doit l'expliquer à l'utilisateur.
