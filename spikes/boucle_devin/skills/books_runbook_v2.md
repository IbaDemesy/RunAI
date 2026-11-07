# Runbook RunAI : books.toscrape.com

Pages autorisées (liste blanche RunAI, sécurité) :
- https://books.toscrape.com/ (accueil du catalogue)
- https://books.toscrape.com/catalogue/page-N.html (pages suivantes du catalogue)
- https://books.toscrape.com/catalogue/<slug>_<id>/index.html (fiche produit d'un livre, ouverte en cliquant sur son titre dans le catalogue)

N'ouvre aucune autre URL. Toute page hors de cette liste est interdite, même sur le même domaine.

Procédure :
1. Sur le catalogue, repère la carte du livre (titre complet dans l'attribut title du lien) et lis le prix.
2. Clique sur le titre pour ouvrir sa fiche produit.
3. Dans le tableau « Product Information » de la fiche : UPC = ligne « UPC » ; stock = l'entier N de la ligne « Availability » (« In stock (N available) »).

Lecture seule : pas de panier, pas de formulaire.

Champs à rendre : titre, prix, upc, stock (entier).
status vaut exactement "ok" ou "bloque" (sans accent). Si un champ manque après l'étape 3, mets null, status "bloque" et explique pourquoi dans raison.
