# Stratégie pour le prix « Best Use of Devin » (1 000 €)

## Principe

Avoir codé avec Devin ne suffit pas : tout le monde le fera. L'originalité, c'est **Devin dans la boucle du produit, pendant que RunAI tourne**, pas seulement pendant sa construction.

## Idée 1 (recommandée) — RunAI qui s'auto-répare

Quand un agent H échoue sur une plateforme (boucle, champ introuvable, formulaire inconnu) :

1. RunAI envoie la **trace H** (étapes, captures, erreur) à une session Devin via l'[API Devin](https://docs.devin.ai).
2. Devin écrit ou corrige le **runbook de la plateforme** : consignes, champs, critères de réussite.
3. Devin relance un **test H** pour vérifier la correction, puis ouvre une PR.
4. Après revue et merge, le prochain coureur utilise le runbook corrigé et passe.

**H agit → échoue → Devin répare → H réussit.**

Cette boucle renforce aussi la **fiabilité (25 % de la note)**. Les tests gardent nos règles : faux profil, aucun compte créé à la place de l'utilisateur, aucun paiement ni réservation finale.

**Moment démo** : « Ce site a fait échouer l'agent ce matin, Devin a ouvert cette PR, maintenant ça passe. »

## Idée 2 — Nouvelle plateforme à la demande

Une course se trouve sur une plateforme jamais vue : RunAI lance une session Devin qui explore le parcours, écrit un **adaptateur + runbook**, puis teste avec H. Même mécanique que l'auto-réparation, mais proactive.

## Idée 3 — QA continue

Une session Devin planifiée rejoue la nuit les parcours **Njuko, Klikego, Booking et TAP**, détecte les changements de mise en page et corrige les runbooks. Toujours avec arrêt avant paiement et validation des changements par PR.

## Ce qu'il faut montrer au jury

- **1 à 2 vraies PR ouvertes par Devin depuis RunAI pendant le hackathon**, avec la trace d'échec et le test de vérification.
- Le **schéma de boucle** H → échec → Devin → correction → H.
- L'**historique des PR du repo**, comme preuve de construction avec Devin, en complément de son rôle dans le produit.

## Prérequis / coût

- **P1 : environ 2 à 3 h** estimées pour le module ; ne pas fragiliser le parcours principal pour l'ajouter.
- Une **clé API Devin**, conservée côté backend. Documentation : [docs.devin.ai](https://docs.devin.ai). Le coût d'exécution des sessions reste à vérifier, distinct du temps de développement.
- Des **runbooks par plateforme stockés comme fichiers dans le repo** : cette brique est déjà identifiée dans [FEATURES_A_REPRENDRE.md](FEATURES_A_REPRENDRE.md).
- Le périmètre, les garde-fous et les pistes de fiabilité restent ceux de [BRAINSTORM.md](BRAINSTORM.md).
