# Brainstorm RunAI

> Document de travail. Rien n'est figé : on est en phase d'idéation.

## Contexte du hackathon

- **Computer Use Agents Hackathon**, H Company x 42AI, les 7 et 8 novembre 2026 à Paris.
- **Rendu : dimanche 8 novembre à 14h00.** Pitchs finaux à 15h45.
- Défi : un agent qui navigue sur des sites, des applis desktop ou des interfaces logicielles pour accomplir une **vraie tâche utile**. La démo doit montrer **le problème, les actions de l'agent, puis le résultat**.
- Équipes de 1 à 4 personnes.
- Prix : 5 000 €, 3 000 € et 2 000 € pour le podium. Prix sponsors **Best Use of Gladia** (1 000 €) et **Best Use of Devin** (1 000 €). Prix réseaux sociaux : meilleur post LinkedIn et meilleur post X (500 € chacun).
- Règle : utiliser **au moins 3 partenaires**.

### Grille du jury

| Critère | Poids | Question posée |
| --- | --- | --- |
| Use of Computer Use | 25 % | À quel point la capacité de l'agent à utiliser un ordinateur est-elle centrale et bien exploitée ? |
| Technical execution & reliability | 25 % | Ça marche de bout en bout, de façon régulière, sans assistance ? |
| Usefulness & impact | 20 % | Ça résout un vrai problème pour de vrais utilisateurs ? |
| Originality & innovation | 15 % | L'idée ou l'approche est-elle nouvelle ? |
| UX & user control | 10 % | Facile à utiliser ? L'utilisateur peut-il superviser ou arrêter l'agent ? |
| Demo clarity & Q&A | 5 % | Démo vidéo claire, bonnes réponses aux questions ? |

## Contraintes qu'on s'est fixées

- Thème : **le sport, en particulier la course à pied**.
- Viser une **vraie plus-value du computer use** : éviter ce qui a déjà une API ou un MCP. Par exemple, Strava a un [MCP officiel](https://support.strava.com/en-us/articles/15401531-how-do-i-connect-strava-to-an-ai-assistant) et Garmin Connect a plusieurs MCP communautaires.
- Partenaires envisagés : **H, Gladia, Devin**, plus **Linkup** et **Stripe** dans la vision complète.

## Idées explorées

| # | Idée | Pour | Contre |
| --- | --- | --- | --- |
| A | **« Inscris-moi »** : une phrase à voix haute, l'agent H trouve la course et remplit le formulaire d'inscription (profil, t-shirt, PPS ou certificat), puis s'arrête avant le paiement | Formulaires hétérogènes sans API, très visuel, correction à la voix en cours | Un coureur ne s'inscrit que quelques fois par an ; captchas possibles |
| B | **Chasseur de dossards** : surveille les bourses officielles de revente et les listes d'attente des courses complètes, puis inscrit automatiquement | Vraie douleur, que du web | Respecter strictement les règles des plateformes ; difficile à démontrer en direct |
| C | **Palmarès automatique** : reconstruit l'historique de résultats du coureur à partir des sites des chronométreurs | Données éparpillées sur des dizaines de sites | Peu d'action, surtout de la lecture |
| 1 | **« Publie ma course partout »** : un organisateur décrit son trail à la voix, et des agents H le publient en parallèle sur tous les calendriers (Jogging International, Finishers, Ahotu, FFA, Facebook…) | Computer use au cœur, gain mesurable (une demi-journée → 5 min), plusieurs agents en parallèle, original | Cible plus restreinte (les organisateurs) |
| 2 | **Inscription de groupe pour les clubs** : les membres envoient un vocal, et les agents inscrivent les 20 coureurs en parallèle | Utilité forte, très parallélisable, tableau de bord de supervision | Gestion des données de nombreuses personnes |
| 3 | **Le coach au bord de la piste** : Gladia transcrit en live les temps annoncés par le coach, et l'agent les saisit dans les outils du club | Meilleur candidat au prix Gladia | Audio de terrain fragile ; computer use moins spectaculaire |
| 4 | **Week-end marathon clé en main** : dossard, puis train ou avion, puis hôtel près du départ, avec arrêt avant chaque paiement | Très impressionnant | Le plus risqué en fiabilité (sites de voyage lourds, anti-bot) |
| 5 | **Revendre son matériel** : photo et une phrase, et l'annonce part sur Vinted, Leboncoin et Facebook | Simple à démontrer | Peu original, pas propre au sport |
| 6 | **Kiné du sport en urgence** : recherche et réservation sur Doctolib | Utile | Anti-bot ; une réservation réelle engage un vrai praticien |

## Vision « assistant complet » (piste actuelle)

Un seul outil qui accompagne le coureur de l'objectif jusqu'à la ligne d'arrivée : **réserver la course, le vol et l'hôtel, puis coacher l'entraînement**, avec un abonnement Stripe.

### Un rôle par partenaire

- **Linkup, pour savoir** : trouver la course, les dates, le lieu du départ, les hôtels proches, les infos pratiques.
- **H, pour faire** : inscription, vol et hôtel, avec des agents en parallèle, une vue live et un arrêt avant chaque paiement.
- **Gladia, pour parler** : toute l'interaction à la voix, y compris la correction d'un agent en cours de route. Plus le débrief vocal après une séance d'entraînement.
- **Stripe, pour payer** : l'abonnement RunAI Premium (coach et réservations).
- **Devin, pour construire** : le développement du projet.

### Scénario de démo (environ 3 min)

1. « Je veux courir le semi de Lisbonne en mars, objectif moins d'1h45. »
2. Linkup trouve la course et ses infos, et RunAI propose un plan.
3. « Vas-y. » Trois agents H partent en parallèle (inscription, vol, hôtel), et on les voit travailler en live.
4. Correction à la voix en cours de route : « hôtel à moins de 15 min du départ ».
5. Récap et validation vocale. Tout s'arrête avant le paiement.
6. Le coach génère le plan d'entraînement, et un abonnement Stripe (en mode test) débloque le suivi.
7. Bonus : un débrief vocal après une séance, et le plan s'ajuste.

### Priorités envisagées

- **P0** : voix → Linkup → inscription H → validation. Ça doit marcher à 100 %.
- **P1** : vol et hôtel en parallèle, correction vocale en cours, abonnement Stripe.
- **P2** : le coach (plan, puis débrief vocal). Il enrichit l'histoire, mais c'est surtout du LLM, donc peu de computer use.

### Points de vigilance

- **Fiabilité** : il faut tester tôt un agent H sur 2 ou 3 vraies pages d'inscription et sur un site d'hôtel (captchas, comptes, formulaires). Garder un faux site d'inscription comme filet de sécurité.
- **Périmètre** : mieux vaut un parcours principal parfait que 6 fonctionnalités fragiles.
- **Contrôle utilisateur** : vue live des agents, pause et stop (à la voix ou par bouton), l'agent qui pose des questions, jamais de paiement automatique.

## Questions ouvertes

1. Quel fil rouge : l'assistant complet « objectif course », l'inscription de groupe pour les clubs, ou « publie ma course partout » ?
2. Combien sommes-nous, et qui fait quoi ?
3. Vraies plateformes ou faux site pour la démo ?
4. Quel test de faisabilité H on lance en premier ?
