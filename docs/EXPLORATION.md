# Exploration des features RunAI

> Document produit par un **workflow de 9 agents d'exploration + synthèse + critique**, avec deux tours d'avocat du diable et d'approfondissement. État des recherches : **7 novembre 2026**. **Critique finale non acceptée (`accepted: false`)** : le scénario reste une proposition, pas une démo validée.

Ce document complète [BRAINSTORM.md](BRAINSTORM.md), [RECHERCHES_AGENTS.md](RECHERCHES_AGENTS.md) et [FEATURES_A_REPRENDRE.md](FEATURES_A_REPRENDRE.md). Il conserve aussi les résultats qui contredisent les premières pistes : semi de Lisbonne complet, Booking et TAP écartés, passage de relais humain non démontré.

**Comment lire les preuves** : **vérifié — test** désigne une observation rapportée par les agents, sur une page ou une session précise ; **vérifié — doc** désigne une capacité documentée, pas testée dans RunAI ; **supposé / à vérifier** désigne une estimation ou une intégration non démontrée. La rédaction n'a pas relancé ces expériences. Un site accessible ne signifie ni inscription possible, ni automatisation autorisée.

## 1. Résumé

### Top 5 produit

Le top 5 regroupe les briques du récit ; ce n'est pas le classement numérique strict. La boucle Devin est un choix pour le prix sponsor, pas une dépendance du parcours coureur.

| Rang | Proposition | Pourquoi la retenir | Réserve décisive |
| --- | --- | --- | --- |
| 1 | **Séjour course cohérent** : inscription, hôtel et transport pour la même ville et les mêmes dates ; Plan B si la course est complète | Computer use central et résultat immédiatement utile | Course réellement disponible, CGU et chaque parcours à revalider ; pas de TAP ni de Booking |
| 2 | **Contraintes de course visibles** : retrait du dossard, accès au départ, retour après l'arrivée ; écran « pourquoi ce choix » sourcé | Le vrai différenciateur face à un assistant de voyage générique | Les contraintes du semi ne valent pas automatiquement pour le 7K, le 10K ou Milan |
| 3 | **Portail de contrôle à données minimales** : arrêt avant consentement, déclaration de santé, soumission et paiement | L'humain garde les engagements et les données sensibles | Pas de clic humain promis dans Agent View ; ressaisie personnelle en repli |
| 4 | **Télécommande vocale Gladia** : interruption, pause H, correction puis reprise | La voix contrôle réellement le computer use, au lieu de seulement dicter | Pause asynchrone : latence réelle non mesurée ; bruit de salle à tester |
| 5 | **Réparation Devin prouvée** : échec H horodaté → PR du runbook/Skill → nouveau test H | Argument pour « Best Use of Devin », avec preuves cliquables | Clé/API et boucle complète non disponibles comme preuve ; hors chemin critique |

### Recommandation

Construire **un seul parcours cohérent**, avec Linkup pour trouver les sources, du code pour calculer les contraintes et H pour agir là où une interface le justifie. Le socle P0 inclut aussi les réponses typées, le contrôle des résultats et le respect du quota.

- **Course** : ne plus promettre une inscription au semi de Lisbonne. Les formulaires 7K/10K contredisent le bandeau « complet » ; demander confirmation à l'organisateur, sans soumettre pour tester. **Milan sur Njuko est le repli documenté** : tarifs ouverts observés, parcours complet non testé pour cette course.
- **Hôtel** : Accor est une cible technique plus crédible que Booking, pas une autorisation juridique acquise. **Transport** : aucun remplacement de TAP n'est encore validé ; recherche et lien officiel manuels si aucune voie autorisée n'est trouvée. Ne pas automatiser TAP, même jusqu'à une simple sélection.
- **Démo minimale** : inscription et hôtel, à condition d'avoir vérifié les CGU applicables et un arrêt sûr ; transport guidé si nécessaire. Deux sessions H laissent un slot de secours. Trois agents simultanés restent un objectif conditionnel, pas un prérequis.
- **Sécurité** : aucune création de compte, soumission, réservation, publication ou transaction réelle. L'agent ne coche ni règlement ni déclaration de santé. En production, santé, PPS/certificat et contact d'un tiers restent hors du navigateur cloud ; arrêter plus tôt si le formulaire les exige.
- **P1 seulement après répétition du P0** : annulation, mesures de fiabilité, boucle Devin. Le survol 3D est un bonus ; entraînement et après-course restent en vision.

Les efforts ci-dessous sont des **estimations**, avec recouvrements. Le premier top 5 approchait 34 h, hors Linkup : trop chargé pour le temps disponible. Ne pas additionner des briques fusionnées ni confondre temps de développement et durée des tests.

## 2. Scénario de démo de 3 minutes

**Scénario proposé, non exécuté de bout en bout.** Choisir une seule course et vérifier ses conditions avant la répétition : Lisbonne uniquement après clarification du 7K/10K, sinon Milan. Tous les agents, horaires, hôtels et tracés suivent ce même choix. Ni Fertagus/Pragal ni les horaires du semi ne doivent être recyclés pour le 7K à Jamor.

**Avant le chrono** : arrêter les tests H de CI et le banc ; vérifier les sessions actives et le budget. Préparer un replay réel et l'annoncer comme tel. Pré-lancer au plus une mission déjà répétée pour la course choisie, sans données personnelles et sans soumission ; lancer l'hôtel en direct. Les 2,4–2,8 min observées sur des pages Accor/TAP ne garantissent ni le délai d'inscription ni celui d'une nouvelle compagnie. Pas de nouvelle session TAP.

| Temps | Ce que voit le jury | Preuve ou condition |
| --- | --- | --- |
| **0:00–0:20** | « Préparer une course à l'étranger oblige à recouper le règlement, le dossard et le voyage. » Le coureur dit la course choisie et sa ville de départ | Micro en appui pour parler ; aucune promesse de minutes gagnées non mesurées |
| **0:20–0:45** | Linkup affiche la page officielle, la date et les contraintes sourcées ; le coureur confirme le plan | Si Lisbonne est choisie, montrer le semi complet et les alternatives **à confirmer**, sans appeler le 7K « ouvert » sur la seule foi du formulaire |
| **0:45–1:15** | Vue live H de l'hôtel sur le site autorisé retenu ; une vignette montre l'inscription pré-lancée, annoncée comme telle | Si l'autorisation ou le parcours manque, montrer un replay autorisé ou réduire le périmètre, sans remplacer discrètement la ville |
| **1:15–1:40** | « Attends ! » → pause ; correction de la zone de l'hôtel → reprise. Afficher le transcript et les noms locaux | Mesurer séparément « détection vocale → demande de pause » et « demande → état paused ». N'afficher que des chiffres réellement mesurés |
| **1:40–2:10** | « Pourquoi ce choix » : hôtel accessible au bon point d'accès, arrivée avant le retrait du dossard, retour compatible | Dates et bornes calculées en code, chaque contrainte reliée à sa source ; transport manuel explicitement signalé si aucun site autorisé |
| **2:10–2:35** | Récap : bonne course, prix observé, champs manquants, conditions, arrêt avant toute case engageante ou envoi | Terminer l'agent. Ouvrir le lien officiel dans une session personnelle séparée, sans H, micro ni capture ; expliquer la ressaisie. Ne rien soumettre |
| **2:35–2:50** | Si elle existe : vraie trace d'échec H, session Devin, PR, puis nouveau run H et son critère de réussite | Preuves préparées hors démo, pas de réparation lancée dans un 4e slot. Sinon, présenter cette boucle comme non livrée |
| **2:50–3:00** | Résultat et limites : taux mesurés s'ils existent, sinon « répétitions encore insuffisantes » | « L'agent prépare, le coureur décide, signe et paie lui-même » |

**Replis** : voix en échec → bouton pause et saisie clavier ; agent bloqué → arrêt et replay annoncé ; captcha → aucun contournement ; course devenue complète → liste d'attente officielle ou changement **de tout le séjour**. Si les trois slots sont occupés, libérer un slot avant une relance. Le survol 3D ne prend du temps que si le tracé exact de l'épreuve est vérifié.

## 3. Toutes les features classées

**Inventaire** : les 58 propositions des 9 explorations sont regroupées en **36 lignes**, doublons et variantes explicités par axe en section 4. F01–F32 viennent du classement final ; F33–F36 rendent visibles quatre propositions non notées séparément dans cette synthèse. Leurs scores sont des **estimations éditoriales supplémentaires**, pas des résultats du workflow.

**Méthode du workflow** : computer use 25 %, exécution/fiabilité 25 %, utilité 20 %, originalité 15 %, UX/contrôle 10 %, démo 5 %, puis ajustement effort/risque. Les scores sont des jugements comparatifs sur 100, **pas des taux de réussite**. Les scores finaux sont conservés malgré les réserves ; une interdiction de CGU prime toujours sur la note. Tri par priorité, puis score décroissant ; identifiants stables pour les renvois.

**P0** : socle ; **P1** : après le socle ; **P2** : vision ; **écarté** : pas pour cette démo. Efforts en heures de développement estimées, non cumulables entre variantes. « Jusqu'au paiement » dans une idée initiale devient **arrêt plus tôt** dès qu'apparaît une donnée sensible, un consentement ou une soumission.

| ID | Nom / regroupement | Axe | Score /100 | Priorité | Rôle du computer use | Effort estimé |
| --- | --- | --- | ---: | --- | --- | --- |
| F01 | Séjour cohérent : inscription + hôtel + transport | Inscription / voyage | 79,5 | P0 conditionnel | H prépare les vrais parcours autorisés ; 3 agents seulement si validés | 3 h de reciblage, hors socle |
| F02 | Contraintes course + écran « pourquoi ce choix » | Voyage / dénivelé | 78,5 | P0 | H applique des bornes calculées en code ; lit les infos interactives | 4 h |
| F03 | Portail de contrôle à données minimales | UX / H | 74,5 | P0 | Outil bloquant, arrêt avant consentement et envoi ; relais séparé | 2 h + 2 h d'essai local |
| F04 | Plan B : course complète, alternative ou voie officielle | Inscription / après-course | 71,5 | P0 allégé | H lit le statut et prépare sans envoyer ; comparateur parallèle en P2 | 3 h ; version complète 5 h |
| F05 | Barge-in, correction multilingue et profil salle bruyante | Gladia | 68,5 | P0 | Gladia commande pause / message / reprise des sessions H | 3–4 h |
| F06 | Orchestration, réponses typées, contrôle H ↔ Linkup | Devin / Linkup / H | 67 | P0 | Quota, budgets, reprises et vérification des états visibles | 3 h, briques partagées |
| F07 | Linkup hybride : pré-recherche + outils de repli H | Linkup / H | 63 | P0 | H ne cherche dans le navigateur que si nécessaire, puis agit | 2–3 h |
| F08 | Annulation gratuite et date limite au récap | Voyage | 61,5 | P1 | H lit les conditions exactes du tarif choisi | 1,5 h |
| F09 | Banc et tableau de fiabilité mesurée | H / veille | 59 | P1 | H répète les parcours ; code calcule x/N et durée médiane | 2–3 h + temps des runs |
| F10 | Routage des sites : CGU, comptes, anti-bot | Voyage / fiabilité | 59 | P1 | H s'arrête sur captcha ou connexion, sans contournement | 2 h |
| F11 | Réparation Devin : échec H → PR/Skill → re-test H | Devin | 57 | P1 | H produit l'échec et vérifie la correction sur une page réelle | 5–6 h |
| F12 | Survol maison, profil et points clés, commande vocale | Parcours 3D / dénivelé | 55 | P1 bonus | Rendu et calculs en code ; H seulement pour collecter le tracé | 3–5 h, variantes non cumulées |
| F13 | Recherche Linkup anticipée sur les partiels | Gladia / Linkup | 50 | P1 | Aucun H avant transcript final et confirmation | 2 h |
| F14 | Narration et récap lus à voix haute | UX / Gladia | 46 | P1 | Aucun direct ; décrit les états H, TTS hors Gladia | 2 h |
| F15 | Éligibilité : PPS, licence, certificat, âge | Inscription | 59 | P2 | H lit exigences et restrictions, sans créer ni transmettre de pièce | 4 h |
| F16 | Demande de départ tardif / consigne | Voyage | 54,5 | P2 | H prépare la demande sur un site autorisé ; Booking exclu | 2,5 h + reciblage |
| F17 | Chasseur de tracé officiel + export GPX/KML | Parcours 3D / dénivelé | 53,5 | P2 | H trouve l'onglet/carte ; téléchargement et conversion en code | 3–4 h |
| F18 | Coordinateur avec sous-agents H natifs | Veille / orchestration | 53,5 | P2 | Manager et enfants H ; quota défavorable à la démo | 3 h |
| F19 | Inscription de groupe / club | Inscription | 53 | P2 | H remplit plusieurs participants, sans consentir ni envoyer | 4 h |
| F20 | Débrief : chrono, diplôme, photos multi-photographes | Après-course | 52,5 | P2 | H navigue entre chronométreur et galeries, sans achat | 5 h ; variante photos 4 h |
| F21 | Coffre à jetons pour les données coureur | Veille / confidentialité | 49,5 | P2 | Réduit l'exposition au modèle, pas celle du navigateur distant | 4 h |
| F22 | Météo/climatologie + allure par km, pente et vent | Dénivelé | 49 | P2 | Calculs/API, pas de computer use requis | 3 h par brique |
| F23 | Guetteur d'ouverture / loterie | Inscription | 47 | P2 | H lit le statut ; un fetch suffit souvent | 5 h |
| F24 | Journal vocal horodaté relié aux actions H | Gladia | 45 | P2 | Traçabilité des commandes ; résumé sans action externe | 2 h |
| F36 | Dictée fiable des données exactes | Gladia | 44,5* | P2 | Saisie H uniquement pour données autorisées ; pas de PPS en cloud | 3,5 h |
| F25 | E2E en langage naturel, H en CI, Devin Review | Devin / H | 43,5 | P2 | H exécute une spécification ; CI coupée pendant la démo | 4 h |
| F26 | Récap « montre-moi » et mode guidé | Veille / UX | 43,5 | P2 | H indique où agir ; reprise humaine cloud non prouvée | 5 h |
| F34 | Blessure : transfert officiel, revente ou assurance | Après-course | 41,5* | P2 | H lit les règles et prépare seulement ; compte réel souvent requis | 6 h |
| F35 | Réclamation chrono, SuperHalfs, palmarès | Après-course | 39,5* | P2 | H prépare les démarches, sans publication ni soumission | 3 h |
| F33 | Export vidéo du survol | Parcours 3D | 37,5* | P2 | Aucun : capture/encodage du rendu maison | 2 h |
| F27 | Google Earth web piloté par H | Parcours 3D | 48,5 | Écarté | Import KML possible ; lecture du tour et interface instables | 4 h |
| F28 | Garmin / Polar : course, plan, GPX, séances, contrôle | Entraînement / dénivelé / veille | 47 | Écarté | H manipule calendrier et éditeur ; compte et upload non testés | 2–6 h par variante |
| F29 | Train France : SNCF API + Trainline | Voyage | 46 | Écarté | API pour horaires, H pour réservation ; parcours non testé | 4 h |
| F30 | Hébergement officiel contre Booking | Voyage | 44,5 | Écarté | Deux recherches H ; Booking interdit, Revolugo non testé | 4 h |
| F31 | Suivi live pour les proches | Après-course | 33,5 | Écarté | Lecture des temps de passage ; pas de vraie course live en démo | 4 h |
| F32 | Rush, captcha, marché noir, comptes auto, paiement et sites interdits | Tous | 0 | Interdit / écarté | Aucun usage retenu | Ne pas développer |

\* Compléments éditoriaux : notes des six critères dans l'ordre de la méthode, puis pénalité : F33 = (1, 6, 4, 3, 5, 5), sans pénalité ; F34 = (5, 3, 6, 4, 4, 4), −2,5 ; F35 = (5, 3, 4, 4, 4, 3), sans pénalité ; F36 = (2, 6, 6, 4, 7, 4), −2,5. Comme les autres scores, ce sont des appréciations, pas des mesures.

## 4. Détail par axe

### 4.1. Inscription — le cœur du computer use

**Résumé** : les formulaires européens hétérogènes justifient H. Les tests génériques ne garantissent pas le parcours de la course choisie, ni sa conformité contractuelle.

- **Copilote « Inscris-moi » multi-plateforme (F01)** : profil réutilisable et runbook par site. **Vérifié — tests de l'équipe** : Njuko et Klikego atteints jusqu'au paiement sur les courses testées ([BRAINSTORM](BRAINSTORM.md#résultats-du-test-de-faisabilité-h-7-nov)). Klikego peut créer un profil avec mot de passe même en parcours invité : arrêter si cela crée un compte. **Non vérifié** : checkout de Lisbonne et généralisation à Milan. Le semi est sur le [site MCP, ID 3769](https://meia-maratona.inscricoes.maratonaportugal.com/?prova_id=3769), pas Njuko ; pas de champ t-shirt à cette étape, taille choisie au retrait, pas de certificat demandé selon la FAQ consultée.
- **Contrôle d'éligibilité/documents (F15)** : lire les exigences, signaler les champs manquants. **Vérifié — doc/pages** : [PPS personnel](https://pps.athle.fr/) et restrictions d'âge sur [Njuko](https://in.njuko.com/10km-bastille-20261771345371021). L'obligation dépend du pays et de la course. **Supposé** : extraction PDF fiable ; aucune création de PPS/certificat à la place du coureur.
- **Plan B comparateur de courses (F04)** : chercher les alternatives puis vérifier les pages. [Ahotu](https://www.ahotu.com/fr/calendrier/course/semi-marathon/france) a été consulté en navigateur ; [RunSignup](https://runsignup.com/API/races/GET) et [Active](https://developer.active.com/docs) documentent la découverte. **Non vérifié** : checkouts Ahotu/Active et comportement de H sur leurs protections. Version parallèle complète en P2, pas dans les trois slots déjà occupés.
- **Guetteur d'ouverture/loterie (F23)** : surveiller un changement officiel et notifier, pas acheter à la seconde. Sources : [Paris](https://www.asicsmarathondeparis.com/fr), [article u-trail](https://www2.u-trail.com/sur-quel-site-sinscrire-au-marathon-de-paris-2027/), source secondaire sur la loterie. **Supposé** : détection robuste ; aucune ouverture réelle prévue pendant la démo. Toute notification simulée doit être nommée.
- **Chasseur de dossard officiel (F04/F34)** : [bourse Klikego](https://www.klikego.com/services), [transfert RunSignup](https://help.runsignup.com/support/solutions/articles/17000062921-transfer-to-another-runner), [liste d'attente RunSignup](https://help.runsignup.com/support/solutions/articles/17000062844-enabling-a-waiting-list), [modules Njuko](https://njuko.com/modules.html). **Vérifié — doc** : ces mécanismes existent selon l'organisateur ; pas de parcours complet testé avec compte/dossard. [Lisbonne interdit le transfert](https://maratonaclubedeportugal.com/faqs-meia-maratona-lisboa/).
- **Inscription groupe/club (F19)** : blocs participants, panier commun ; options vues sur MCP et [modules Njuko](https://njuko.com/modules.html). **Supposé** : fiabilité multi-profils ; consentement des tiers et risque de mélange des champs. Ne pas créer de comptes ni soumettre.

**Arbitrage Lisbonne/Milan — vérifié en lecture seule le 7 novembre** :

| Épreuve | Observation | Ce que cela ne prouve pas |
| --- | --- | --- |
| [Semi Lisbonne, 3769](https://meia-maratona.inscricoes.maratonaportugal.com/?prova_id=3769) | Complet, page « Lista de Espera », 7 mars 2027 | Pas d'inscription possible au semi démontrée |
| [Hyundai 7K, 3768](https://meia-maratona.inscricoes.maratonaportugal.com/?prova_id=3768) | Formulaire actif, 15 € ; [fiche officielle](https://maratonaclubedeportugal.com/corrida-marco/hyundai-7k) « inscrições abertas », 6 mars à 9h30, Estádio Nacional/Jamor | Le bandeau dit aussi « Luso 7K complet » ; Easypay et acceptation serveur non testés |
| [Vodafone 10K, 3767](https://meia-maratona.inscricoes.maratonaportugal.com/?prova_id=3767) | Formulaire actif, 37 €, dimanche 7 mars ; bandeau « complet » | Disponibilité non confirmée ; bouton actif ≠ place garantie |
| [New Generation, 3766](https://meia-maratona.inscricoes.maratonaportugal.com/?prova_id=3766) | 1,5 km, gratuit, 6–16 ans | Pas une alternative pour notre coureur adulte |
| [Marathon de Milan sur Njuko](https://in.njuko.com/wizz-air-milano-marathon-20271776152378557?currentPage=select-competition) | 4 avril 2027, 8h00, deux catégories à 114 € avec « S'inscrire » ; [site officiel](https://www.milanomarathon.it/en/marathon/register/) | Ni checkout H de cette course ni logistique de voyage validés |

**Idées écartées** : rush et marché noir, contournement de captcha, PPS/certificat généré, comptes créés automatiquement, paiement réel. Le bouton MCP « Inscrever agora! » envoie un formulaire ASP.NET et peut créer une inscription avant paiement : ne pas cliquer pour lever l'incertitude. Barcelone et Séville ont été trouvées complètes ; Endu/Rome affiche un contrôle humain depuis la VM.

### 4.2. Voyage — la logistique course plutôt qu'un comparateur générique

**Résumé** : c'est l'accès réel au départ et au dossard qui doit déterminer l'hôtel et les dates, pas un simple rayon autour de la ligne de départ. Les premières recommandations Booking/TAP sont **dépassées par la critique juridique**.

- **Hôtel calé sur départ/Expo/arrivée (F02)** : **vérifié — test** : recherche Booking par coordonnées et filtres de distance, annulation et réception. Cette recette technique n'autorise pas son automatisation. **Repli technique** : [Accor](https://all.accor.com/), page voyageur atteinte en 2,8 min et conservée 20 min, un seul essai ; voir section 5. **Supposé** : même tri et même couverture sur un site autorisé.
- **Départ tardif et consigne (F16)** : champ « demandes spéciales » observé sur [une fiche Booking](https://www.booking.com/hotel/gb/grand-airport-ensuites.en-gb.html). Idée à transposer, pas à exécuter sur Booking. Une demande n'est jamais une garantie de l'hôtel ; reciblage non testé.
- **Fenêtre de voyage (F02)** : calculer arrivée avant retrait et retour après course + marge. **Vérifié — sources du semi** : [organisateur](https://maratonaclubedeportugal.com/corrida-marco/edp-meia-maratona-de-lisboa/), retrait du 4 au 6 mars, 10h–20h, pas le jour J ; accès Fertagus/Pragal et absence de consigne rapportés. Le [règlement 2027](https://maratonaclubedeportugal.com/wp-content/uploads/REGULAMENTO_EDP_MEIA_MARATONA_DE_LISBOA_2027_EN.docx.pdf) donne 9h30 pour le départ du semi, contre 9h20 sur une page : citer l'édition/source et confirmer. **Non vérifié** : retrait et accès propres au 7K ; aucune déduction « vendredi 20h » acquise.
- **Routage selon blocage et relais humain (F10)** : depuis Chrome VM, SNCF Connect/DataDome, easyJet/Akamai, OUIGO/Turnstile et Hotels.com/429 bloquent ; Booking, TAP, Trainline, Vueling, Transavia et Expedia chargent. **Cela ne décrit pas le navigateur cloud H**, ni leurs CGU. [Pause et steering H](https://hub.hcompany.ai/agents-api/observe-and-steer.md) sont documentés ; reprise souris cloud non démontrée. Aucun proxy ne doit servir à contourner un contrôle.
- **Train France API SNCF + Trainline (F29)** : [SNCF](https://numerique.sncf.com/faq/api/) documente une fenêtre d'horaires de −1 à +23 jours dans l'exploration, incompatible avec mars/avril 2027 en novembre. Trainline charge mais contient DataDome ; parcours et CGU non validés. Écarté pour cette démo.
- **Hébergement officiel contre Booking (F30)** : partenaires identifiés, dont [Revolugo à Anvers](https://antwerpmarathon.com/en/accommodation/) et [Dubaï](https://www.dubaimarathon.org/travel/hotel-accommodation/). **Non vérifié** : réservation ; les liens dépendent de l'édition. Comparaison à recadrer sans Booking, pas deux agents hôtel dans le MVP.
- **Plan B blessure / annulation gratuite (F08)** : filtre Booking observé, date limite exacte non observée dans le premier test ; lecture/transposition à Accor non validée. Afficher le tarif, l'échéance et les conditions exactes, pas « remboursable » par défaut.

**Idées écartées** : Booking et Airbnb (CGU), TAP (CGU §8), compagnies exigeant compte/vérification non disponible, réservation automatique réelle. [Booking Demand](https://developers.booking.com/demand/docs/getting-started/prerequisites) et [Expedia Rapid](https://developers.expediagroup.com/rapid/setup?locale=en_US) demandent des accès partenaires ; un accès futur n'est pas acquis. Duffel enlèverait le computer use du vol ; les disponibilités d'API anciennes doivent être recontrôlées, pas promises.

### 4.3. Parcours 3D — bonus visuel, pas cœur agentique

**Résumé** : le rendu maison est plus fiable que piloter une appli 3D tierce. L'originalité est l'intégration au séjour, pas le survol seul.

- **Survol accéléré maison (F12)** : MapLibre + relief [Mapterhorn](https://tiles.mapterhorn.com/tilejson.json) + imagerie. **Vérifié — prototype rapporté** : rendu du tracé du semi de Lisbonne et du pont ; **non vérifié** : fluidité dans l'app finale et tracé du 7K/10K. [Exemple de caméra](https://docs.mapbox.com/mapbox-gl-js/example/free-camera-path/) comme référence, pas comme dépendance imposée. Respecter licences et attributions des fonds, même sans clé.
- **Chasseur de tracé officiel (F17)** : H cherche le lien organisateur → My Maps/GPX ; l'export et la normalisation sont en code. [FAQ officielle](https://maratonaclubedeportugal.com/en/faqs-edp-lisbon-half-marathon/) et [export OpenRunner](https://support.openrunner.com/hc/fr-fr/articles/19006800048284-Exporter-le-fichier-GPX-d-un-parcours). **Vérifié** : export de carte sans compte sur le cas du semi ; **non vérifié** : récupération autonome H et correspondance d'édition pour toute autre carte.
- **Google Earth web + KML/gx:Tour (F27)** : import KML observé sans connexion ; animation du tour non validée, interface changeante. [Import Earth](https://developers.google.com/maps/documentation/earth/import-kml), [KML touring](https://developers.google.com/kml/documentation/touring). Écarté au profit du rendu maison.
- **Profil et points clés (F12)** : [OpenTopoData](https://www.opentopodata.org/api/) pour les altitudes ; les ponts imposent des corrections, détaillées dans l'axe suivant.
- **Survol commenté et corrections vocales (F12)** : « montre le km 7 », pause, ravitaillement suivant. Faisable en code + Gladia, **supposé**, pas une action H supplémentaire.
- **Export MP4/WebM du survol (F33)** : encoder le rendu pour le replay ou le partage. **Non testé** dans RunAI ; sans rôle computer use. [Animation de parcours](https://www.mapbox.com/blog/building-cinematic-route-animations-with-mapboxgl) comme référence.

**Idées écartées** : Relive/Strava Flyover mobiles ou payants, FATMAP fermé, komoot nécessitant une connexion malgré sa FAQ. Ne pas présenter un vieux tracé de marathon comme celui du semi 2027. Concurrents existants : [13milers](https://13milers.com/races/lisbon-half-marathon), [BeforeTheRun](https://www.beforerace.day/races/lisbon-half-marathon/).

### 4.4. Dénivelé et fiche course — calculer, ne pas faire cliquer pour rien

**Résumé** : H est utile pour trouver l'information enfouie ; profil, météo et allure relèvent surtout de code déterministe. La précision doit être affichée honnêtement.

- **Trouver le tracé + exporter GPX/KML (F17)** : **vérifié — test** : [KML lié par l'organisateur](https://www.google.com/maps/d/kml?mid=1OJJ0KpT0ZaRGcYOHJbIfJ3DJd0ONXWY&forcekml=1), 225 points, environ 21,2 km et 23 repères. Un autre axe obtient 21,10 km sur une autre carte : conserver provenance et édition, ne pas mélanger les tracés. La collecte par H n'a pas été testée sur ce cas précis.
- **Profil altimétrique et côtes clés (F12)** : [Open-Meteo altitude](https://open-meteo.com/en/docs/elevation-api) et [OpenTopoData](https://www.opentopodata.org/) répondent sans clé dans les essais. **Vérifié — calcul exploratoire** : D+ de 162 à 380 m selon MNT/lissage ; les deux donnent 0 m sur le pont au départ. **Non codé** : correction fiable ponts/tunnels. Afficher une fourchette, pas un D+ « officiel ».
- **Météo jour J ou climatologie (F22)** : [forecast](https://open-meteo.com/en/docs), [ensembles](https://open-meteo.com/en/docs/ensemble-api), [historique](https://open-meteo.com/en/docs/historical-weather-api). **Vérifié — doc/tests** : prévision jusqu'à 16 jours, ensemble GFS jusqu'à 35 jours selon doc ; au-delà, climatologie. Pour début mars à Lisbonne, calcul rapporté sur 2016–2025 : médiane 13,4 °C, vent médian 14 km/h. Ce n'est **pas une prévision du 7 mars 2027**.
- **Fiche pratique : ravitos, barrières, accès, meneurs (F02)** : [règlement du semi](https://maratonaclubedeportugal.com/wp-content/uploads/REGULAMENTO_EDP_MEIA-_MARATONA_DE-LISBOA_2027_PT-.docx.pdf) : ravitaillements tous les 5 km, limite 3 h, meneurs de moins de 4:00 à moins de 5:30 min/km. Les positions projetées tous les 5 km sont estimées, pas géolocalisées officiellement. H seulement pour onglets/FAQ interactifs si l'extraction directe échoue.
- **Allure par km ajustée à la pente et au vent (F22)** : [Minetti](https://journals.physiology.org/doi/full/10.1152/japplphysiol.01177.2001) et [GAP Strava](https://medium.com/strava-engineering/an-improved-gap-model-8b07ae8886c3) comme pistes ; pages non relues à cause de 403. **Supposé, non codé** : coefficients, vent de face par km, bracelet d'allure. Aucune promesse de performance ni recommandation médicale.
- **Mettre parcours/allure sur la montre (F28)** : import via [Garmin Connect](https://connect.garmin.com/), compte existant et upload requis. **Non testé**, écarté en démo.
- **Survol 3D vocal (F12)** : même brique que l'axe précédent ; [terrain MapLibre](https://maplibre.org/maplibre-gl-js/docs/examples/3d-terrain/). Les API disponibles ne prouvent pas l'animation finale.

**Idées écartées** : chiffre de D+ unique sans correction, météo précise à plusieurs mois, modèle GAP présenté comme validé sans relecture ni implémentation, agent H utilisé pour remplacer un simple calcul/API.

### 4.5. Entraînement — vrai potentiel, trop de comptes pour cette démo

**Résumé** : les écritures dans les logiciels du coureur sont intéressantes, mais aucune des six variantes n'a été validée par H de bout en bout. Toutes sont regroupées en **F28, écarté pour le hackathon**.

- **Ajout de course + Garmin Coach** : [partenariat Ahotu/Garmin](https://www.ahotu.com/partner/garmin), [fonctions jour de course Garmin](https://www.garmin.com/en-US/blog/fitness/free-race-day-features-on-your-garmin-running-smartwatch/) documentés ; compte, SSO/2FA et montre compatible à vérifier.
- **Polar Running Program depuis la date de course** : [guide Polar](https://support.polar.com/us-en/support/get_started_with_the_polar_running_program), [FAQ](https://support.polar.com/en/support/polar_running_program_faqs). **Vérifié — doc** : compte gratuit, programme web, minimum 14 semaines pour semi/marathon ; pas de modification libre après création. Parcours H non testé.
- **Import GPX dans Garmin + lien à la course/PacePro** : [guide d'import](https://fakepace.run/blog/how-to-import-gpx-to-garmin-connect), [écriture de fichier H](https://hub.hcompany.ai/agents-api/sessions/write-file). **Supposé** : manipulation du sélecteur de fichiers et compatibilité de l'appareil.
- **Séances structurées Workout Builder + calendrier** : [guide utilisateur](https://garmin.vaw.be/en/community/day-40-build-your-own-interval-training), [API Training partenaire](https://developer.garmin.com/gc-developer-program/enterprise/training-api/). Éditeur documenté, cadence de 5–10 min par séance seulement estimée ; 50 séances ne tiennent pas dans la démo.
- **Correction vocale du calendrier** : déplacer une séance via H ; [steering](https://hub.hcompany.ai/agents-api/sessions/send-messages). Glisser-déposer et fiabilité non testés. « J'ai mal au mollet » ne doit pas devenir un diagnostic ni être envoyé au cloud sans cadre adapté.
- **Vérificateur du calendrier** : relire date de course, séances et doublons. **Supposé** : 2–4 min par vérification ; aucun gain mesuré, un slot de plus.

**Idées écartées** : plan LLM générique sans computer use ; Strava automatisé malgré ses [CGU](https://www.strava.com/legal/terms) ; MCP Garmin non officiels et cookies personnels ; Runna/Nike mobiles ; TrainingPeaks payant ou fermé ; contourner COROS alors qu'une voie officielle d'écriture existe selon l'exploration. Une [API intervals.icu](https://intervals.icu/) peut être un repli produit, pas une démonstration de H.

### 4.6. Après-course — prolonger l'histoire sans acheter ni publier

**Résumé** : résultats, diplômes et photos sont dispersés sur des sites différents ; l'utilité est réelle mais hors du cœur des trois minutes.

- **Débrief chrono/diplôme/photos (F20)** : **vérifié — lecture seule**, Lisbonne 2024 : [résultats organisateur](https://www.running-portugal.com/lisbon/lisbonhalf/en/results.html) → [Sporthive](https://sporthive.com/events/s/7142907578304137472) → [Marathon Photos Live](https://marathonphotos.live/Event/Sports%2FCPUK%2F2024%2FLisbon%20Half%20Marathon/5327). La consultation rapportée trouvait un chrono, un certificat, 51 photos et un pack à 22,95 €. Exemple historique, pas tarif ni disponibilité 2027 ; le diplôme n'est pas une qualification officielle.
- **Chasseur multi-photographes (F20)** : [Sportograf](https://helpdesk.sportograf.com/en/support/solutions/articles/77000354629-how-it-works), [FinisherPix](https://help.finisherpix.com/hc/en-us/articles/8425751891095-Find-Your-Photo-Gallery), MarathonFoto : mécanismes documentés ; fédération automatique H non testée. Rester sur la recherche par course/dossard, sans selfie ni collecte en masse.
- **Blessure : transfert, revente, assurance (F34)** : [Klikego](https://www.klikego.com/services/bourse-aux-dossards.jsp), [modules Njuko](https://njuko.com/modules.html). **Vérifié — doc** : offres officielles selon événement ; non testé avec vrai dossard. Lire conditions et préparer une demande, pas céder ni déclarer un sinistre. Lisbonne interdit le transfert.
- **Liste d'attente de la bourse (F04)** : même mécanisme officiel que l'axe inscription, pas une garantie d'obtenir un dossard ; compte et soumission non testés.
- **Suivi live pour les proches (F31)** : lecture des temps de passage, sans GPS mobile. **Supposé** : agrégation robuste ; aucune course live prévue au moment de la démo. Replay historique seulement, annoncé.
- **Réclamation chrono, passeport SuperHalfs, palmarès (F35)** : préparer les liens et formulaires officiels à partir des [résultats](https://www.running-portugal.com/lisbon/lisbonhalf/en/results.html). **Non testé** : démarches complètes, éligibilité et validation ; aucune soumission ni publication.

**Idées écartées** : achat de photos, scraping/téléchargement massif, selfie biométrique, revente hors canal officiel, déclaration d'assurance médicale automatisée, publication sociale/Strava. Luck-it est signalé fermé dans l'exploration, pas une dépendance à retenir.

### 4.7. Gladia — une télécommande, pas seulement du speech-to-text

**Résumé** : toutes les capacités suivantes sont **documentées**, mais n'ont pas été testées avec les voix de l'équipe dans la salle. Gladia ne fournit pas ici de TTS ; la voix sortante est une autre brique.

- **Barge-in vocal (F05)** : [événement `speech_start`](https://docs.gladia.io/api-reference/v2/live/websocket) avec `receive_speech_events`, puis [pause H](https://hub.hcompany.ai/agents-api/sessions/pause). **Vérifié — doc** : 202 asynchrone, pas arrêt instantané ; `send_message` relance une session en pause. **Non mesuré** : délai de l'arrêt réel. Appui pour parler et bouton pause de secours ; choisir explicitement entre pause dès le début de parole ou pause après reconnaissance du mot d'arrêt.
- **Recherche anticipée (F13)** : [partiels Gladia](https://docs.gladia.io/chapters/live-stt/features/partial-transcripts) → Linkup réversible ; annuler les recherches obsolètes. Aucun lancement de formulaire H sur un partiel ; attendre le final et l'accord utilisateur.
- **Dictée exacte (F36)** : e-mail/téléphone et autres champs autorisés, avec relecture. [Vocabulaire personnalisé](https://docs.gladia.io/chapters/audio-intelligence/custom-vocabulary), variantes phonétiques et confiance par mot ; NER live annoncée alpha dans l'exploration. Fiabilité non mesurée. PPS/licence/date de naissance ne sont pas collectés pour le MVP cloud minimal.
- **Narration et récap lus (F14)** : Web Speech API, éventuellement ElevenLabs hors socle. Ne pas attribuer cette synthèse vocale à Gladia ; éviter que la voix de l'app déclenche ses propres commandes.
- **Profil salle bruyante (F05)** : micro-casque, appui pour parler, demi-duplex, réglages d'enhancement et seuil ; [paramètres recommandés](https://docs.gladia.io/chapters/live-stt/recommended-parameters). Banc d'enregistrements sur place à faire, pas de réglage « magique » acquis.
- **Code-switching FR/EN/PT et traduction (F05)** : [doc](https://docs.gladia.io/chapters/language/code-switching). Détection par énoncé avec langue des mots ; liste courte de langues. Partiels moins précis en multilingue ; le vocabulaire local aide mais ne prouve pas la reconnaissance de « Praça do Comércio » en salle.
- **Journal vocal de mission (F24)** : relier phrase, horodatage et commande H, puis résumé. Simple piste de traçabilité ; durée du post-traitement et politique de conservation non définies.

**Idées écartées** : ajouter Pipecat/LiveKit/Vapi sans besoin, diarisation live non documentée, audio-to-LLM ou Solaria-3 présentés comme live, endpointing trop court, analyse d'émotion gadget, GladiaFlow comme bus d'événements du produit. Une commande vocale « oui » ne remplace jamais une déclaration personnelle de santé.

### 4.8. Devin, Linkup et H — la preuve compte plus que la promesse

**Résumé** : orchestration explicite, recherche sourcée et sorties vérifiables d'abord ; auto-réparation ensuite, sans monopoliser les trois slots.

- **Boucle d'auto-réparation (F11)** : trace H → PR runbook → Skill H versionné → re-test. [Skills H](https://hub.hcompany.ai/agents-api/skills/overview.md), [API Devin](https://docs.devin.ai/api-reference/v3/overview), [guide service user](https://docs.devin.ai/api-reference/getting-started/teams-quickstart). **Vérifié — recherche** : un échec H partiel existe ; pas de clé Devin parmi les secrets recensés alors. **Non vérifié** : inclusion API dans l'offre, coût, boucle complète. Un lancement manuel doit être nommé manuel ; un CI vert ne prouve pas une inscription réussie.
- **E2E en langage naturel + CI/Review (F25)** : [exemples QA H](https://github.com/hcompai/agents-api-demos/blob/main/examples/qa/shared.py). La spécification doit dire quelle page/quel état vaut succès ; URL accessible au cloud nécessaire. Concurrence avec les répétitions : couper ces runs pendant la démo.
- **Linkup hybride (F07)** : pré-recherche de la bonne URL, outils search/fetch disponibles à H en repli. [Search](https://docs.linkup.so/pages/documentation/endpoints/search/overview.md), [fetch](https://docs.linkup.so/pages/documentation/endpoints/fetch/overview.md), [outils H](https://hub.hcompany.ai/agents-api/custom-tools.md). Les temps de recherche annoncés sont ponctuels ; extraction générique des règlements non validée. Un fetch n'est pas une échappatoire aux CGU d'un site.
- **Réponses typées, vérification croisée et journal (F06)** : [sorties structurées H](https://hub.hcompany.ai/agents-api/structured-output.md). Réponse = bonne course, édition, distance, prix/devise, champs manquants, URL et état d'arrêt. Vérifier ce qui est visible ; une réponse JSON valide n'est pas une preuve de vérité. Inconnues à `null`, divergences affichées.
- **Orchestration robuste (F06)** : [limites H](https://hub.hcompany.ai/agents-api/plans-and-limits.md), [quota](https://hub.hcompany.ai/agents-api/sessions/quota.md). **Vérifié — API** : 3 sessions simultanées ; pause/attente gardent un slot, les sessions supplémentaires ordinaires sont mises en file. Budgets et nettoyage des sessions à contrôler ; aucune relance concurrente « gratuite ».
- **Portail par outil bloquant (F03)** : [résultats d'outil](https://hub.hcompany.ai/agents-api/sessions/tool-results.md). Attente testée environ 20 min ; un message reçu pendant `awaiting_tool_results` n'est consommé qu'après la réponse à l'outil. Intégrer la correction à cette réponse, puis reprendre ; ne pas confondre avec une pause de session.
- **Banc de fiabilité planifié (F09)** : [schedules](https://hub.hcompany.ai/agents-api/schedules/overview.md). Mesurer N, réussites, causes, médiane, durée et tokens sur le **même critère d'arrêt sûr**. Pas de taux x/5 existant dans les données. Quinze runs de trois minutes demanderaient 15–20 min avec trois slots libres ; avec des parcours complets de 10–15 min, plutôt 50–75 min au minimum, hors incidents.

**Idées écartées** : manager H natif dans le chemin critique (slot du manager en plus), Linkup research/batch/MCP sans bénéfice démontré, navigateur H texte pour remplir un formulaire (lecture seule), attendre que Devin code pendant les trois minutes, comptes/vaults créés sans accord. Les changements de Skills, PR et API décrits ici sont une piste produit, pas des opérations exécutées pour ce document.

### 4.9. Veille SOTA — éviter de confondre intégration et nouveauté

**Résumé** : les recherches rapportent à San Francisco PLVA (confidentialité), Handyman (guidage) et Reel-Learn (mesure/correction). En déduire que confiance et preuves comptent est une **interprétation**, pas une règle du jury parisien. Certains projets du Showcase restent inaccessibles (401).

- **Tableau de fiabilité (F09)** : inspiré de Reel-Learn et des retours de jury ; [annonce H](https://www.linkedin.com/posts/h-company-ai_last-week-%F0%9D%9F%AD%F0%9D%9F%AE%F0%9D%9F%AC-%F0%9D%97%AF%F0%9D%98%82%F0%9D%97%B6%F0%9D%97%B9%F0%9D%97%B1%F0%9D%97%B2%F0%9D%97%BF%F0%9D%98%80-spent-activity-7486057611960864768-JLy_). Nos propres résultats restent à mesurer.
- **Coordinateur séjour à sous-agents natifs (F18)** : [multi-agent H](https://hub.hcompany.ai/agents-api/multi-agent.md). Documenté mais non testé ici ; enfants sans file d'attente en cas de quota plein, manager consommateur de slot. Préférer le code d'orchestration explicite pour cette démo.
- **Récap « montre-moi », mode guidé (F26)** : [Handyman](https://github.com/gurul/handyman). L'idée est de montrer le bon bouton et laisser agir l'humain ; intégration et prise de main cloud non vérifiées. Vérifier la licence avant toute reprise de code.
- **Coffre à jetons (F21)** : [PLVA/privacy layer](https://github.com/dael-amz/browser-agent-privacy-layer). Masquer une valeur dans le prompt peut réduire l'exposition au modèle, **pas au fournisseur du navigateur** si elle est résolue dans la page. Ce n'est pas une solution RGPD suffisante.
- **Tracé officiel + dénivelé + survol au récap (F12/F17)** : [BeforeTheRun](https://www.beforerace.day/races/lisbon-half-marathon/), [13milers](https://13milers.com/races/lisbon-half-marathon), [RunConcierge](https://devpost.com/software/runconcierge-powered-by-neurun) montrent que le rendu existe déjà. La collecte utile par H et l'intégration sont à démontrer.
- **Course et séances poussées dans Garmin (F28)** : [Training API entreprise](https://developer.garmin.com/gc-developer-program/enterprise/training-api/) ; potentiel sans API grand public, mais parcours H non testé et comptes requis. Vision, pas extension de dernière minute.

**Concurrence et idées écartées** : [RunSignup décrit déjà l'inscription par Muse](https://info.runsignup.com/2026/09/27/signing-up-for-races-with-metas-muse-ai-agent/). Ne pas revendiquer « premier agent qui inscrit à une course ». Le séjour générique, le coaching LLM, le survol 3D et les alertes ont des concurrents. Le différenciateur proposé reste **plateformes européennes + contraintes de course visibles + contrôle vocal + fiabilité prouvée** ; sa supériorité n'est pas mesurée. Hors périmètre : paiements x402/USDC, fine-tuning desktop/Roblox, arènes de recherche, forfait « dossard garanti » sans quota officiel. Snowglobe, Glassbox et AI Teaching Assistant n'ont pas pu être analysés : aucune conclusion sur eux.

## 5. Critiques de l'avocat du diable et réponses

Les deux tours finissent avec **`accepted: false`**. Cela signifie que la proposition n'a pas obtenu la validation finale de la critique, pas que les objections sont résolues. Les approfondissements ont corrigé des faits, mais aucun ne valide le produit complet.

| Critique | Réponse étayée / nuance | Décision et reste à faire |
| --- | --- | --- |
| **Le scénario mélange deux villes et de mauvaises infos Lisbonne** | Confirmé : MCP ≠ Njuko ; 3765 est une marche, 3769 le semi complet. Pas de t-shirt/certificat à promettre. Le 7K et le 10K ont un formulaire actif malgré le bandeau | Une seule ville, une seule épreuve et les bonnes dates. Confirmation organisateur ou repli Milan ; Easypay non testé, ne pas soumettre pour vérifier |
| **Booking puis TAP rendent le parcours contractuellement fragile** | Confirmé : [Booking](https://www.booking.com/content/terms.html) vise explicitement les assistants automatisés/IA ; [TAP anglais §8](https://www.flytap.com/en-pt/legal-info/terms-and-conditions) et [portugais §8](https://www.flytap.com/pt-pt/info-legal/termos-e-condicoes) interdisent robots/scripts ; priorité au portugais en §14 | Exclure ces parcours sans autorisation spécifique. [Accor](https://all.accor.com/a/en/information/legal-conditions.html) : pas de clause équivalente trouvée ≠ permission. Auditer les conditions applicables, sinon parcours humain |
| **« L'humain consent » repose sur un takeover inexistant** | [Agent View](https://hub.hcompany.ai/agents-api/observe-and-steer.md) et [partage](https://hub.hcompany.ai/agents-api/sessions/share.md) documentent vue/replay et messages, pas le clic humain. Cela ne prouve pas l'impossibilité. [Chrome local](https://hub.hcompany.ai/agents-api/your-browser.md) est documenté, pas validé de bout en bout | Aucun takeover promis. Lien officiel et ressaisie dans une session personnelle sans agent ; mode local seulement après essai et arrêt confirmé de H |
| **Les données de santé transitent quand même chez H** | Confirmé pour une déclaration révélant la santé. Naissance/contact ne sont pas automatiquement des données de santé. [RGPD](https://eur-lex.europa.eu/legal-content/FR/TXT/?uri=CELEX%3A32016R0679) : base art. 6 et exception art. 9 si nécessaire ; consentement explicite pas unique exception ; [AIPD](https://www.cnil.fr/fr/realiser-une-analyse-dimpact-si-necessaire) selon risque élevé | Démo sans vraies données. Production : santé/PPS/certificat hors cloud ; MVP sans naissance/contact tiers. Contrats H, conservation et transferts non audités. Ni jetons ni navigateur local encore connecté ne suppriment l'exposition |
| **Fiabilité non mesurée, trois slots sans marge** | Confirmé : un essai par site n'est pas un taux. [Quota H](https://hub.hcompany.ai/agents-api/plans-and-limits.md) = 3, attente et pause incluses. Manager natif défavorable | Deux missions pour garder une marge ; pas de banc/CI/re-test pendant le passage. Mesurer les runs jusqu'au même arrêt sûr, sans faux « 4/5 » |
| **Pré-lancement trop long, paniers expirés, correction impossible au bon moment** | Nuancé par tests réels : [Accor](https://platform.hcompany.ai/agents/sessions/ea01ea80-ea2a-4efb-8885-8c123acc509a), 2,8 min jusqu'aux coordonnées ; [TAP, observation historique uniquement](https://platform.hcompany.ai/agents/sessions/d659ae18-6faa-4681-8e90-60bcee1d1db2), 2,4 min jusqu'aux passagers. Après attente de 20 min et refresh : même page/prix, **un essai chacun**, pas page de paiement | Pas de garantie sur autre site/jour. Répéter sur la cible retenue. En attente d'outil, libérer l'outil avec la correction : reprise observée 4–11 s plus tard ; pas lecture immédiate d'un message |
| **La démo « live » est un replay déguisé** | Critique fondée si le montage n'est pas annoncé. Une attente H d'environ 20 min a été observée, même sans client connecté ; cela ne valide pas trois parcours simultanés | Montrer du live réel, distinguer pré-lancement, replay et accélération. Arrêt de sécurité et bouton pause visibles ; repli clairement nommé |
| **Top 5 trop gros, Linkup marginal, originalité surestimée** | Surcharge confirmée ; Muse/RunSignup et d'autres couvrent déjà inscription/coaching/voyage. La logistique course est un différenciateur proposé, pas une nouveauté absolue | Recentrer sur F01–F07, réduire le nombre de sites, afficher « pourquoi ce choix ». Retirer l'entraînement et le survol s'ils menacent la fiabilité |
| **Gladia trop banal, Devin mis en scène** | Barge-in et code-switching documentés, pas testés en salle. Pas de clé/API Devin validée ni boucle complète ; l'échec ancien cité ne prouve pas une réparation | Deux latences vocales réellement mesurées. Pour Devin : trace du jour, session, PR, révision du Skill et re-test sur le même critère sûr. Sans preuve, annoncer « non livré » ; un CI vert seul ne suffit pas |

**Point technique Chrome local** : le SDK inspecté avertit qu'un simple override `host=user_device` ne démarre pas le bridge. Il faut servir le navigateur avec `holo local browser`, utiliser le `session_id` ou une spec locale, et disposer de l'extra navigateur (`hai-drivers[web]`). La doc limite un processus à un navigateur piloté ; une nouvelle session remplace l'ancienne. Sources : [SDK sessions](https://github.com/hcompai/hai-agents-python/blob/main/src/hai_agents_local/sessions.py#L90-L96), [SDK browser](https://github.com/hcompai/hai-agents-python/blob/main/src/hai_agents_local/browser.py#L62-L71). **Non testé sur la machine de démo**. Même après arrêt de H, ne pas réutiliser pour de vraies données sensibles une page cloud synchronisée ; la ressaisie dans une nouvelle session personnelle reste le repli minimal.

## 6. Questions ouvertes

### Bloquantes avant une promesse de démo

1. **Quelle course exacte et réellement disponible ?** Faire confirmer le 7K/10K par MCP, ou retenir Milan avec un arrêt sûr répété. Le bandeau de Lisbonne reste contradictoire ; pas de soumission pour trancher.
2. **Quelles autorisations de sites ?** Booking, TAP, Airbnb et Strava automatisés exclus. Accor sans clause explicite ne suffit pas. Compagnie/voie transport autorisée à trouver ; sinon lien manuel, sans agent sur les pages interdites.
3. **Quelles contraintes propres à l'épreuve ?** Retrait, accès, horaires et tracé du 7K/10K ou Milan à vérifier. Ne pas hériter des infos Fertagus ou du retrait du semi.
4. **Quel relais humain démontré ?** Agent View permet-il réellement le clic ? Chrome local fonctionne-t-il avec `h/web-surfer-pro`, et l'arrêt de l'agent est-il confirmé ? À défaut, ressaisie dans le navigateur personnel sans H/micro/capture, continuité non garantie.
5. **Quelle fiabilité ?** Répéter le parcours exact, mesurer N, erreurs, durée et tokens. Tester trois sessions seulement après validation des briques ; le test de tenue de 20 min ne porte que sur deux pages de coordonnées, une fois chacune.
6. **Quelle latence vocale réelle ?** Mesurer détection → pause demandée puis demande → `paused`, en salle bruyante. Tester code-switching, vocabulaire local et bouton de secours sans confondre voix détectée et arrêt effectif.

### Hors chemin critique / avant production

7. **API Devin et preuve de réparation** : offre compatible, service user/PAT, coût ACU et budget ? Sans clé, lancement manuel explicite ou feature retirée ; aucun taux ni PR fictifs.
8. **Budget H** : solde actuel, tokens par run complet et répétitions disponibles ? Les ordres de grandeur partiels (environ 0,5 M de tokens d'entrée par run dans un approfondissement) ne sont pas un coût universel ni un solde garanti.
9. **Prix et expiration** : que se passe-t-il après saisie du voyageur, près du paiement et un autre jour ? Conditions d'annulation et disponibilité à relire au moment du récap, sans réservation réelle.
10. **Protection des données** : contrats/sous-traitants H, bases légales, consentements nécessaires, conservation des captures/audio, transferts, éventuelle AIPD et effacement à définir. Données fictives ≠ conformité de production.
11. **Tracé et cartes** : quel fichier officiel pour l'épreuve/édition choisie, quelles licences et attributions, quelle correction des ponts ? Sans cela, pas de D+ fiable ni de survol présenté comme officiel.
12. **Différenciation prouvée** : comparer sur des parcours précis avec Muse/RunSignup et les assistants existants. Mesurer l'effet des contraintes course, pas seulement revendiquer le multi-agent ou le nombre de partenaires.
