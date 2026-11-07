# Spike axe B : trouver des courses ouvertes adaptees au coureur

Entree : un profil coureur (`profiles.py`). Sortie : 3-5 courses avec date, distance, D+, plateforme,
URL d'inscription, statut verifie sur la page, raison, sources. Aucune session H creee.

## Pipeline (`finder.py`)

1. **Decouverte** : 2 `/search` Linkup `standard` + `structured` (schema Pydantic), domaines exclus :
   finishers.com (CGU anti-IA), booking, airbnb, strava. + 1 `/fetch` d'une page calendrier si Linkup en cite une.
2. **Filtre dur** : fenetre de dates, tolerance de distance, temps de trajet estime (geocodage Open-Meteo +
   haversine, vitesse 80 km/h sol, 700 km/h + 1,5 h fixe en avion).
3. **URL d'inscription** : un `/search` cible par course sans URL.
4. **Verification** : `/fetch` de la page d'inscription avec schema (`renderJs` si besoin) ->
   statut `open / full / waitlist / not_yet_open / closed / unknown`, phrase exacte, prix lu.
   Statut d'un agregateur = `open_selon_agregateur` (non recommande). Page illisible (Njuko) = `a_verifier_par_H`.
5. Si moins de 3 ouvertes : 2e tour avec une autre formulation. Score : distance, terrain, trajet, prepa.

## Relancer

```bash
cd spikes/trouver_courses
LINKUP_API_KEY=... ../../.venv/bin/python run_profiles.py   # ecrit results/<profil>.json + summary.json
```

## Resultats MESURES (7 nov. 2026, `results/`)

| Profil | Latence | Cout Linkup (delta solde) | Ouvertes proposees | Verif. manuelle (curl de la page) |
|---|---|---|---|---|
| p1 debutant 10 km Paris, mars-avr. 2027 | 20,4 s | 0,038 $ | 1 | 0/1 : EcoTrail 10 km, page ambigue ("Inscriptions terminees" + liste d'attente) |
| p2 semi rapide France, printemps | 26,5 s | 0,068 $ | 4 | 3/4 : Boucle de Seine, Crevin, Nantes OK ; Sylvanais = ouvert **aux licencies FFA seulement**, semi tout public "Ferme, ouverture 01/12/2026" |
| p3 trail 20-30 km depuis Lyon | 52,2 s | 0,056 $ | 3 | 2/3 : Forts de Besancon, Transju'Trails OK ; Volvic : "Inscriptions sportives" = item de menu, statut non prouve |
| p4 semi etranger < 2 h de vol | 60,8 s | 0,104 $ | 4 | 3/4 : Reading, Hastings, Leuven OK ; Hackney = dossard caritatif (35 GBP + 155 GBP de collecte) |

- **Precision** (ouvertes proposees confirmees a la main) : **8/12 = 67 %** (9/12 si on compte le dossard caritatif).
- **Cout** : 0,266 $ pour les 4 profils, 0,067 $ par profil en moyenne. Couts unitaires mesures sur appels
  isoles : search standard structured 0,006 $, fetch renderJs + schema 0,012 $, fetch schema 0,008 $.
- **Latence** : 20-61 s par profil ; le `/fetch` de verification est le poste principal (1-21 s par page).
- **Instabilite** : meme profil, meme code ou presque, resultats tres differents d'un run a l'autre.
  Run precedent : p1 = "10 km Magny 2027" (registration4all, "Places disponibles : 637", verifie OK) ;
  p2 = 0 ouverte et 5 pages Njuko/SPA `a_verifier_par_H`. `/search` `deep` : 126 s pour 10 courses sans URL.
- **Linkup `/fetch` echoue (HTTP 400)** sur `in.njuko.com` et `in.reg.hokasemimarathondeparis.com`
  (SPA) : Semi de Paris, Poitiers-Futuroscope, Marathon medieval, Night Marathon Luxembourg.

## Sources et CGU (lues le 7 nov. 2026)

| Source | API / flux | Automatisation |
|---|---|---|
| Finishers | aucune publique | **Interdit** : CGU interdisent scrapers, navigateurs automatises, IA/RAG, calendriers derives. Exclu. |
| Njuko | `/api/` interdit par robots.txt | pages d'inscription SPA, illisibles par Linkup -> H |
| Klikego | aucune | robots.txt interdit formulaires/paiement ; CGU : robots et fausses inscriptions = suppression de compte. Lecture de la fiche OK. |
| Protiming | aucune | robots.txt `Content-Signal: search=yes, ai-train=no, use=reference` |
| Calendrier FFA (bases.athle.fr) | aucune, pas de licence de reutilisation trouvee | robots.txt `Disallow: /` sur bases.athle.fr ; athle.fr competitions cite comme source par Linkup |
| JogOnce | introuvable | non confirme |
| Ahotu | - | 403 Cloudflare depuis la VM |

Conclusion : pas d'API calendrier exploitable ; Linkup (moteur de recherche) + lecture de la page
officielle de la course est la seule voie propre.

## Ce que H apporte (prompt pret : `h_verification.md`, non lance)

- Pages SPA (Njuko, HOKA Semi de Paris) : statut et prix illisibles par Linkup.
- Statut **par epreuve et par public** : Sylvanais "ouvert" seulement aux licencies ; EcoTrail
  "termine" vs liste d'attente ; dossard caritatif vs dossard standard.
- Prix du palier courant et options (t-shirt, repas, assurance, navette) visibles apres le choix de l'epreuve.

## ESTIME, non mesure

- Temps de trajet (geometrique, pas d'itineraire reel) ; preparation minimale par niveau (regle fixe).
- Cout de la verification H (~1 session/course) : non mesure, aucune session lancee.
