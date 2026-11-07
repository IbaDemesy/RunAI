---
name: runai/njuko-devis
description: Use when the page is a njuko registration site (in.njuko.com or a white-label domain with the njuko footer) and the task asks for the current price, fees or paid options of a race, without registering.
---
# Lire un devis sur njuko (sans s'inscrire)

Parcours njuko (workflow de l'édition, lu via l'API publique) : choix de l'épreuve > formulaire participant > formulaires additionnels (conditions, confidentialité, « Services ») > étape assurance > panier > choix du paiement > paiement.

1. Refuse les cookies (« REFUSER »).
2. Page « select-competition » : chaque carte d'épreuve affiche DATE, HEURE, un texte libre (souvent « Les frais d'inscription comprennent : X euros de frais de service ») et « Tarif / Personne ». Relève ce prix : c'est le palier actuel. Si une icône info ou un tooltip de prix existe, survole-le pour lire les paliers suivants. La date de fin du palier n'est affichée que si l'organisateur l'a activée : si elle n'apparaît pas, mets null, ne la devine pas.
3. Si la carte est grisée ou indique complet / liste d'attente, mets complet=true et arrête-toi (etape_arret="choix_epreuve").
4. Tu peux cliquer « S'INSCRIRE » sur l'épreuve demandée et remplir UNIQUEMENT les champs d'identité avec le profil fictif fourni. N'utilise jamais d'autres données.
5. ARRÊT OBLIGATOIRE dès qu'apparaît : une case à cocher de règlement, de CGU, de confidentialité/RGPD, de santé, de certificat médical ou de PPS ; une demande de création de compte ou de mot de passe ; un bouton de paiement. Ne coche rien, ne clique pas « Valider » sur une page qui contient ces cases. Mets etape_arret="cases_consentement" (ou "identification_compte", "choix_paiement").
6. Avant de t'arrêter, liste toutes les options payantes visibles (t-shirt, repas/pasta party, assurance annulation, navette, photos, médaille gravée, dons, pass participation) avec leur prix et si elles sont obligatoires. Ne sélectionne aucune option.
7. Le panier njuko expire au bout de quelques minutes : ne reviens pas en arrière en boucle.
