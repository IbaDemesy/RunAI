# Règles dures (communes à toutes les plateformes)

1. N'effectue AUCUN paiement. Ne clique jamais sur un bouton qui déclenche un paiement ou une soumission définitive
   ("Payer", "Valider et payer", "Confirmer la commande", "Procéder au paiement" sur la page de paiement, etc.).
   Arrête-toi sur la page récapitulatif/panier juste AVANT le paiement.
2. Utilise UNIQUEMENT le profil fictif fourni. N'invente aucune autre donnée personnelle.
   Si un champ obligatoire n'a pas de valeur dans le profil, laisse-le vide et note-le dans `champs_manquants`.
3. NE COCHE JAMAIS les cases liées à la santé : PPS (Parcours Prévention Santé), certificat médical,
   questionnaire de santé, attestation d'aptitude. Ne téléverse aucun document.
   Recopie leur texte exact dans `cases_sensibles` (avec `cochee=false`).
4. Les cases règlement / CGV / RGPD / droit à l'image : NE LES COCHE PAS non plus ; recopie leur texte dans
   `cases_sensibles`. C'est l'humain qui signera.
5. Si la suite exige de créer un compte, de se connecter, ou de valider un vrai e-mail (code reçu par mail),
   arrête-toi et mets `statut="COMPTE"`.
6. Si un captcha ou une page anti-bot apparaît, arrête-toi et mets `statut="CAPTCHA"`.
7. Si l'épreuve est complète ou fermée, mets `statut="COMPLET"`.
8. Si une case obligatoire non cochée bloque le passage à l'étape suivante, arrête-toi sur cette page et
   mets `statut="HUMAIN"` : c'est un succès attendu (l'humain prend la main).
9. Si tu atteins la page juste avant paiement, mets `statut="PAIEMENT"`.
10. Ne crée aucun compte, ne soumets aucun formulaire de manière définitive.
