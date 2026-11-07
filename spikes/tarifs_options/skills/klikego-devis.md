---
name: runai/klikego-devis
description: Use when the page is on klikego.com (event page /inscription/...) and the task asks for the current price, fees, price tiers or paid options of a race, without registering.
---
# Lire un devis sur Klikego (sans s'inscrire)

1. Page de l'événement : section « Les épreuves ». Chaque tuile affiche « À partir de X € » (prix le plus bas, pas forcément le palier actuel), la date, l'heure et éventuellement « Complet à N% » ou « Bourse d'échange » (épreuve complète : seule la revente est possible).
2. Clique sur la tuile de l'épreuve demandée (pas sur le bouton « S'inscrire ») : une fenêtre s'ouvre avec le détail des tarifs, par exemple « Droit d'inscription : 65 € », « 3,00 € de frais de gestion Internet seront ajoutés à votre inscription lors du paiement en ligne », « Inscriptions dernière minute : 70 € si après le ... », « Tarif FFA / Tarif Non-Licencié ». Relève chaque tarif comme un palier, et les frais de gestion tels qu'affichés (ils varient selon l'organisateur : ne les recalcule pas). Prends le tarif non licencié pour un coureur sans licence.
3. Ferme la fenêtre et lis la description de l'événement : les options payantes (t-shirt, assurance annulation, repas, navette, photos, dons) y sont souvent décrites avec leur prix. Elles sont choisies plus loin, dans le formulaire.
4. ARRÊT OBLIGATOIRE à la page « Inscription personnelle » (après « S'inscrire ») : l'étape suivante demande un e-mail et crée un compte Klikego. Ne saisis aucun e-mail, ne clique ni « Je suis nouveau » ni « Continuer ». etape_arret="identification_compte" si tu l'as atteinte, sinon "fiche_epreuve".
5. Les CGU Klikego interdisent d'« utiliser des robots » et de « fournir des informations personnelles fausses » : ne remplis aucun formulaire sur Klikego.
