# Démo et livrables : comment on procède

> Objectif : arriver dimanche matin avec tout préparé, pour que le jour J ne serve qu'à exécuter. Les points marqués **à décider** ou **à vérifier** restent ouverts.

## Principes

- **Produit générique, démo sécurisée** : RunAI accepte n'importe quelle course. Pour le jury, on montre une course **qu'on sait ouverte** sur une plateforme déjà testée (Njuko ou Klikego), plus un essai « donnez-nous une course ».
- **Un seul vrai run filmé** pour la vidéo, hors créneau de démo. On ne génère pas la vidéo dans la CI à chaque PR, pour ne pas consommer les slots et les tokens H.
- **3 slots H pour toute l'organisation.** Une session en pause ou en attente garde son slot. Benchmark, vidéo et démo ne doivent jamais se chevaucher. Plus rien ne tourne dans la CI côté H pendant les passages.
- **Rien n'est payé.** Tous les agents s'arrêtent avant paiement. Données fictives uniquement (aucune vraie identité, adresse ou contact d'urgence).
- **Sites retenus** : Njuko ou Klikego (inscription), Accor (hôtel). Booking et Airbnb sont exclus : leurs CGU interdisent les assistants IA. Transport : vol (TAP) ou Trainline, **à décider** (SNCF Connect et OUIGO affichent un captcha).

## Ce qu'on sait déjà (vérifié le 7 nov.)

| Point | Résultat |
| --- | --- |
| Clés H, Gladia, Linkup | Appels HTTP 200 |
| Attente au portail | Une session H est restée **19,5 min** en `awaiting_tool_results`, sans client connecté, puis un `send_message` l'a relancée et elle s'est terminée en succès (un seul essai) |
| Coût d'un run court | ~230 000 à 260 000 tokens ; ~59,5 M restants sur 60 M |
| Durée d'un run complet | 10 à 15 min (40 à 64 étapes) |
| Semi de Lisbonne 2027 | Complet, hors Njuko : inutilisable comme démo principale |

## Planning

### Samedi soir (avant 21h, fermeture du lieu)

- [ ] **Choisir la course de démo** : une course ouverte sur Njuko ou Klikego, avec un hôtel Accor et un transport faisables. Garder une 2e course en secours.
- [ ] Écrire le **script de la vidéo** (voix off, ~3 min), voir [Vidéo](#vidéo-de-démo-livrable-4).
- [ ] Préparer le **profil coureur fictif** (nom, date de naissance, e-mail jetable, licence ou PPS fictifs).
- [ ] Enregistrer **10 phrases de démo** dans la salle pour régler Gladia (bruit, fin de phrase).
- [ ] Rédiger les brouillons des livrables 3, 5 et 6 (modèles ci-dessous).

### Nuit (sans intervention humaine)

- [ ] **Banc de fiabilité** : 5 runs par plateforme, par vagues de 3, pour un tableau « x réussites sur 5 » et la durée médiane. Compter 70 à 105 min si les 3 slots sont libres.
- [ ] Corriger les skills H des plateformes qui échouent (boucle Devin, si elle est en place).

### Dimanche 8 novembre

| Heure | Quoi | Slots H |
| --- | --- | --- |
| 8h00 | Réouverture. Vérifier les clés, le quota H (`GET /api/v2/sessions/quota` : 0 actif) et le résultat du banc de nuit | 0 |
| 8h30 | Dernières corrections du parcours principal | 0 à 1 |
| **9h00** | **Run filmé pour la vidéo** : 3 agents en parallèle, capture Playwright de l'appli, commandes vocales réelles | 3 |
| 9h30 | Génération de la vidéo (voix off, sous-titres Gladia, montage ffmpeg) | 0 |
| 10h30 | Relecture de la vidéo, upload YouTube en « non répertorié » | 0 |
| 11h00 | Livrables 3, 5 et 6 finalisés ; fiche H Showcase remplie | 0 |
| 11h30 | **Répétition complète** de la démo live, chronométrée | 3 |
| **12h00** | **Gel du code** : uniquement des correctifs bloquants ensuite | 0 |
| 13h00 | Relecture de « Review what judges will see » sur le dashboard | 0 |
| **13h30** | **Soumission** (marge de 30 min sur 14h00) | 0 |
| 14h30 | Premier tour de jugement : lancer les 3 sessions ~12 min avant notre passage | 3 |
| 15h45 | Pitchs finaux (si qualifiés) : même procédure | 3 |

**À vérifier** sur Discord ou auprès des organisateurs : le format du premier tour (démo à la table ou sur scène ?) et notre horaire de passage.

## Démo live

### Déroulé (environ 3 min)

1. **0:00, le problème** : « S'inscrire à une course, c'est 3 sites, 40 champs, des règlements à lire. »
2. **0:20, la voix** : on dit la course au micro. Les transcriptions partielles Gladia s'affichent et Linkup lance la recherche avant la fin de la phrase.
3. **0:40, le plan** : RunAI affiche la date, le lieu, le retrait du dossard et l'accès au départ, avec les sources Linkup. On dit « vas-y ».
4. **1:00, les agents** : 3 vues live H en parallèle (inscription, hôtel, transport), lancées ~12 min plus tôt.
5. **1:30, le contrôle** : « Stop ! » met l'agent en pause. « Prends plutôt le 10 km » le corrige en cours de route.
6. **2:00, l'agent remplit, l'humain signe** : l'agent s'arrête sur les cases santé, règlement et RGPD, et avant le paiement. Le coureur valide à la voix ou coche lui-même. Récap des 3 missions.
7. **2:30, les chiffres** : tableau de fiabilité du banc de nuit et, si elle est livrée, la PR Devin qui a réparé un skill.
8. **2:50, la conclusion** : « L'agent prépare tout, l'humain paie, jamais l'agent. »

### « Donnez-nous une course » (bonus)

Un juré dit une course à voix haute. On montre que Linkup la trouve, que la logistique se calcule et que l'agent part. On ne garde que **1 slot H libre** pour ça : on n'attend pas la fin, on revient au récap pendant les questions.

### Avant chaque passage

- [ ] Quota H : 0 session active avant de lancer les 3 sessions de démo.
- [ ] Session Gladia live ouverte récemment (3 h maximum). En offre gratuite, **une seule session live à la fois** : personne d'autre de l'équipe ne teste au même moment.
- [ ] Micro-casque branché, volume de la synthèse vocale réglé.
- [ ] Onglets ouverts : l'appli, les replays H du run filmé, la vidéo en secours, la PR Devin.
- [ ] Partage d'écran testé sur le projecteur.

### Plans de secours

| Problème | Réponse |
| --- | --- |
| Session H en file d'attente ou en échec | Basculer sur les replays du run de 9h00, puis sur la vidéo |
| Gladia refuse la connexion | Saisie au clavier dans la même interface ; la vidéo montre la voix |
| Wi-Fi instable | Partage de connexion d'un téléphone |
| Course de démo devenue complète | Course de secours, ou montrer la détection « complet » et la proposition de liste d'attente |

## Vidéo de démo (livrable 4)

Vidéo **générée par script**, sans logiciel de montage, relançable après chaque correction.

1. **Capture** : Playwright pilote l'appli pendant le run de 9h00 et enregistre l'écran (`recordVideo`). On récupère aussi les captures d'étapes et les liens de replay des sessions H.
2. **Voix off** : le script texte (~3 min, même déroulé que la démo live) est lu par une synthèse vocale : Piper (open source, local) ou ElevenLabs (offre gratuite limitée, attribution demandée). Les **commandes vocales à l'écran restent une vraie voix humaine**, enregistrée pendant le run. **À décider** : narration par synthèse ou par un membre de l'équipe.
3. **Sous-titres par Gladia** : transcription pré-enregistrée de la voix off et des commandes, export SRT ou VTT, incrusté dans la vidéo. C'est un usage Gladia de plus, visible à l'écran.
4. **Montage ffmpeg** : passages des agents accélérés ×4 à ×8 avec un compteur « temps réel : 11 min », carton titre, logos partenaires, fin sur le tableau de fiabilité. Export MP4 1080p.
5. **Publication** : upload manuel sur YouTube en « non répertorié » (l'automatiser demanderait une configuration OAuth).
6. **Déclinaison** : une version de 30 s pour les posts LinkedIn et X (500 € chacun).

Si le temps manque, une capture d'écran du run de 9h00 avec voix off enregistrée suffit.

## Les 6 livrables

| # | Champ | Responsable | Échéance | Statut |
| --- | --- | --- | --- | --- |
| 1 | Project Name | | | Fait : RunAI |
| 2 | Github Repo | | | Fait : [github.com/IbaDemesy/RunAI](https://github.com/IbaDemesy/RunAI) |
| 3 | Submission on H Showcase Platform | **à décider** | Dim. 11h00 | À faire |
| 4 | Demo Video URL | **à décider** | Dim. 10h30 | À faire |
| 5 | Project Description | **à décider** | Dim. 11h00 | Brouillon ci-dessous |
| 6 | How do I test your product live | **à décider** | Dim. 11h00 | Brouillon ci-dessous |

Le bouton « Submit » du [dashboard](https://builderbase.com/track-dashboard/h-company-42ai-computer-use-agents-hackathon/overview) ne se débloque qu'une fois les 6 champs remplis. La saisie est enregistrée au fur et à mesure : remplir les champs dès qu'ils sont prêts.

### 3. Fiche H Showcase (brouillon)

Sur [showcase.hcompany.ai/submit](https://showcase.hcompany.ai/submit/), sur le modèle des fiches existantes :

- **What it does** : tell RunAI which race you want to run, by voice. It finds the race, reads its rules, and prepares your registration, hotel and transport in parallel, then stops before every health, consent and payment step so you sign and pay yourself.
- **How it works** : Gladia live transcription drives the app (start, stop, correct the agents). Linkup finds the official race page, date and logistics. Three H agents (`h/web-surfer-pro`) fill the registration platform, the hotel site and the transport site in parallel, with a live view and typed results. Devin built the app and repairs platform skills when an agent fails.
- **Built with** : H Agents API, Gladia, Linkup, Devin.
- **Run it** : commandes du [README](../README.md#installation).

### 5. Project Description (brouillon)

> **RunAI : dis-moi ta course, je prépare tout le déplacement.** Le coureur dit sa course à la voix. Linkup trouve la page officielle, la date, le règlement et la logistique (retrait du dossard, accès au départ). Trois agents H préparent en parallèle l'inscription, l'hôtel et le transport sur les vrais sites, sans API. L'agent remplit, l'humain signe : il s'arrête sur chaque case santé, règlement et paiement. La voix sert de télécommande (stop, correction en cours de route). Partenaires : H, Gladia, Linkup, Devin.

Version anglaise à prévoir si le formulaire est lu par des jurés anglophones (**à vérifier**).

### 6. How do I test your product live (brouillon)

> 1. Ouvrir [URL de l'appli, à compléter] dans Chrome et autoriser le micro.
> 2. Dire : « Je veux courir [course de démo] » (ou taper la phrase).
> 3. Valider le plan avec « vas-y ». Trois agents H démarrent ; leurs vues live s'affichent en 1 à 2 min.
> 4. Essayer « stop », puis une correction (« prends plutôt le 10 km »).
> 5. Les agents s'arrêtent avant chaque case sensible et avant le paiement. **Rien n'est jamais payé ni soumis.**
>
> Un run complet dure 10 à 15 min et l'organisation dispose de 3 sessions H simultanées : si une session est en file d'attente, les replays d'un run complet sont ici : [liens, à compléter].

## Questions probables du jury

| Question | Réponse |
| --- | --- |
| Pourquoi pas une API ? | Njuko, Klikego et la plupart des sites d'hôtel n'ont pas d'API publique pour s'inscrire ou réserver : c'est le terrain du computer use. |
| Et Booking ? | Ses CGU interdisent les assistants IA. En production, on passerait par des partenariats ou des API affiliées. |
| Quelle fiabilité ? | Le tableau du banc de nuit : réussites sur 5 runs par plateforme, durée médiane. |
| Et si un site bloque ? | L'agent rend la main au coureur avec le lien et ce qu'il a déjà rempli. |
| Les données personnelles ? | Elles passent par le navigateur cloud H. Démo faite avec des données fictives. |
| Différence avec Meta Muse ? | Muse inscrit sur RunSignup (US, avec API). RunAI couvre les plateformes européennes sans API, et tout le déplacement autour. |

## Réseaux sociaux (500 € par plateforme)

- [ ] Post LinkedIn et post X avec la vidéo de 30 s, publiés dimanche avant 14h00 (**à vérifier** : règlement du prix et hashtag demandé).
- [ ] Mentionner H Company, 42AI, Gladia, Linkup et Cognition.
