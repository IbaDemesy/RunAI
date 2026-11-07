# Skill Klikego (www.klikego.com)

Parcours connu (testé le 7 nov. 2026 sur le 10 km du Maine Libre) :
1. Page de l'événement `/inscription/<slug>/<sport>/<id>` : section "Les épreuves" avec le prix "À partir de".
   Ferme le bandeau cookies.
2. Clique sur l'épreuve demandée puis "S'inscrire". Ignore les épreuves "Bourse d'échange" ou complètes.
3. Si Klikego propose "Se connecter" ou "Continuer sans compte / en invité" : choisis TOUJOURS le mode invité.
   Si seule la connexion est possible ("Connexion requise"), arrête-toi : `statut="COMPTE"`.
4. Formulaire participant : nom, prénom, sexe, date de naissance, nationalité, e-mail, téléphone, adresse,
   club, licence. Non licenciée.
5. Le parcours invité peut demander un mot de passe pour créer un "profil coureur" :
   ne remplis PAS de mot de passe, arrête-toi et mets `statut="COMPTE"` en recopiant le texte.
6. Bloc PPS / certificat médical : ne coche rien, ne téléverse rien. Recopie le texte.
7. Options (t-shirt, repas, dons, assurance) : n'en prends aucune, note-les.
8. Page récapitulatif / panier avec bouton de paiement : arrête-toi. Relève total et URL.

## Appris au run H du 7 nov. 2026 (session 501f4316-4bb6-4762-a69f-8aebea3196ab, Semi Boucle de Seine)
- "S'inscrire" mène directement au formulaire `/types/generic/custo/x.running2/formulaire-1.jsp?version=v6`
  (pas d'écran "invité/connexion" séparé).
- Le MÊME formulaire contient le bloc "Informations de connexion à votre compte" : "Un compte KLIKEGO va vous
  être créé gratuitement" + identifiant (pré-rempli avec l'e-mail) + mot de passe + confirmation.
  → Laisse les mots de passe vides, arrête-toi : `statut="COMPTE"`. L'humain choisit son mot de passe.
- Tarif à choisir : "Non licencié FFA" (palier en cours) ; frais de gestion Klikego ajoutés (2,50 € ici).
- Champ "SAS de départ" obligatoire (tranches de temps) : absent du profil → `champs_manquants`
  (à ajouter au profil coureur RunAI : temps visé).
- Cases à NE PAS cocher : "Règlement à accepter", "J'autorise l'organisateur à communiquer mes coordonnées
  aux partenaires", radio "J'accepte les nouvelles Conditions Générales d'Utilisation de Klikego".
- Options payantes vues : envoi du dossard, t-shirt collector, cadre finisher, garantie remboursement, résultat SMS.
