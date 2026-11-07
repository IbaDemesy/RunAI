# Verification H (pret a lancer, NON lance dans ce spike)

Ce spike n'a cree aucune session H (consigne : les 3 slots vont a la boucle principale).
Ce prompt sert quand Linkup ne peut pas trancher : page d'inscription en SPA (Njuko renvoie une
erreur 400 a Linkup /fetch), statut "complet" visible seulement apres le choix de l'epreuve,
prix du palier actuel et options payantes affiches seulement dans le parcours d'inscription.

## Agent

- `agent`: `h/web-surfer-pro`
- URL de depart : `registration_url` renvoyee par `finder.py` (champ `to_check_with_H`).
- Une session par course a verifier, sequentielle, `cancel` systematique en fin de run.

## Prompt

```text
Tu verifies une inscription de course a pied, en lecture seule.
Course : {name}, epreuve {distance_label}, date attendue {date}.
Ouvre {registration_url}. Accepte seulement les cookies strictement necessaires.
1. Trouve l'epreuve {distance_label}. Note si elle est ouverte, complete, en liste d'attente,
   pas encore ouverte ou cloturee, avec la phrase exacte affichee.
2. Si elle est ouverte, avance dans le parcours d'inscription jusqu'a l'ecran qui affiche le prix
   et les options (t-shirt, repas, assurance annulation, navette, photos, don). Si un formulaire
   identite bloque l'acces aux prix, remplis-le avec : Camille Martin, camille.martin@example.com,
   nee le 12/05/1994, femme, France. Ne coche aucune case de reglement, de sante (PPS, certificat)
   ni de consentement.
3. Arrete-toi des qu'une creation de compte, une verification d'email, un captcha, un paiement ou
   une validation definitive est demandee. Ne clique jamais sur Payer, Valider ou Confirmer.
Reponds uniquement avec le format demande.
```

## answer_format (JSON Schema)

```json
{
  "type": "object",
  "required": ["registration_status", "status_evidence", "stopped_at", "final_url"],
  "properties": {
    "registration_status": {"enum": ["open", "full", "waitlist", "not_yet_open", "closed", "unknown"]},
    "status_evidence": {"type": "string", "description": "phrase exacte affichee"},
    "race_date": {"type": "string", "description": "YYYY-MM-DD lu sur la page"},
    "distance_km": {"type": "number"},
    "elevation_gain_m": {"type": ["number", "null"]},
    "current_price_eur": {"type": ["number", "null"]},
    "price_tier": {"type": ["string", "null"], "description": "palier en cours et date du prochain palier"},
    "options": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["label", "price_eur"],
        "properties": {
          "label": {"type": "string"},
          "kind": {"enum": ["tshirt", "repas", "assurance", "navette", "photos", "don", "autre"]},
          "price_eur": {"type": ["number", "null"]},
          "mandatory": {"type": "boolean"}
        }
      }
    },
    "requires_account": {"type": "boolean"},
    "requires_pps_or_certificate": {"type": "boolean"},
    "stopped_at": {"enum": ["status_page", "price_page", "account_wall", "captcha", "before_payment"]},
    "final_url": {"type": "string"}
  }
}
```

## Valeur ajoutee attendue de H (a mesurer)

| Information | Linkup /search + /fetch | H (attendu) |
| --- | --- | --- |
| Statut sur un site statique (Klikego, Protiming, site organisateur) | Oui, mesure | Inutile |
| Statut sur Njuko (SPA) | Non : /fetch renvoie 400 | Oui, page rendue dans un vrai navigateur |
| Epreuve complete alors que l'evenement est "ouvert" | Partiel : la page evenement ne le dit pas toujours | Oui, en choisissant l'epreuve |
| Prix du palier actuel | Souvent absent ou ambigu (grille de paliers) | Oui, dans le panier |
| Options payantes (t-shirt, repas, assurance, navette, photos) | Rarement | Oui, ecran des options |
