# Skill Njuko (in.njuko.com)

Parcours connu (testé le 7 nov. 2026 sur le 10 km de Hyères) :
1. Page d'accueil de l'événement : `?currentPage=select-competition` liste les épreuves (date, places restantes, tarif).
   Accepte ou refuse le bandeau cookies ("Refuser" suffit).
2. Clique "S'inscrire" sur la ligne de l'épreuve demandée (pas sur une épreuve "Complet").
3. Choisis "Individuelle" si on te demande le type d'inscription.
4. Formulaire coureur : nom, prénom, sexe, date de naissance, e-mail (souvent deux fois), téléphone,
   nationalité, adresse, club / licence. Si "licencié FFA ?" : réponds non.
5. Bloc PPS / certificat : ne coche rien, ne téléverse rien. Recopie le texte.
   Si Njuko propose "je fournirai mon PPS plus tard", NE LE COCHE PAS non plus, note-le.
6. Options payantes (t-shirt, repas, assurance annulation) : n'en prends aucune, note-les.
7. Bouton "Ajouter au panier" / "Valider" de l'étape coureur : autorisé (le panier n'est pas un paiement).
8. Page panier / récapitulatif : arrête-toi ici. Ne clique pas "Payer" / "Procéder au paiement".
   Relève le montant total et l'URL.
Pas de compte requis jusqu'au panier (constaté le 7 nov.). Pas de captcha constaté.

## Appris au run H du 7 nov. 2026 (session 3c2947ae-fea1-4476-bd44-6b013d22eeab)
- Le formulaire participant (`?currentPage=form_formulaire-participant`) contient un bloc obligatoire
  "PIÈCE JUSTIFICATIVE — Votre justificatif (Majeur) *" avec deux radios : "Licence FFA (Compétition,
  Running, Entreprise)" et "Numéro PPS.". "SUIVANT" reste bloqué ("Le champ ne peut pas être vide.").
  → Remplis tout le reste, ne coche aucune des deux, puis arrête-toi : `statut="HUMAIN"`.
  C'est le point de passage à l'humain (il saisit son PPS), pas un échec. N'essaie pas d'autres contournements.
- Le choix "Je souhaite apparaître dans les résultats" (Oui/Non) est obligatoire et non sensible : "Oui".
- "Souhaitez-vous un SAS préférentiel ?" : laisse vide.
