# Spike axe 8 — Plan B « course complète »

Quand la course visée est complète/fermée/passée, `plan_b.py` renvoie (modèle Pydantic `PlanB`, voir `models.py`) :
(a) les options officielles (liste d'attente / revente / transfert) avec URL source, (b) jusqu'à 3 alternatives de même
distance à ±21 jours, atteignables en ≤ 2 h de vol/train depuis Paris, avec statut d'inscription et plateforme.
Pipeline 100 % Linkup (search `standard` structuré + fetch `renderJs` structuré), ~30 s, ~0,10–0,16 $ par course.
`h_verify.py` = 1 run H (h/web-surfer-pro) qui ouvre la page Lisbonne et lit le formulaire sans rien saisir ni soumettre.

## Relancer
```bash
pip install -r requirements.txt            # LINKUP_API_KEY (et HAI_API_KEY pour h_verify) dans l'env
cd spikes/plan_b
python plan_b.py "EDP Meia Maratona de Lisboa 2027 (semi-marathon de Lisbonne, 21,1 km, mars 2027)" \
  --registration-url https://meia-maratona.inscricoes.maratonaportugal.com/ --out results/lisbon_half_2027.json
python plan_b.py "Hyundai Mitja Marató Barcelona 2027 (Barcelona half marathon, February 2027)" --km 21.1 --out results/barcelona_half_2027.json
python plan_b.py "Zurich Maratón de Sevilla 2027 (Seville marathon, February 2027)" --km 42.195 --out results/sevilla_marathon_2027.json
python h_verify.py --out results/h_lisbon_waitlist.json   # attend le quota H (≤10 min), annule toujours la session
```

## MESURÉ (7 nov. 2026, sorties dans `results/`, logs `run_v2.log`, `run_v3.log`)
| Course | Statut détecté (preuve) | Options officielles | Latence | Appels Linkup | Coût calculé |
|---|---|---|---|---|---|
| Semi Lisbonne 7/03/2027 | `sold_out` — fetch page d'inscription : « As provas EDP Meia Maratona de Lisboa, Vodafone 10K e Luso 7K estão esgotadas » | aucune liste d'attente / revente / transfert confirmée dans le règlement officiel | 34,2 s (v3) / 39,6 s (v2) / 35,1 s (v1) | 20 search + 7 fetch (+1 no_result, non facturé) | 0,162 $ (v3), 0,132 $ (v1, = delta de solde mesuré 0,132 $) |
| Semi Barcelone 14/02/2027 | `sold_out` — « ha tancat inscripcions després d'exhaurir els 40.000 dorsals » | aucune confirmée (FAQ officielle) | 26,2 s | 14 + 2 | 0,096 $ |
| Marathon Séville 21/02/2027 | `sold_out` — « Once the 20,000 race bibs … sell out, the waiting list will open » | **liste d'attente officielle** : https://www.zurichmaratonsevilla.es/en/zms-regulations | 28,3 s | 16 + 3 | 0,114 $ |

Le delta de solde Linkup (0,254 $ v3) est bruité : la clé est partagée avec d'autres agents en parallèle ; le coût calculé
(nb d'appels × prix public) est la valeur fiable.

Alternatives renvoyées pour Lisbonne et **vérification manuelle** (curl / fetch de la page officielle et de la plateforme) :
| Alternative (run) | Date | Trajet (estimé) | Vérif. manuelle |
|---|---|---|---|
| Liverpool Half (v1,v2,v3) | 14/03/2027 | vol ~90 min | **OUVERT** — Active (endurancecui.active.com, e=96803721) : General Entry 38 £, catégories disponibles |
| NN CPC Loop Den Haag (v1) | 14/03/2027 | vol ~80 min | **OUVERT** — page register officielle, 44 € / 46 € / 49,50 €, lien Njuko |
| Stramilano Half, Milan (v2,v3) | 21/03/2027 | vol ~90 min | **probablement ouvert** — site : « Register Now », inscriptions ouvertes depuis le 15/06/2026, page Endu `/events/stramilano-2/book` active ; aucun prix/compteur lu |
| Bath Half (v1,v2) | 14/03/2027 | vol ~80 min | **FAUX POSITIF** — accueil : « Missed out on general entry? Secure a charity place » (FAQ obsolète). Rejeté en v3 grâce au champ `general_entry_open` |
| Frankfurt Mainova Halbmarathon (v3) | 21/03/2027 | vol ~75 min | **FAUX POSITIF** — « Wir sind ausgebucht! », Datasport « Teilnehmerlimit: 10500 freie Startplätze: 0 » |

Barcelone et Séville : 0 alternative retenue (aucun candidat ouvert à ±21 j dans la table de trajets) — résultat honnête, pas d'invention.

**Run H (1 seul, mesuré)** — session `a9db3ef5-7541-4b6d-9053-bcf25c844a71`, h/web-surfer-pro, attente quota 300 s
(3/3 slots occupés), 37,8 s, 27 événements, aucune saisie, session annulée (`cancelled: true`). L'agent a sélectionné le
semi dans « Prova » et a été redirigé vers une **liste d'attente officielle** :
https://meia-maratona.inscricoes.maratonaportugal.com/waitinglist.aspx?lang=&prova_id=3769 — titre « Lista de Espera »,
texte « …esgotaram… na eventualidade de haver desistências, avisaremos… », champs Nome / Apelido / Email / Nacionalidade.
→ **Linkup seul l'avait manquée** (règlement : « aucune liste d'attente confirmée ») ; le computer use H la trouve.
Sortie : `results/h_lisbon_waitlist.json`.

## ESTIMÉ / limites
- Durées de trajet : table manuelle `travel.py` (vols directs / TGV typiques depuis Paris), **pas** une recherche de billets.
- Les résultats Linkup varient d'un run à l'autre (3 runs Lisbonne → 3 jeux d'alternatives différents) : 2 faux positifs
  « ouvert » sur 5 candidats distincts. Pour la démo, il faut une vérification de la page de la **plateforme** (Active, Njuko,
  Datasport, Let's Do This, Endu) — par fetch ciblé ou par un agent H — avant d'afficher « ouvert ».
- Fusion prudente des statuts (`fuse`) : une seule source « complet/fermé » l'emporte ; « ouvert » exige la page d'inscription lue.
