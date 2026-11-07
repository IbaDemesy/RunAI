# Vérification manuelle (7 nov. 2026)

4 champs par course, comparés aux pages sources (téléchargées avec curl, PDF lus avec pdftotext).
✓ correct · ✗ faux · vide = Linkup n'a rien renvoyé · NV = non vérifiable (source officielle introuvable ou rendue en JS).

## Variante A : `standard` puis `deep` si un champ critique manque (`results/*.json`)

| Course (plateforme) | Date | Heure de départ | Lieu de départ | Retrait des dossards |
| --- | --- | --- | --- | --- |
| Wizz Air Milano Marathon (Njuko) | ✓ 04/04/2027 (FAQ officielle) | vide | NV « Corso Sempione » (absent des pages lues) | ✓ 1-3 avril au Milano Running Festival (FAQ) ; horaires NV |
| Semi de La Rochelle (Klikego) | ✓ 14/03/2027 | ✓ 08:30 | ✓ av. Edmond Grasset | vide (la page Klikego le donne : Leclerc Lagord, ven./sam.) |
| Marathon Royan Côte de Beauté (Klikego) | ✓ 23/05/2027 | ✓ 07:15 | ✓ place Charles-de-Gaulle | ✓ 21 mai 14h-19h, 22 mai 9h30-19h, village marathon (règlement art. 17) |
| EDP Meia Maratona de Lisboa (MCP) | ✓ 07/03/2027 | ✓* 09:20 | ✓ Ponte 25 de Abril | ✗ jours 5-6 mars au lieu de 4, 5 et 6 (lieu et horaires ✓) |
| ASICS Marathon de Paris (ASO) | ✓ 04/04/2027 (FAQ) | vide | ✗ « Champs-Élysées » : la FAQ dit que le parcours 2027 n'est pas dévoilé (le règlement ne cite que l'adresse du siège, 66 av. des Champs-Élysées) | vide (correct : le règlement renvoie à des modalités futures) |

\* Conflit de sources officielles : le site MCP affiche « 09:20 Partida », le règlement PDF dit « início previsto para as 09h30m ».

- Champs remplis : 16/20 (80 %). Corrects : 13. Faux : 2. NV : 1.
- **Précision : 13/16 = 81 %** (NV compté faux) ; 13/15 = 87 % sur les champs vérifiables.

## Variante B : `standard` puis `/fetch` + schéma sur le règlement ou le site (`results/fetch/*.json`)

| Course | Date | Heure | Lieu | Retrait |
| --- | --- | --- | --- | --- |
| Milan | ✓ | vide | vide | ✓ jours (horaires NV) |
| La Rochelle | ✓ | ✓ | ✓ | vide |
| Royan | ✓ | vide | vide | vide (fetch en erreur `FetchTargetUnreachable`) |
| Lisbonne | ✓ | ✓* 09:20 | ✓ | ✗ 5-6 mars |
| Paris | ✓ | vide | vide | vide |

- Remplis : 11/20 (55 %). **Précision : 10/11 = 91 %.**

## Autres champs contrôlés (hors précision)

- Plateforme : Milan → Njuko confirmé (la page `milanomarathon.it/maratona/iscriviti` redirige vers njuko.net) ; La Rochelle et Royan → Klikego, URL exactes ✓ ; Lisbonne → plateforme MCP (tirage au sort) ✓ ; Paris → pas d'URL renvoyée.
- Statut : Royan « ouvert » ✓ (bouton S'inscrire, 65 €, « complet à 58 % » sur le semi). La Rochelle « inconnu » : la page Klikego montre « Bourse d'échange » pour le semi individuel (tirage déjà fait). Lisbonne et Paris « inconnu » (tirages au sort). Linkup n'a jamais affirmé à tort « ouvert » ou « complet ».
- Documents : Paris PPS ou licence FFA ✓ (règlement 2.3) ; Lisbonne pas de certificat ✓ ; Milan licence ou Runcard + certificat ✓ (FAQ).
