# Brainstorm RunAI

> Document de travail. Rien n'est figé : on est en phase d'idéation.

## Contexte du hackathon

- **Computer Use Agents Hackathon**, H Company x 42AI, les 7 et 8 novembre 2026 à Paris (La Maison by Motier Ventures). [Page de l'événement](https://builderbase.com/track-dashboard/h-company-42ai-computer-use-agents-hackathon/event-site), [Discord](https://discord.gg/WjmTcMW9e).
- **Rendu : dimanche 8 novembre à 14h00** (le dashboard indique une clôture à 14h30, on vise 14h00). Pitchs finaux à 15h45. Les 6 livrables sont détaillés dans [Livrables de soumission](#livrables-de-soumission).
- Outils H : [Agents API](https://hub.hcompany.ai/agents-api/introduction) et [modèles](https://hub.hcompany.ai/models-api/introduction). Mentorat 1:1 avec les chercheurs et ingénieurs de H sur place.
- Défi : un agent qui navigue sur des sites, des applis desktop ou des interfaces logicielles pour accomplir une **vraie tâche utile**. La démo doit montrer **le problème, les actions de l'agent, puis le résultat**.
- Équipes de 1 à 4 personnes.
- Prix : 5 000 €, 3 000 € et 2 000 € pour le podium. Prix sponsors **Best Use of Gladia** (1 000 €) et **Best Use of Devin** (1 000 €). Prix réseaux sociaux : meilleur post LinkedIn et meilleur post X (500 € chacun). Total : 13 000 € en cash. Les membres des 3 équipes du podium gagnent aussi un mois gratuit de coworking Morning Nomade.
- Règle : utiliser **au moins 3 partenaires**. Partenaires : H, Gladia, Linkup, Cognition (Devin), Stripe et Morning (coworking, pas un outil technique).

### Planning

| Quand | Quoi |
| --- | --- |
| Sam. 7, 10h30 | Début du hacking |
| Sam. 7, 21h00 | Plus d'entrée dans le lieu |
| Dim. 8, 8h00 | Réouverture du lieu |
| **Dim. 8, 14h00** | **Rendu des projets** |
| Dim. 8, 14h30 | Premier tour de jugement |
| Dim. 8, 15h45 | Pitchs finaux |
| Dim. 8, 17h45 | Annonce des gagnants |

Horaires de Paris, susceptibles de petits ajustements.

### Livrables de soumission

Le formulaire du [dashboard](https://builderbase.com/track-dashboard/h-company-42ai-computer-use-agents-hackathon/overview) demande **6 éléments**. Le bouton « Submit » ne se débloque qu'une fois les 6 remplis, et la saisie est enregistrée au fur et à mesure.

| # | Champ | Statut | Ce qu'on met |
| --- | --- | --- | --- |
| 1 | Project Name | Fait | RunAI |
| 2 | Github Repo | Fait | [github.com/IbaDemesy/RunAI](https://github.com/IbaDemesy/RunAI) |
| 3 | Submission on H Showcase Platform | À faire | Fiche sur [showcase.hcompany.ai/submit](https://showcase.hcompany.ai/submit/), sur le modèle des fiches existantes : *What it does*, *How it works*, *Built with*, commandes pour lancer le code |
| 4 | Demo Video URL | À faire | Vidéo d'environ 3 min : le problème, les actions des agents H en live, puis le résultat (arrêt avant paiement) |
| 5 | Project Description | À faire | Pitch court : « Dis-moi ta course, je prépare tout le déplacement », partenaires utilisés (H, Linkup, Gladia, Devin) |
| 6 | How do I test your product live | À faire | Instructions pour le jury : URL ou commandes, clés nécessaires, scénario à dire au micro, et le rappel que rien n'est payé |

Le jury voit un aperçu de la soumission (« Review what judges will see ») : à relire avant d'envoyer.

**Deadline** : la page de l'événement indique un rendu à 14h00, le dashboard une clôture des soumissions à 14h30 (GMT+1). On vise **14h00**.

### Grille du jury

Jurés : Mathieu Astruc, Axel Darmouni, Thibaut Le Boulaire, Maxime Langevin, Alexis Deprez, zak a, Nolwenn Guiban, Denis Charrier, Amel Negra, Mathieu Diaz.

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
  Linkup sera branché comme outil d'un **agent H**, et non de Devin : c'est l'agent H qui l'appelle pour chercher l'info avant d'agir.
  Endpoints, coûts et exemple de branchement : [LINKUP.md](LINKUP.md).
- **H, pour faire** : inscription, vol et hôtel, avec des agents en parallèle, une vue live et un arrêt avant chaque paiement.
- **Gladia, pour parler** : toute l'interaction à la voix, y compris la correction d'un agent en cours de route. Plus le débrief vocal après une séance d'entraînement.
- **Stripe, pour payer** : l'abonnement RunAI Premium (coach et réservations).
- **Devin, pour construire** : le développement du projet.
  Stratégie pour le prix « Best Use of Devin » : [DEVIN.md](DEVIN.md), avec Devin dans la boucle du produit.

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

- **Fiabilité** : le test H sur de vraies pages d'inscription, d'hôtel et de vol est fait (résultats ci-dessous). Garder un faux site d'inscription comme filet de sécurité.
- **Périmètre** : mieux vaut un parcours principal parfait que 6 fonctionnalités fragiles.
- **Contrôle utilisateur** : vue live des agents, pause et stop (à la voix ou par bouton), l'agent qui pose des questions, jamais de paiement automatique.

## Orientation retenue : une seule feature forte

Plutôt que plein d'idées annexes, on vise **une feature unique, fiable de bout en bout et spectaculaire en démo**. C'est ce que récompense la grille : le computer use et la fiabilité pèsent 50 % de la note.

### La feature : « Dis-moi ta course, je prépare tout le déplacement »

Le coureur formule **une seule intention** (« je veux courir le semi de Lisbonne en mars »), et plusieurs agents l'exécutent :

1. **Inscription à la course** : l'agent H trouve la page d'inscription et remplit le formulaire (profil, t-shirt, PPS ou certificat).
2. **Hôtel** proche du départ.
3. **Vol ou train**.

Tout se fait avec **3 agents H en parallèle et une vue live**. La voix sert à piloter et corriger (« hôtel à moins de 15 min du départ »). L'agent **s'arrête avant chaque paiement** : rien n'est réservé, mais le jury voit les formulaires remplis.

C'est plus fort que l'inscription seule sur deux critères, l'impact et l'utilisation du computer use, tout en restant une seule histoire.

### Principes pour la rendre fiable

- **Linkup cherche, H agit.** On ne fait pas naviguer H sur des comparateurs (Google Flights…) : Linkup trouve les options, et H ne va sur un site que pour remplir la réservation choisie.
- **Arrêt avant chaque paiement.** Aucune vraie réservation.
- **Construction par couches, chacune démontrable seule** : d'abord l'inscription à la course (béton), puis l'hôtel, puis le vol. Si une couche ne tient pas dimanche matin, on présente les précédentes, et la suivante reste dans la vision du pitch.
- **Supervision** : une vue live par agent, pause et stop, l'agent qui pose des questions en cas de doute.

### Risques

- Les sites de voyage sont les plus difficiles pour un agent : anti-bot (Booking, Airbnb), pages lourdes, prix dynamiques. Les compagnies aériennes sont souvent les pires.
- Les plateformes d'inscription peuvent avoir des captchas ou exiger un compte.

### Test de faisabilité réalisé

Le test visait à vérifier qu'un agent H arrive, **jusqu'à l'étape du paiement sans payer**, à faire trois choses :

1. Remplir 2 ou 3 vraies pages d'inscription à une course.
2. Réserver un hôtel (Booking ou le site d'une chaîne).
3. Réserver un vol (site d'une compagnie).

Ce test a confirmé le périmètre **course + hôtel + vol** (résultats ci-dessous).

Hors périmètre, ou mention « vision » dans le pitch : coach d'entraînement, abonnement Stripe, mode club.

## Résultats du test de faisabilité H (7 nov.)

Test avec l'agent **`h/web-surfer-pro`**, un **faux profil** et **5 sessions en parallèle**. Toutes les sessions ont été arrêtées avant paiement.

| Site | Résultat | Détails |
| --- | --- | --- |
| Njuko | ✅ Panier/paiement atteint | 10 km de Hyères, 22 €, sans compte |
| Klikego | ✅ Page de paiement atteinte | 10 km du Maine Libre, 8 €, mode invité ; le parcours invité crée un profil coureur avec mot de passe |
| Site organisateur (Time To / ASO) | ❌ Compte obligatoire | 10K Montmartre |
| Booking.com | ✅ Étape finale avant paiement atteinte | Ibis Lisbonne, 173 € pour 2 nuits, sans compte |
| TAP, Paris → Lisbonne | ✅ Page « Payer » atteinte | 171,47 €, mode invité |

**Aucun captcha ni anti-bot rencontré.**

### Conclusions et décisions de l'équipe

- **Course + hôtel + vol est faisable : le périmètre est confirmé.**
- **PPS obligatoire pour les non-licenciés** sur Njuko et Klikego. Le PPS touche à la santé, donc l'agent ne le fait jamais à la place de l'utilisateur : il l'avertit et le guide (quoi faire sur pps.athle.fr), puis l'utilisateur fournit lui-même son numéro PPS, qui est ensuite réutilisé dans son profil coureur.
- **Si un site exige un compte, l'utilisateur crée son compte lui-même**, puis l'agent reprend (décision de l'équipe).
- **Point à surveiller : le temps.** 40 à 64 étapes par session, environ 10 à 15 min chacune. Pistes : agents en parallèle, consignes ciblées, sessions préchauffées / démo préparée.

## Linkup et Gladia : ce qu'on a appris

### Linkup prépare, H exécute

Test Booking avec le même faux profil et les mêmes règles d'arrêt avant paiement :

| Mesure | H seul (test initial) | Linkup + H |
| --- | --- | --- |
| Étapes H | 48 | 22 |
| Exécution H (démarrage → fin) | 4 min 23 | 1 min 56 |
| Total (file comprise, avec environ 5 s de Linkup) | 5 min 32 | Environ 2 min 7 |

**Un seul essai par variante, avec une cible différente** : Praça do Comércio au départ, puis le pont du 25-Avril. Le gain observé n'est donc pas une preuve causale ni une garantie de temps.

- **« Linkup prépare, H exécute »** : la préparation est une recherche structurée Linkup et une URL de départ directe. L'agent H n'a jamais appelé l'outil `recherche_web` mis à sa disposition ; **un seul appel Linkup au total**.
- L'URL Booking fournie par Linkup était trop générique : **on construit l'URL depuis les coordonnées** retournées, avec les dates et le nombre de voyageurs.
- Linkup a trouvé la vraie date de la course : **7 mars 2027**, alors que les nuits demandées étaient du 20 au 22 mars. **Vérifier les dates avant de réserver** devient un moment de démo : détecter l'incohérence et demander confirmation.
- Intégration H : `tools=[recherche_web]`, avec une fonction Python exécutée dans **notre backend** pendant que le SDK attend la session. **Pas de branchement MCP entrant documenté pour les agents H** ; le MCP H expose H à d'autres clients, pas l'inverse.
- Coût Linkup : environ **0,006 $/appel** en `depth="standard"`, avec `output_type="structured"` ou `"sourcedAnswer"`.

Docs : [recherche, formats et tarifs Linkup](https://docs.linkup.so/pages/documentation/endpoints/search/overview), [SDK Python](https://docs.linkup.so/pages/sdk/python/python), [outils personnalisés H](https://hub.hcompany.ai/agents-api/custom-tools), [MCP H](https://hub.hcompany.ai/agents-api/mcp). Détails d'intégration dans [LINKUP.md](LINKUP.md).

### Gladia pour piloter et superviser à la voix

- **Transcription live en français avec `solaria-1`** : `language_config.languages=["fr"]`. Afficher les transcriptions partielles à l'écran (`messages_config.receive_partial_transcripts=true`), puis remplacer par le résultat final du même énoncé.
- **Vocabulaire personnalisé** : Njuko, Klikego, PPS, semi… via `realtime_processing.custom_vocabulary` et `custom_vocabulary_config`. La reconnaissance d'entités en temps réel (`realtime_processing.named_entity_recognition=true`) peut aider à repérer lieux, dates et montants.
- **Correction vocale** : transmettre la consigne transcrite à `session.send_message(...)` ; H la prend en compte **à l'étape suivante**. `pause()` / `cancel()` pour la pause ou l'arrêt vocal : c'est du **contrôle utilisateur et de la supervision**, pas seulement une entrée micro.
- **Pas de TTS Gladia trouvé dans la documentation consultée** : prévoir la synthèse vocale du navigateur ou des réponses à l'écran.

Docs : [démarrage live Gladia](https://docs.gladia.io/chapters/live-stt/quickstart), [transcriptions partielles](https://docs.gladia.io/chapters/live-stt/features/partial-transcripts), [vocabulaire personnalisé](https://docs.gladia.io/chapters/audio-intelligence/custom-vocabulary), [entités nommées](https://docs.gladia.io/chapters/audio-intelligence/named-entity-recognition), [pilotage des sessions H](https://hub.hcompany.ai/agents-api/observe-and-steer).

### Pipeline cible

**Voix → Gladia → intention → Linkup structuré → 3 agents H en parallèle sur la bonne URL → correction/stop vocal → récap → « oui » vocal → arrêt avant paiement.**

Le « oui » valide la préparation, jamais un paiement ni une réservation finale.

## Projets déjà faits (H Showcase)

Source : le [H Showcase](https://showcase.hcompany.ai/), qui liste 35 agents construits sur l'API H Agents. On y trouve des démos officielles de H et les projets du hackathon de San Francisco.

Le tri de ce qu'on peut reprendre, par priorité, est dans [FEATURES_A_REPRENDRE.md](FEATURES_A_REPRENDRE.md).

### Les plus proches de notre idée

| Projet | Ce qu'il fait | Recoupement avec RunAI |
| --- | --- | --- |
| **Life-Admin Operator** (Hackathon SF) | Agent piloté uniquement à la voix sur de vrais sites, qui demande avant toute action irréversible | Même UX que nous : la voix et l'arrêt avant le paiement. **Ce n'est donc pas un argument d'originalité** |
| **Kylian** (Hackathon SF) | On l'appelle ou on lui écrit sur WhatsApp, et il agit sur l'ordinateur en notre absence | Assistant vocal généraliste |
| **BuyWith402** (Hackathon SF) | Des agents navigateur H remplissent des commandes sur n'importe quel site | Remplissage de formulaires jusqu'au checkout |
| **Workfleet** (Hackathon SF) | Clone l'ordinateur pour faire travailler plusieurs agents en parallèle | Agents en parallèle |
| **Hiking Routes in Google Maps** (Hackathon SF) | Planifie des randonnées urbaines et les trace dans Google Maps | Seul projet lié au sport ou à l'outdoor |
| **Add to cart**, **Product availability**, **Price Check**, **Pricehunter** | Démos e-commerce : panier, stock, prix, codes promo | Briques de navigation e-commerce, sans orchestration |

**Zoom sur [Life-Admin Operator](https://github.com/chinesepowered/hack-h)** (Hackathon SF), **le projet le plus proche du nôtre** : un agent pensé pour les personnes qui ne voient pas l'écran, qui fonctionne entièrement à la voix. On dit « annule mon abonnement » ou « inscris-moi à cet événement », et il le fait sur le vrai site.
- Un planificateur découpe l'objectif en étapes et les lit à voix haute avant de commencer.
- L'agent annonce chaque étape à voix haute et gère les connexions, les formulaires, les pop-ups et les boutons de confirmation.
- Il attend un « oui » prononcé avant toute action irréversible (acheter, supprimer, valider). La sécurité fait partie de l'architecture.
- Démo principale : **l'inscription à un vrai événement Luma, avec un arrêt avant le bouton Register**. Il existe aussi un mode de secours (remplir un formulaire), une démo hors ligne des trois garde-fous de sécurité, et une vérification du micro.

*Ce que ça implique pour RunAI* : « inscris-moi, à la voix, avec un arrêt avant de valider » **a déjà été montré au jury de SF**. Notre originalité ne peut pas reposer là-dessus. Elle doit venir de :
1. **La verticale course à pied** : le profil coureur réutilisé (PPS ou certificat à téléverser, taille de t-shirt, club, contact d'urgence) et les plateformes spécifiques (Njuko, Klikego…).
2. **Une seule intention, plusieurs agents coordonnés** (course, hôtel, transport), en parallèle avec une vue live. Life-Admin Operator ne fait qu'une tâche à la fois.
3. **La vérification avant paiement** par un agent indépendant (voir Houston) et la chaîne Linkup → H.

Bonnes idées à reprendre : lire le plan à voix haute avant d'agir, et préparer une démo de secours hors ligne qui montre les garde-fous.

**Zoom sur [Price Check](https://showcase.hcompany.ai/a/price-check-test/)** (From H) : un seul agent `h/browser` ouvre la page de tarifs d'un éditeur (dans l'exemple, linear.app/pricing) et donne le prix du moins cher des plans payants. La fiche affiche la trace du run étape par étape (« ouvre linear.app », « clique sur le bouton Billed yearly », « répond »), avec le raisonnement de l'agent à chaque étape. Dans l'exemple, l'agent remarque que le tarif annuel est affiché par défaut et bascule sur le mensuel : 12 $ au lieu de 10 $.
*À reprendre pour RunAI* : afficher ce genre de trace étape par étape dans notre vue de supervision. Et prévoir que l'agent vérifie les options qui changent un prix (annuel ou mensuel, distance de course, options payantes) avant de présenter le récap au coureur.

**Zoom sur [Add to cart](https://github.com/hcompai/agents-api-demos/tree/main/examples/add_to_cart)** (From H, 3 runs sur 3 réussis) : un seul fichier Python et quelques lignes du SDK `hai-agents` autour d'un prompt en langage naturel. L'agent (`holo4-27b`, `h/browser`, skills `h/planning` et `h/answering`) cherche un album sur Amazon, l'ajoute au panier et vérifie qu'il y est, sans utiliser l'API du magasin. Le prompt se termine par « Do not check out », et le champ `added_to_cart` ne vaut `true` que si la page panier affiche bien l'article.
*À reprendre pour RunAI* : c'est le point de départ le plus simple pour le **test de faisabilité**. On garde la même logique d'arrêt avant le paiement, avec un booléen vérifié à l'écran (par exemple `form_ready_for_payment`).

**Zoom sur [Pricehunter](https://github.com/lmveprog/pricehunter)** (communauté) : on colle le lien d'un produit. Des agents web H lisent la page, cherchent des codes promo pour ce magasin et les testent dans le panier. D'autres cherchent le même produit neuf chez des revendeurs fiables. On suit chaque navigateur en direct, puis on obtient une seule réponse : où acheter, et avec quel code.
- `server.py` en FastAPI : chaque agent est une session de l'API Agents (`h/web-surfer-flash`), avec un schéma JSON passé dans `agent.answer_format` pour recevoir des réponses structurées.
- `web/index.html` : une seule page, sans étape de build.
- Le **filtre de sécurité** (même variante, neuf, vendu par le magasin, en stock) tourne **côté serveur, pas seulement dans le prompt**.

*À reprendre pour RunAI* : c'est presque notre architecture (plusieurs sessions H en parallèle, vue live, une réponse consolidée). Le code est sous licence MIT, donc on peut s'en inspirer directement. À retenir surtout : valider côté serveur ce que l'agent renvoie (bonne course, bonne distance, prix, arrêt avant le paiement) au lieu de se fier uniquement au prompt.

**Zoom sur [Hiking Routes in Google Maps](https://github.com/Exynos-8890/0711hack)** (Hackathon SF), **le seul projet lié au sport** : les randonnées urbaines ne rentrent pas dans les itinéraires classiques de Google Maps. NVIDIA NemoClaw conçoit l'itinéraire et le vérifie. Un agent navigateur H le trace dans Google Maps, puis renvoie des captures et un lien de partage. Si un point de passage est faux, il est corrigé sur place, sans tout recommencer.
*À reprendre pour RunAI* :
- Séparer le « cerveau » qui planifie (chez nous, Linkup et le LLM) de l'agent H qui exécute.
- Rendre au coureur des preuves directement utilisables : captures du formulaire rempli, lien vers la page de paiement.
- Corriger une erreur sur place (« prends plutôt le 21 km ») au lieu de relancer tout le parcours.

Le sport reste donc quasiment libre dans le showcase : ce projet fait de la planification d'itinéraire, pas de l'inscription ni de la logistique de course.

**Zoom sur [Workfleet](https://github.com/WillVo1/WorkFleet)** (Hackathon SF) : un agent de computer use prend le contrôle du curseur, donc une appli desktop comme SAP ne peut accueillir qu'un agent à la fois, et l'utilisateur ne peut plus se servir de sa machine. Workfleet crée des clones de l'ordinateur, chacun synchronisé avec les fichiers et les applis de l'utilisateur. Plusieurs agents travaillent ainsi en parallèle pendant qu'il continue sur son propre portable. Backend FastAPI, avec des machines virtuelles sur GCP.
*À reprendre pour RunAI* : notre parallélisme (course, hôtel, transport) est plus simple, puisque chaque agent H a déjà son propre navigateur cloud. Pas besoin de cloner une machine. En revanche, l'argument est le même pour le pitch : **le coureur garde la main pendant que les agents travaillent**, et il les suit dans la vue live.

### Les autres catégories

- **QA et tests** : QA any web UI, A-Test, GrannySmith, Simulation Labs, Houston.
  - [A-Test](https://github.com/dzianisv/a-test) (Hackathon SF) : des cas de test écrits en langage courant, tirés des cas d'usage du cahier des charges, sont exécutés par un agent de computer use (modèles Holo 3.1) dans la CI. Une GitHub Action réutilisable bloque toute PR qui casse l'appli. Ça marche sur les applis web Chrome, les extensions, les émulateurs Android et iOS et les applis en terminal. Leur argument : les agents de code ont besoin d'un vrai retour, pas d'être surveillés en permanence.
    *À reprendre pour RunAI* : écrire en langage courant les **scénarios de la démo** (« inscris-moi au semi de Paris en 21 km », « change la taille de t-shirt »…) et les faire rejouer automatiquement sur notre faux site d'inscription à chaque PR. Devin, qui code le projet, recevrait ainsi un vrai retour. C'est aussi une piste pour le prix « Best Use of Devin ».
  - [Houston](https://github.com/nossa-y/houston-hackathon) (Hackathon SF) : une « tour de contrôle » qui ne croit jamais un agent sur parole quand il dit avoir fini. Chaque mission suit quatre étapes :
    1. **Exécution** : une session H réalise la tâche, demandée à la voix ou par écrit.
    2. **Audit** : une seconde session H, indépendante, refait la vérification sur le site en ligne et renvoie un verdict typé.
    3. **Correction et arbitrage** : si le résultat est rejeté, l'agent est relancé dans la même session en cours (steering). Si sa réponse change, un arbitre tranche en inspectant la page.
    4. **Preuve** : un reçu chaîné par hash, avec des replays publics étape par étape, résumé à voix haute.

    Stack : sessions H et steering, Gradium pour la voix (transcription et synthèse), Holo 3.1 en local, NVIDIA NemoClaw.
    *À reprendre pour RunAI* : c'est la réponse la plus directe au critère « fiabilité » (25 % de la note). Une fois le formulaire rempli, un **agent vérificateur H** relit la page avant le paiement : bonne course, bonne distance, bonnes infos du coureur. En cas d'écart, on corrige l'agent dans la même session plutôt que de tout relancer. Et chaque mission se termine par un récap rejouable.
  - [QA any web UI](https://github.com/hcompai/agents-api-demos/tree/main/examples/qa) (From H) : un serveur FastMCP expose un agent navigateur H sous forme de deux outils. `review_web_ui` fait une revue complète d'une URL (usabilité, accessibilité, liens cassés) et renvoie `{verdict, summary, findings, steps_taken}`. `visual_check` répond à une question sur une page. Le même agent existe aussi en CLI, avec un skill Claude Code. Il tourne sur `holo4-27b` avec `h/browser`, un skill maison `design-qa-checklist` et `h/planning`.
    *À reprendre pour RunAI* : c'est le modèle pour **exposer un agent H comme outil MCP**. On pourrait l'utiliser pour faire vérifier notre faux site d'inscription par Devin avant la démo, ce qui ferait aussi un argument pour le prix « Best Use of Devin ». Autre idée : écrire nos propres skills dans l'`agent.json` (par exemple une checklist « formulaire d'inscription »).
  - [GrannySmith](https://github.com/ducnguyen67201/AngryGrandmy) (Hackathon SF) : des agents qui jouent des utilisateurs prudents parcourent un produit (inscription, checkout). Ils hésitent, reviennent en arrière et réfléchissent à voix haute. Tout est enregistré (captures, actions, trajet du curseur, réactions vocales, heatmaps) en trajectoires rejouables, puis transformé en constats d'utilisabilité et en propositions de correctifs. Stack : sessions H, Gradium pour la voix (un concurrent de Gladia), NVIDIA Nemotron et VSS pour l'analyse visuelle.
    *À reprendre pour RunAI* : enregistrer chaque run de l'agent (captures et actions horodatées) et le rejouer. C'est une preuve concrète pour les critères « fiabilité » et « contrôle utilisateur ».
- **Apprendre des vidéos et rejouer** : Holo Forge, Reel-Learn, AI Runbooks, ImproveMe, Voodoo.
  - [AI Runbooks](https://github.com/omkarpat/ai-runbooks) (Hackathon SF) : on enregistre une fois une démarche en vidéo d'écran. L'agent en extrait les étapes, les range dans une base consultable et fusionne plusieurs enregistrements de la même démarche en un seul runbook de référence. Il le rejoue ensuite dans un navigateur cloud H et indique, pour chaque étape, si elle a été vérifiée par rapport à l'enregistrement d'origine.
    *À reprendre pour RunAI* : préparer un **runbook par plateforme d'inscription** (Njuko, Klikego…). On enregistre une inscription faite à la main, puis on donne à l'agent ce guide étape par étape, avec un critère de vérification pour chaque étape. C'est un bon moyen de fiabiliser la démo sur des sites connus.
  - [Voodoo](https://github.com/Masmedeam/holo-tuto) (Hackathon SF) : on colle l'URL d'une appli web et on dit ce qu'il faut expliquer, avec la voix, le ton et la durée voulus. Un agent navigateur H explore le parcours et repère les moments importants. Voodoo écrit ensuite un court script, le fait lire par une voix de synthèse et produit une vidéo tutoriel animée en MP4.
    *À reprendre pour RunAI* : générer automatiquement, à la fin de chaque mission, une **courte vidéo récap commentée** des actions de l'agent. C'est utile au coureur, et aussi pour la vidéo de démo et les posts LinkedIn ou X, qui ont leurs propres prix de 500 €.
  - [ImproveMe](https://github.com/zach2940/improveme) (Hackathon SF) : observe une journée de travail et repère les routines qui se répètent, grâce à Claude. L'utilisateur répond oui ou non pour chaque routine à garder, sans script ni API. Holo 3.1 rejoue ensuite ces routines seul, selon un planning. Chaque étape est une consigne en langage naturel : si un site change de mise en page, l'agent retrouve ses repères et continue. NemoClaw choisit quand lancer chaque run et envoie un message WhatsApp quand il est terminé.
    *À reprendre pour RunAI* :
    - Formuler les étapes de l'agent en langage naturel plutôt qu'en sélecteurs figés. Elles résistent mieux aux changements des plateformes d'inscription.
    - Envoyer une notification (WhatsApp) quand l'inscription est prête à payer.
    - Une piste « vision » : surveiller l'ouverture des inscriptions d'une course et lancer l'agent automatiquement à l'heure d'ouverture.
  - [Reel-Learn](https://github.com/ipsita-praharaj/Reel-Learn) (Hackathon SF) : un premier agent regarde un tutoriel YouTube comme le ferait une personne (il avance, met en pause, observe les images, sans sous-titres ni transcription). Il en tire un plan en étapes atomiques, chacune illustrée par une image de la vidéo montrant le résultat attendu. Un second agent applique ce plan dans le vrai Audacity, sur un enregistrement bruité. La réussite est **mesurée** : le bruit de fond doit baisser d'au moins 6 dB, sinon le run échoue. Chaque échec est classé puis réinjecté dans le plan comme garde-fou pour le run suivant.
    Leur constat : sans ce mécanisme, l'agent a répété un clic quasi identique une quarantaine de fois sur une session de 76 étapes, sans jamais s'en rendre compte.
    *À reprendre pour RunAI* :
    - Définir pour chaque étape un **critère de réussite vérifiable**, par exemple « la page récap affiche le bon nom, la bonne distance et le bon prix ».
    - **Détecter les boucles** (même action répétée) et rendre la main au coureur dans ce cas.
  - [Holo Forge](https://github.com/exemplary-citizen/computer-use-hackathon) (Hackathon SF) : un expert filme une tâche en la commentant et envoie la vidéo sur Telegram. Gradium transcrit, puis NemoClaw et Hermes en font une automatisation versionnée, que l'expert relit et approuve. HoloDesktop l'exécute ensuite sur macOS, y compris dans des applis anciennes sans API. Les entrées, validations et statuts passent par des boutons Telegram. Démo : traiter des demandes de retour reçues dans Apple Mail via une appli interne ancienne.
    *À reprendre pour RunAI* : piloter l'agent à distance depuis une messagerie (Telegram ou WhatsApp), avec des boutons de validation, par exemple pour l'étape avant le paiement.
- **Agents métier ou applis desktop** : ArcFlash Copilot, Claw-DJ (Mixxx), Cloud CUA (console AWS), Holodev (Roblox Studio), CUA Molecular Visualizer, AI Teaching Assistant.
  - [CUA Molecular Visualizer](https://github.com/RyanDennis916/NUA-Computer-Use) (Hackathon SF) : on demande à voix haute ou par écrit ce qu'on veut voir d'une molécule ou d'une protéine. Un agent orchestrateur (GLM-5.2, via NemoClaw/OpenClaw) modifie les paramètres de la visualisation en coulisses, pendant que Holo suit la structure à l'écran et la manipule directement.
    *À reprendre pour RunAI* : encore une fois, l'orchestrateur qui décide est séparé de Holo qui agit à l'écran. On garde ce principe : notre orchestrateur interprète l'intention du coureur et répartit le travail, et chaque agent H n'a qu'une mission précise.
  - [Claw-DJ](https://github.com/InServiceOfX/claw-dj) (Hackathon SF) : on décrit le set voulu (ambiance, énergie, durée). Des agents H (`hai_agents`) choisissent les morceaux dans la bibliothèque locale et décident de l'ordre du mix. NVIDIA NemoClaw et Nemotron servent de moteur d'agent alternatif. Une couche **déterministe** en Python et Rust pilote ensuite Mixxx pour un mix calé sur le tempo, en direct.
    *À reprendre pour RunAI* : réserver l'agent aux décisions (quelle course, quel hôtel, quelles options) et à la navigation sur des sites qu'on ne connaît pas. Tout ce qui peut être déterministe reste en code classique : le profil coureur, le calcul des dates et des distances, la validation du récap. C'est plus fiable et plus rapide en démo.
  - [ArcFlash Copilot](https://github.com/techadnank9/arcflash) (Hackathon SF) : prépare des brouillons d'études d'arc électrique, un travail de plusieurs heures de clics répétitifs dans le navigateur. L'agent fait les clics et conserve des preuves traçables. Les données manquantes restent à `null` et sont signalées à l'ingénieur au lieu d'être inventées. Le rapport est clairement marqué comme brouillon, et l'agent s'arrête à une validation explicite. Leur principe : « L'agent fait les clics, l'ingénieur garde le jugement. »
    *À reprendre pour RunAI* : **ne jamais inventer une info du coureur**. Un champ manquant (numéro de licence, contact d'urgence…) reste vide et déclenche une question vocale au coureur. Le récap présenté avant le paiement doit signaler ce qui a été rempli et ce qui manque, avec la preuve correspondante (capture du formulaire).
  - [Cloud CUA](https://github.com/Jiyungi/cloud_CUA) (Hackathon SF) : un serveur MCP qui prend un repo terminé et le déploie en pilotant la vraie console AWS.
    1. Codex étudie le repo et rédige un « contrat de déploiement » précis.
    2. Un agent H pilote la console comme le ferait une personne, et s'adapte quand AWS affiche un parcours différent.
    3. Le déploiement est vérifié de façon indépendante via les API AWS, CloudTrail, des requêtes HTTP et Playwright, avec validation humaine et contrôle des coûts.
    4. Chaque erreur devient une règle relue, ajoutée à une bibliothèque de skills hébergée chez H. La session suivante ne refait pas la même erreur.

    Voix : Gradium (transcription en direct et explications parlées).
    *À reprendre pour RunAI* :
    - Faire préparer à un agent de code (Devin pour nous) un « contrat » que l'agent H exécute. Ça montre Devin *dans* le produit, un bon argument pour le prix « Best Use of Devin ».
    - Vérifier le résultat par un autre canal que l'agent lui-même.
    - Transformer les erreurs de l'agent sur une plateforme d'inscription en skills réutilisables (par exemple « sur Njuko, le certificat se téléverse à l'étape 3 »).
- **Divers** : HoloMobile (mobile), Halo (panneau Chrome), Privacy Layer, Snowglobe, FollowThrough, Agent Kalshi, Glassbox, HoloBlocks et HoloBricks.
  - [HoloMobile](https://github.com/swswsw/AndroidUseH) (Hackathon SF) : un agent « mobile use » basé sur les modèles Holo. Il pilote de vraies applis Android de bout en bout : on donne une tâche en langage naturel, il voit l'écran, tape et enchaîne plusieurs étapes, y compris entre plusieurs applis, sans API.
    *Pour RunAI* : une piste pour plus tard. Certaines inscriptions ou certains suivis passent par des applis mobiles (applis de courses, appli SNCF…). Pour le hackathon, on reste sur le web.
  - [Halo](https://github.com/vaibhavgeek/hcompany-hack-sf) (Hackathon SF) : une extension Chrome (MV3) qui ouvre un panneau latéral sur n'importe quelle page. On dit en langage courant ce qu'on veut, ou on choisit un modèle de tâche préenregistré pour les actions fréquentes, et l'agent H pilote la page, voire en réorganise la mise en page.
    *À reprendre pour RunAI* : l'idée des **modèles de tâches** (« inscris-moi avec mon profil habituel »). Une extension Chrome pourrait aussi servir de piste « vision » : le coureur est sur la page d'une course, il clique, et RunAI remplit l'inscription. Pour le hackathon, on reste sur notre PWA avec les navigateurs cloud H.
  - [Agent Kalshi](https://github.com/DhruvMiyani/hcompany-hack26) (Hackathon SF) : un modèle de machine learning qui s'améliore tout seul choisit un marché de paris sur la Coupe du monde (sur Kalshi), le côté à jouer et la mise. Un agent navigateur H place ensuite le pari en direct sur le site. Un humain peut relire chaque pari avant qu'il parte.
    *À reprendre pour RunAI* : la même séparation entre **le code qui décide** (ici un modèle ML, chez nous Linkup, le profil et les règles) et **l'agent H qui exécute** sur le site, avec une validation humaine avant l'action qui engage de l'argent. C'est aussi un rare projet lié au sport dans le showcase, mais sous l'angle des paris, pas de la pratique.
  - [Privacy Layer for Visual Agents](https://github.com/dael-amz/browser-agent-privacy-layer) (Hackathon SF) : un agent de computer use envoie des captures d'écran au modèle dans le cloud, mots de passe compris. Cette couche se place entre HoloDesktop et le modèle et floute chaque capture sur la machine (CoreML, environ 120 ms par image). En cas de doute, elle bloque l'image plutôt que de la laisser passer. Les données personnelles sont rangées dans un coffre en mémoire et remplacées par des jetons, qui ne redeviennent de vraies valeurs qu'au moment où l'action est exécutée. Un petit modèle local (Qwen3-4B, dans un bac à sable NemoClaw sans accès réseau) décide quand un secret peut être utilisé. Le tout est vérifié par de vrais runs Holo 3 et 338 tests.
    *À reprendre pour RunAI* : l'agent manipule des données sensibles du coureur (date de naissance, adresse, numéro de licence, certificat médical, contact d'urgence). Sans aller jusqu'au floutage sur la machine, on peut appliquer le principe des jetons : le prompt de l'agent contient des références (`{{runner.birth_date}}`), et le serveur ne fournit la vraie valeur qu'au moment de remplir le champ. C'est un bon argument « confiance » pour le pitch.
  - [FollowThrough](https://github.com/yhinai/followthrough) (Hackathon SF) : après une conversation, les relances promises ne sont souvent jamais faites. FollowThrough écoute la conversation, avec le consentement des participants (audio temps réel LiveKit, transcrit par Gemini). Des agents H recherchent ensuite sur le web ce qui a été évoqué. Hermes orchestre et livre chaque action de suivi, avec sa source.
    *À reprendre pour RunAI* : c'est le même enchaînement que le nôtre (voix → recherche → actions traçables). Il a donc déjà été montré, ce qui confirme que notre originalité doit venir de la verticale course à pied et de l'action concrète sur les sites d'inscription, pas de la simple chaîne voix + recherche.
- **Démos « From H » sous forme d'app web** : [HoloBlocks](https://blocks.hcompany.ai/) ([code](https://github.com/hcompai/holoblocks)). On décrit une construction ou on donne une photo, Holo la bâtit bloc par bloc en 3D, puis on peut l'exporter vers Minecraft. [HoloBricks](https://bricks.hcompany.ai/) ([code](https://github.com/hcompai/holobricks)) fait la même chose en vraies briques, et fournit la liste des pièces à commander pour la monter chez soi. Les deux sont des exemples open source d'apps web complètes (serveur Python + front npm) construites autour de l'API Agents.

### Ressources utiles pour construire

Tirées de la fiche [Product availability](https://showcase.hcompany.ai/p/product-availability/) :

- **Code des démos officielles** : [hcompai/agents-api-demos](https://github.com/hcompai/agents-api-demos). Par exemple [product_availability](https://github.com/hcompai/agents-api-demos/tree/main/examples/product_availability), une bonne base pour une réponse typée (validée avec zod).
- **Un agent = un `agent.json`**, envoyé en corps de `POST /api/v2/agents`. Il contient le modèle (`holo4-27b`), l'outil `h/browser`, les skills `h/planning` et `h/answering`, et le schéma de la réponse attendue.
- **Skill `/hai-agents`** : génère le projet d'un agent à partir d'une seule phrase.
- **Holo Desktop** : fait tourner un agent sur son propre navigateur plutôt que dans le cloud browser (`curl -fsSL https://install.hcompany.ai/install.sh | bash && holo login`). Pratique pour tester en local.
- **On peut soumettre RunAI au showcase** après le hackathon : [showcase.hcompany.ai/submit](https://showcase.hcompany.ai/submit/).

### Ce qu'on en retient

- **Aucun projet ne porte sur la course à pied, l'inscription à une course ou le déplacement sportif.** La verticale reste libre.
- La voix et la validation avant une action irréversible existent déjà (Life-Admin Operator). L'originalité doit venir d'ailleurs : **une seule intention qui déclenche plusieurs agents coordonnés** (course, hôtel, transport), le profil coureur (PPS, certificat, t-shirt) et la chaîne Linkup → H.
- Le jury a déjà vu beaucoup d'agents « QA » et « rejouer une vidéo ». Mieux vaut éviter ces angles.

## Valorisation des partenaires

| Partenaire | Rôle actuel | Valorisation | À ajouter |
| --- | --- | --- | --- |
| H | 3 agents en parallèle, outils, correction en cours, vue live | Forte (cœur) | Sous-agents H (coordinateur voyage qui délègue), agent vérificateur du récap avant paiement, Models API Holo (ex. vérifier une capture du récap) — non utilisé pour l'instant |
| Gladia | Commande vocale, correction et stop | Moyenne (STT seulement) | Voir [GLADIA.md](GLADIA.md) |
| Linkup | Prépare course, départ, URL | Bonne (gain ~2× mesuré, essai unique avec cible différente) | Vérification des faits avant réservation (date, règlement, PPS), comparaison hôtels/vols avant H, recherche `deep` pour le règlement, sources affichées dans le récap |
| Devin | Construction + auto-réparation | Forte si l'idée 1 est livrée | Voir [DEVIN.md](DEVIN.md) (PR #13) |
| Stripe | Hors périmètre | Nulle | Stripe Checkout en mode test pour une « commission RunAI » quand le coureur valide : l'humain paie, l'agent jamais ; ~1 h, P1 tardif si le parcours tient à 19 h |

Chaque partenaire doit avoir son moment visible dans la démo : voix (Gladia), sources (Linkup), agents live (H), PR de réparation (Devin), paiement validé par l'humain (Stripe).

## Questions ouvertes

1. ~~Quel fil rouge ?~~ Orientation : une feature unique, « déplacement course complet » (voir plus haut). Périmètre course + hôtel + vol confirmé par le test de faisabilité.
2. Combien sommes-nous, et qui fait quoi ?
3. Vraies plateformes ou faux site pour la démo ?
4. ~~Quel test de faisabilité H on lance en premier ?~~ Test réalisé, résultats ci-dessus.
