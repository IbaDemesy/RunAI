# Frontend RunAI — direction produit et critères de finition

Partie du [plan de développement multi-agents](PLAN_DEVELOPPEMENT.md). Proposition du 7 novembre 2026 pour la V1 et le voyage complet ; **ce document ne valide pas le rendu actuel**.

## 1. Verdict et responsabilité

Le plan couvre les fonctions frontend, mais une équipe et des skills ne suffisent pas à garantir une belle application. La sortie attendue est **une expérience cohérente et vérifiée**, pas une juxtaposition de cartes techniques et une page 3D séparée.

- **D1** est le propriétaire de la direction visuelle, des écrans et du shell.
- **C1/C2/C3** livrent carte, lecteur de voyage et repli accessible derrière une API stable.
- **D2** fournit l’entrée vocale et les commandes, sans modifier le shell en concurrence.
- **D3** fait une revue UX indépendante ; les corrections reviennent à D1/C3.
- **E3** câble les données et routes après transfert explicite du verrou du shell.

Réutiliser la refonte V1 déjà engagée, pas recommencer un design concurrent.

## 2. Direction visuelle proposée

**Un carnet de voyage sportif haut de gamme, avec la carte du séjour comme élément signature.** Le produit s’adresse à un coureur qui prépare une expérience, pas à un développeur qui supervise des outils.

- Une surface claire et calme, texte très lisible, accent sportif unique ; pas de gradients décoratifs ni d’accumulation de panneaux flashy.
- Titres expressifs et texte fonctionnel sobre ; deux familles typographiques maximum, polices système en repli.
- Hiérarchie nette : prochaine action humaine, état du séjour, budget, détails. L’adresse ou les logs techniques ne deviennent jamais les éléments dominants.
- Grille d’espacement, couleurs sémantiques, échelle typographique, rayons et styles de boutons définis dans des tokens CSS partagés ; pas de CSS indépendant inventé par chaque agent.
- Photos seulement si utiles et utilisables légalement. La carte et le parcours suffisent à l’identité ; pas d’imagerie fictive d’hôtel présentée comme réelle.
- Animations réservées à la progression et aux changements de chapitre, interrompables et compatibles avec la préférence de mouvement réduit.
- Langage utilisateur : « Inscription », « Hôtel », « Transport », « À vous de répondre », « Préparé ». Garder H, SSE, SDK et identifiants de sessions dans les détails techniques.

La palette et la typographie exactes sont arrêtées par D1 au premier incrément, puis partagées avant toute finition de composant. Pas de changement de framework imposé ; continuer le frontend léger de la V1.

## 3. Les six écrans et leurs actions principales

| Écran | Contenu essentiel | Action / critère |
| --- | --- | --- |
| 1. Préparer ma course | Demande texte, micro optionnel, exemple modifiable, mode démo/réel visible. | « Préparer mon séjour » ; saisie utilisable sans micro. |
| 2. Compléter ma demande | Origine consentie, dates, distance, budget, informations manquantes ; coach en option. | Questions courtes, réponses conservées, pas d’informations inventées ni de santé cochée par défaut. |
| 3. Préparatifs en cours | Étapes inscription/hôtel/transport, dernière action utile, état et durée mesurée si disponible. | Pause/annulation globales ou ciblées ; détail technique et vue H en second niveau. |
| 4. À vous de répondre | Vraie question de l’agent, contexte, conséquence, choix et champ texte. | Répondre au bon agent, refuser ou arrêter ; état d’envoi puis confirmation, sans double réponse. |
| 5. Mon séjour | Dates, budget détaillé, postes manquants, source des offres, points d’arrêt humains et timeline. | Ajuster le choix, ouvrir le site autorisé, revoir les informations ; « préparé » jamais présenté comme « réservé ». |
| 6. Explorer et emporter | Voyage complet et chapitres, profil course, récap PDF/.ics et réserves. | Naviguer à l’hôtel/au départ/au km, pause/lecture, repli 2D, exporter un instantané cohérent. |

La question humaine est un bloc prioritaire ou un panneau accessible dans le parcours, pas obligatoirement une nouvelle page. Ne pas masquer les questions en attente derrière la carte.

### Composition responsive

- **Ordinateur** : résumé et prochaine action en tête ; zone principale carte/timeline ; panneau de détail du chapitre ou de l’agent.
- **Mobile** : une colonne ; prochaine action humaine avant les détails ; carte à hauteur maîtrisée et contrôles toujours accessibles. Pas de copie miniature d’un dashboard desktop.
- Conserver les choix et la progression lors d’un changement d’écran ou d’une reconnexion. Un refresh ne doit pas lancer une deuxième mission.
- La vue navigateur H réelle peut nécessiter une connexion ou refuser l’iframe : afficher un lien explicite et le suivi utile, jamais une vue simulée prétendument live.

## 4. Composants et états à spécifier avant le parallèle

| Composant partagé | États à couvrir |
| --- | --- |
| Saisie et micro | Prêt, permission demandée/refusée, écoute, transcription, erreur et repli texte. |
| Étape agent | En attente, actif, pause demandée, pause confirmée, question humaine, arrêté avant engagement, échec, terminé. |
| Question humaine | Ouverte, réponse en envoi, acceptée, expirée, refusée, mission annulée ; liens accessibles entre état et question. |
| Budget | Chargement, complet, partiel, plafond dépassé, offre périmée ; devise et date de collecte. |
| Carte et lecteur | Initialisation, tuiles lentes, lecture, pause, chapitre sélectionné, géométrie illustrative, WebGL indisponible, repli 2D. |
| Source et provenance | Réel, démo, replay ; vérifié, estimé, illustratif ou inconnu. |
| Export | Disponible, génération, erreur avec reprise ; instantané versionné et adresse protégée. |

Définir un vocabulaire commun et une seule convention d’événements entre la carte, le shell et le backend. Les identifiants de question/mission/révision ne sont pas reconstruits côté UI.

## 5. Frontend réellement parallélisable

1. D1 livre tokens, structure des écrans et mocks de composants basés sur les fixtures G1.
2. En parallèle, C1/C2 développent la carte/lecture sur ces fixtures ; D2 développe la voix et les commandes ; D3 prépare les cas clavier/mobile.
3. D1 intègre les composants visuels sans dépendre des appels H. E3 branche ensuite les événements et données réelles, un point central à la fois.
4. D3 relève les défauts avec écran, reproduction, résultat attendu et sévérité ; D1/C3 corrigent leurs propres fichiers.
5. Le chef D valide cohérence et finition, puis E vérifie le parcours complet.

Éviter trois agents qui modifient le même index.html ou la même feuille CSS. Découpage en modules uniquement quand nécessaire ; pas de migration React/Vue pour justifier l’organisation.

## 6. Gate de finition : on ne dit pas « joli » sans preuves

### Avant l’implémentation finale

- Une direction visuelle explicite et deux écrans de référence : **question humaine** et **séjour avec carte**.
- Captures ordinateur et mobile à présenter à Iba et Mathieu ; évolution du travail V1, pas seconde maquette concurrente.
- Tokens et contrats de composants partagés avant lancement des finitions parallèles.

### Avant de livrer l’aperçu

- Parcours principal relu à **360 px, 768 px et 1440 px** ; aucune coupure de texte ou action inaccessible. Pas de défilement horizontal du parcours principal.
- Usage intégral au clavier, focus visible, ordre logique, libellés de formulaire, erreurs reliées aux champs et annonces d’état pertinentes pour lecteur d’écran.
- Cible WCAG 2.2 AA : contrastes vérifiés, sens non porté par la couleur seule, zones de clic confortables, mouvement réduit respecté. Une checklist ne vaut pas certification de conformité.
- Le changement de statut d’un agent ne fait pas perdre le focus d’une réponse en cours. Pas d’autoscroll qui empêche de lire.
- Un échec réseau, une réponse expirée, un quota saturé et une carte indisponible donnent une action de récupération concrète.
- Réponse humaine et commande de pause réagissent visuellement dès l’envoi ; confirmation distante distincte de la simple réception locale.
- La page affiche son shell et les contrôles sans attendre les tuiles ou fournisseurs ; chargement différé de la 3D, ressources libérées en quittant la vue, pas de boucle d’animation active une fois en pause.
- Aucune erreur console inattendue sur le parcours validé ; défauts tiers documentés. Performances mesurées sur le candidat et l’environnement indiqués, pas garanties sans mesure.
- Budget, sources et réserves identiques entre résumé, carte et exports ; aucune donnée demo sans mention.
- Une recette UI sur le candidat exact, après accord, avec preuve du parcours complet ; puis **aperçu privé ouvrable ici**, pas publication implicite.

Le premier incrément 3D donne déjà la vision complète du séjour ; les transitions cinématiques ne doivent pas repousser la vraie question humaine ou la sûreté des actions.

## 7. Skills et limites de validation

La [PR #29](https://github.com/IbaDemesy/RunAI/pull/29) contient notamment frontend-design, accessibility, core-web-vitals, performance et webapp-testing. Vérifier leur présence et leurs instructions au démarrage ; ne pas les considérer fusionnés ni appliqués du seul fait de leur nom.

Les skills guident l’exécution ; les livrables restent les écrans intégrés, les états complets, les captures relues et les tests. La présence de ce plan ne prouve pas que le frontend actuel satisfait ces critères.
