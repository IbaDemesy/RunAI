# Acceptation UX statique D3

Revue statique uniquement, aucun test navigateur/lecteur d'écran. Les motifs
de `checks.py` vérifient des contrats source ciblés, pas toutes les variantes
sémantiquement équivalentes de JavaScript/CSS. Un changement de structure exige
une revue de ces contrats ; les tests ne prouvent pas le comportement à l'exécution.

| Défaut | Fichier | Attendu | Sévérité | Patch (`fixes/`) |
|---|---|---|---|---|
| UX-01 | app.js | Focus équivalent ou h1 après reconstruction, y compris mutation désactivant le bouton | majeur | d1-app-js.patch |
| UX-02 | app.js | Navigation courante aria-current=page | moyen | d1-app-js.patch |
| UX-03 | app.js | Noms contextualisés des candidats, réponses et envois | moyen | d1-app-js.patch |
| UX-04 | app.js | Annonce des changements de mission.status reçus via SSE | moyen | d1-app-js.patch |
| UX-05 | app.js | Région nommée journey-map | mineur | d1-app-js.patch |
| UX-06 | app.js | h1 unique inconditionnel de mission et questions en h2 | mineur | d1-app-js.patch |
| UX-07 | app.js | Nouvel onglet annoncé dans le nom du lien | mineur | d1-app-js.patch |
| UX-08 | app.js | Lecture non proposée en mouvement réduit | mineur | d1-app-js.patch |
| UX-09 | live.html | Viewport et statut polled annoncé | mineur | d1-UX-09.patch |
| UX-10 | style.css | ink-3 sur paper/paper-2 >= 4.5 | moyen | d1-UX-10.patch |

Tous les défauts proposés sont retenus à la lecture du code D1 (97265c6).
UX-01 : `render` remplace les descendants, les clés/restauration ne visent que
les inputs ; `mutate` désactive les boutons avant le rendu, d'où la clé mémorisée
avant l'action dans le correctif. Le symptôme de focus sur body reste une inférence
statique, pas une observation navigateur. UX-04 : le refresh SSE est câblé hors mock,
hors états terminaux, si EventSource existe ; il recharge puis rend sans annoncer
le statut. Pas de connexion SSE réelle effectuée. UX-08 concerne le bouton externe
du shell, même si C3 refuse déjà la lecture réduite dans son API.

Contrôles de régression : langue française, viewport, feedback status/polite,
champs enveloppés dans label, focus-visible >=2px, neutralisation animation et
transition en mouvement réduit, option reducedMotion, boutons >=44px, noopener.
Les contrastes sont calculés selon WCAG à partir des hex et alias :root : les
deux échecs réels ink-3/paper (4.398) et ink-3/paper-2 (4.325) restent en xfail
strict ; les autres combinaisons demandées passent. Le patch assombrit ink-3.

Les patches sont groupés pour app.js afin d'éviter les chevauchements, appliqués
par `git apply` sur une copie de la base 97265c6, puis les mêmes checks et
`node --check` sont exécutés. Aucun fichier produit n'est modifié.

C3 : fournir `RUNAI_UX_C3_DIR` contenant journey-fallback.js et journey.css ;
sinon utilisation de web/flyover si intégré, sinon skip explicite (câblage E3).
Un dossier explicitement fourni incomplet échoue au lieu d'être ignoré.
Contrôles : live region, chapitre courant, flèches/Home/End, désactivation de
Lecture réduite, restauration du focus chapitre/action, CSS et noopener.
Aucun défaut C3 retenu dans ces contrats statiques.

Exécution : `.venv/bin/ruff check . && .venv/bin/pytest -q tests/ux_acceptance`
après `source ~/.nvm/nvm.sh` pour Node ; puis même pytest avec RUNAI_UX_C3_DIR.
