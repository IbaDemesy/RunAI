# Spike axe 2 : inscription H réelle (Njuko, Klikego)

Agent `h/web-surfer-pro` (modèle holo4-27b), profil fictif Camille Martin, consigne « remplir puis s'arrêter avant
paiement ». Aucun paiement, aucune soumission, aucun compte créé. 3 runs H au total, un à la fois, quota vérifié avant
chaque run, chaque session annulée à la fin (statut final `interrupted`).

## Ce qui est prouvé

- Sur une course ouverte de printemps 2027, H remplit seul tout le formulaire coureur Njuko et Klikego
  (identité, contact, adresse, contact d'urgence, tarif non licencié) sans captcha ni anti-bot.
- H s'arrête bien aux points de passage humain : PPS/licence (Njuko Hyères), case règlement/CGU (Njuko Cahors),
  mot de passe du compte Klikego (Klikego Chatou). Aucune case santé, règlement ou RGPD n'a été cochée
  (vérifié sur les captures et dans la réponse JSON).
- La réponse JSON typée (`answer_schema` pydantic) remonte les textes exacts des cases sensibles, les champs
  manquants (ex. « SAS de départ ») et les options payantes : c'est la matière du portail de validation.
- Bug trouvé : holo4 n'arrive pas à écrire la valeur d'enum `bloque_case_obligatoire` (11 essais refusés de l'outil
  `answer` dans d56006bc, détour par Wikipédia et Google pour « s'amorcer »). Corrigé dans `run_h.py` par des valeurs
  courtes (`PAIEMENT`, `HUMAIN`, `COMPTE`, …) ; correction **non re-testée** (limite de 3 runs atteinte).

## Résultats mesurés (7 nov. 2026)

| Run | Course (plateforme) | Session H | Étapes | Durée H | Arrêt | Statut renvoyé |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 km de Hyères, 21/03/2027, 22 € (Njuko) | 3c2947ae-fea1-4476-bd44-6b013d22eeab | 57 | 12 min 43 | Formulaire participant, radio obligatoire « Licence FFA / Numéro PPS » | `echec` (en fait case humaine, enum non émise) |
| 2 | Semi Boucle de Seine, Chatou, 21/03/2027, 43 € + 2,50 € de frais (Klikego) | 501f4316-4bb6-4762-a69f-8aebea3196ab | 40 | 3 min 13 | Même formulaire : bloc « Un compte KLIKEGO va vous être créé » (mot de passe) | `compte_requis` |
| 3 | Grand Trail des Cadourques, Valentré 15 km, Cahors, 03/04/2027, 20 € (Njuko) | d56006bc-2dd8-4e2a-ac0d-7e3bfcce6129 | 69 | 7 min 33 | Étape règlement : « J'accepte le règlement et les CGU » obligatoire ; PPS laissé vide (autorisé par l'organisateur) | `echec` (en fait case humaine) |

- 3/3 runs : formulaire rempli avec le profil fictif et arrêt au bon endroit, 0 captcha, 0 paiement, 0 case sensible cochée.
  Mais 0/3 n'atteint le panier : chaque plateforme impose une action humaine avant (PPS, CGU, mot de passe).
- Durée « utile » (jusqu'à la page d'arrêt, lue dans les horodatages des événements, heuristique) : environ 2 à 3 min
  par run. Le reste (≈ 10 min au run 1, ≈ 4 min au run 3) correspond aux essais de réponse refusés à cause de l'enum.
- Jetons holo4 en entrée (dont cache) : 3,19 M (2,70 M), 0,83 M (0,54 M), 2,28 M (1,76 M).
- Quota avant chaque run : `available` = 2/3 (1 slot occupé par un autre agent).
- Ouverture des courses vérifiée le 7 nov. 2026 : Hyères 10 km, 595 places restantes (semi complet) ; Cadourques
  Valentré, 112 places ; Chatou, inscriptions ouvertes à tous.

Détails et réponses JSON complètes : `resultats/<cible>/resultat.json`, captures : `resultats/<cible>/captures/`.

## Recommandation de démo

**Njuko, 10 km de Hyères (21/03/2027)** en principal : pas de compte jusqu'au panier, formulaire testé deux fois
(10 km Hyères le 7 nov. au matin dans BRAINSTORM, puis ici), et le blocage PPS est exactement le moment
« l'agent remplit, l'humain signe ». En secours : **Njuko Cadourques 15 km** (autre course Njuko, PPS facultatif à
l'inscription, l'arrêt se fait sur la case règlement). Klikego reste jouable mais impose un mot de passe à l'humain.

## Relancer

```bash
.venv/bin/pip install -r requirements.txt
# HAI_API_KEY dans l'environnement ou .env
.venv/bin/python spikes/inscription_h/run_h.py njuko_hyeres_10k        # ou klikego_boucle_seine_semi, njuko_cadourques_15k
.venv/bin/python spikes/inscription_h/run_h.py recup <cible> <session_id>  # recollecte événements et captures
```

Le script vérifie le quota (attente max 10 min), lance une session, attend la réponse, annule la session dans tous les
cas, puis écrit `resultats/<cible>/resultat.json` et 5 captures.

## Fichiers

- `skills/regles_communes.md` : règles dures (pas de paiement, cases sensibles non cochées, statuts d'arrêt).
- `skills/njuko.md`, `skills/klikego.md` : prompt-skills par plateforme, enrichis avec ce qu'ont appris les runs.
- `skills/profil_fictif.md` : profil Camille Martin.
- `run_h.py` : lanceur et collecte.
