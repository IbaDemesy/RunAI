# Features à reprendre des projets du H Showcase

Ce document trie ce qu'on peut **brancher sur RunAI** à partir des projets déjà faits, et ce qui ne nous sert pas. Le détail de chaque projet est dans [BRAINSTORM.md](BRAINSTORM.md#projets-déjà-faits-h-showcase).

On reste sur la course à pied. L'idée est de ne pas réinventer ce qui existe déjà : on reprend les briques qui ont marché et on les assemble autour de notre feature, « Dis-moi ta course, je prépare tout le déplacement ».

**Licences** : le code des démos officielles H ([agents-api-demos](https://github.com/hcompai/agents-api-demos)) et [Pricehunter](https://github.com/lmveprog/pricehunter) sont sous licence MIT, on peut s'en servir directement. Pour les autres projets, il faut **vérifier la licence du repo avant de copier du code**. Reprendre une idée reste toujours possible.

Les priorités suivent celles de BRAINSTORM.md :
- **P0** : voix → Linkup → inscription H → validation. Ça doit marcher à 100 %.
- **P1** : vol et hôtel en parallèle, correction vocale.
- **P2** : vision, à garder pour le pitch.

## P0 : le cœur de la démo

| Feature | Projet source | Ce qu'on en fait dans RunAI |
| --- | --- | --- |
| Agent minimal en quelques lignes du SDK `hai-agents`, avec « ne pas payer » dans le prompt | [Add to cart](https://github.com/hcompai/agents-api-demos/tree/main/examples/add_to_cart) (MIT) | Point de départ du test de faisabilité et de l'agent d'inscription. On s'arrête avant le paiement. |
| Booléen de réussite vérifié à l'écran (`added_to_cart` ne vaut `true` que si le panier affiche l'article) | Add to cart (MIT) | Un champ `form_ready_for_payment` qui ne vaut `true` que si la page récap est réellement affichée. |
| Réponse typée par un schéma JSON (`agent.answer_format`) | [Pricehunter](https://github.com/lmveprog/pricehunter) (MIT), [Product availability](https://github.com/hcompai/agents-api-demos/tree/main/examples/product_availability) (MIT) | Chaque agent renvoie un objet structuré : course, distance, prix, champs remplis, champs manquants, URL. |
| Backend FastAPI, une session H par agent, une page de suivi | Pricehunter (MIT) | La base de notre orchestrateur. C'est le code le plus proche de notre architecture. |
| Filtre de sécurité côté serveur, pas seulement dans le prompt | Pricehunter (MIT) | Le serveur vérifie que le récap correspond à la demande (bonne course, bonne distance, prix sous le plafond) avant de le montrer au coureur. |
| Vue live de chaque navigateur | Pricehunter (MIT) | La vue live des agents dans notre PWA. |
| Trace du run étape par étape, avec le raisonnement de l'agent | [Price Check](https://showcase.hcompany.ai/a/price-check-test/) | Le fil d'actions affiché sous chaque agent. |
| Vérifier les options qui changent le prix | Price Check | L'agent vérifie la distance et les options payantes avant d'annoncer le prix final. |
| Confirmation vocale avant toute action irréversible | [Life-Admin Operator](https://github.com/chinesepowered/hack-h) (licence à vérifier) | Un « oui » prononcé avant de passer au paiement. Leur code de gestion des confirmations est à lire. |
| Valeurs manquantes laissées à `null`, jamais inventées | [ArcFlash Copilot](https://github.com/techadnank9/arcflash) (licence à vérifier) | Un champ du profil coureur absent (licence, contact d'urgence) déclenche une question vocale. Le récap montre ce qui manque. |
| Code déterministe pour tout ce qui n'a pas besoin d'un agent | [Claw-DJ](https://github.com/InServiceOfX/claw-dj) (principe) | Profil coureur, calcul des dates et des distances, contrôle du récap : en code classique, pas dans un prompt. |
| Le planificateur décide, l'agent H exécute | [Hiking Routes](https://github.com/Exynos-8890/0711hack), [Agent Kalshi](https://github.com/DhruvMiyani/hcompany-hack26), [CUA Molecular Visualizer](https://github.com/RyanDennis916/NUA-Computer-Use) (principe) | Linkup et l'orchestrateur choisissent, et chaque agent H reçoit une mission précise. |

## P1 : fiabilité et parallélisme

| Feature | Projet source | Ce qu'on en fait dans RunAI |
| --- | --- | --- |
| Agent vérificateur indépendant | [Houston](https://github.com/nossa-y/houston-hackathon) (licence à vérifier) | Un second agent H relit la page récap avant le paiement et renvoie un verdict typé. C'est notre meilleur argument « fiabilité ». |
| Correction dans la même session (steering) | Houston, Hiking Routes | « Prends plutôt le 21 km » corrige l'agent en cours de route, sans relancer tout le parcours. |
| Critère de réussite vérifiable pour chaque étape | [Reel-Learn](https://github.com/ipsita-praharaj/Reel-Learn) (licence à vérifier) | Chaque étape a sa condition : « la page affiche le bon nom, la bonne distance, le bon prix ». |
| Détection des boucles | Reel-Learn | Si l'agent répète la même action, on l'arrête et on rend la main au coureur. |
| Un guide par plateforme, à partir d'une inscription faite à la main | [AI Runbooks](https://github.com/omkarpat/ai-runbooks) (licence à vérifier) | Un runbook pour Njuko, un pour Klikego… donné à l'agent avec ses critères de vérification. |
| Étapes écrites en langage naturel plutôt qu'en sélecteurs figés | [ImproveMe](https://github.com/zach2940/improveme) (principe) | Les instructions résistent aux changements de mise en page des sites. |
| Données personnelles remplacées par des jetons | [Privacy Layer](https://github.com/dael-amz/browser-agent-privacy-layer) (principe) | Le prompt contient `{{runner.birth_date}}`, et le serveur ne fournit la vraie valeur qu'au remplissage. C'est un argument « confiance » pour le pitch. |
| Captures et actions horodatées, rejouables | [GrannySmith](https://github.com/ducnguyen67201/AngryGrandmy), Houston (principe) | On garde la preuve de chaque run, pour le récap et pour le replay en démo. |
| Agent QA qui vérifie une page web | [QA any web UI](https://github.com/hcompai/agents-api-demos/tree/main/examples/qa) (MIT) | Vérifier notre faux site d'inscription avant la démo. |
| Scénarios de test en langage courant rejoués dans la CI | [A-Test](https://github.com/dzianisv/a-test) (licence à vérifier) | Rejouer les scénarios de démo à chaque PR. Devin, qui code le projet, a ainsi un vrai retour. Piste pour le prix « Best Use of Devin ». |
| Notification et boutons de validation sur une messagerie | ImproveMe (WhatsApp), [Holo Forge](https://github.com/exemplary-citizen/computer-use-hackathon) (Telegram) | Prévenir le coureur quand l'inscription attend le paiement. |
| Un agent préparé par un agent de code, exécuté par H | [Cloud CUA](https://github.com/Jiyungi/cloud_CUA) (principe) | Devin prépare un « contrat » (champs à remplir, critères) et H l'exécute. Piste « Best Use of Devin ». |

## P2 : vision pour le pitch

| Feature | Projet source | Ce qu'on en fait dans RunAI |
| --- | --- | --- |
| Vidéo tutoriel commentée générée automatiquement | [Voodoo](https://github.com/Masmedeam/holo-tuto) | Une vidéo récap de chaque mission, utile aussi pour les posts LinkedIn ou X (prix de 500 €). |
| Les erreurs deviennent des règles réutilisables | Cloud CUA, Reel-Learn | Une bibliothèque de skills par plateforme d'inscription, enrichie à chaque échec. |
| Runs planifiés | ImproveMe | Lancer l'inscription automatiquement à l'heure d'ouverture d'une course. |
| Modèles de tâches et extension Chrome | [Halo](https://github.com/vaibhavgeek/hcompany-hack-sf) | « Inscris-moi avec mon profil habituel » depuis la page d'une course. |
| Agent sur mobile | [HoloMobile](https://github.com/swswsw/AndroidUseH) | Applis de courses ou appli SNCF. |
| Reçu chaîné par hash | Houston | Preuve infalsifiable de ce que l'agent a fait. |

## Ce qui ne nous sert pas

| Projet ou feature | Pourquoi |
| --- | --- |
| HoloBlocks, HoloBricks | Construction 3D ou en briques. Seule leur structure d'app (serveur Python + front npm) peut servir de référence. |
| Claw-DJ (Mixxx), CUA Molecular Visualizer, ArcFlash Copilot (arc électrique), Cloud CUA (console AWS) | Métiers sans rapport avec le nôtre. On garde seulement leurs principes, listés plus haut. |
| Workfleet (clonage de la machine) | Chaque agent H a déjà son propre navigateur cloud, donc le parallélisme ne nous coûte rien. |
| Holo Forge, Holodev, apps desktop sur macOS ou Windows | RunAI ne passe que par des sites web. |
| Reel-Learn : apprendre en regardant une vidéo | Inutile pour remplir un formulaire. On garde seulement les critères de réussite et la détection des boucles. |
| GrannySmith, Simulation Labs : heatmaps et tests d'usabilité | Sans intérêt pour le coureur. On garde seulement l'enregistrement des runs. |
| Floutage des captures sur la machine (CoreML de Privacy Layer) | Trop lourd et spécifique à macOS pour le hackathon. On garde seulement les jetons. |
| Modèle ML d'Agent Kalshi | Rien à prédire chez nous. |
| FollowThrough, Kylian : assistant vocal généraliste | Rien de nouveau à reprendre. Ils confirment surtout que la chaîne voix → recherche → action est déjà connue. |
| Stack NVIDIA (NemoClaw, Nemotron), Gradium, LiveKit, Codex, Hermes | Ce ne sont pas nos partenaires. Pour nous : Gladia pour la voix, Linkup pour la recherche, H pour l'action, Devin pour construire. |
| Le thème « QA » ou « rejouer une vidéo » comme sujet principal | Le jury en a déjà vu beaucoup. On s'en sert comme outils internes, pas comme sujet. |

## Projets pas encore étudiés

Vus dans les liens « More from » du showcase, mais pas encore lus en détail : **BuyWith402** (des agents H remplissent des commandes sur n'importe quel site, donc très proche de nous, à regarder en priorité), Kylian, Glassbox, Snowglobe, Handyman, Holodev, AI Teaching Assistant et Simulation Labs.
