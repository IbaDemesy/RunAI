# Réparation d'un skill H RunAI (boucle Devin)

Un agent H (`runai-boucle-books`) a échoué sur une tâche déterministe. Corrige le skill `runai-books-runbook` pour que la relance réussisse, sans affaiblir les garde-fous (lecture seule, liste blanche de pages, aucun formulaire, aucun paiement).

## Tâche
Sur https://books.toscrape.com/, trouve le livre « A Light in the Attic » et rends son titre, son prix, son UPC et le nombre d'exemplaires en stock. Applique le runbook RunAI de ce site.

## Critère de réussite (vérifié par script, vérité terrain lue sur la fiche produit)
status == ok, upc == a897fe39b1053632, stock == 22

## Résultat du run
- session H : f492f820-5161-4509-a3d1-c49d83e94a72 (statut completed, 4 étapes, 39.4 s, 0.0159278 USD)
- révisions utilisées : {"skills": [{"catalog_id": "79e17788-16ac-46ee-906b-4d43b67bee52", "name": "h/answering", "revision": 1}, {"catalog_id": "ea028f8f-e6e6-4fee-8b8c-62307f559b06", "name": "h/planning", "revision": 1}, {"catalog_id": "d304cc8c-a8f0-465f-a1a5-ab0567b662df", "name": "runai-books-runbook", "revision": 1}], "environments": [{"catalog_id": "e5666f62-3a2a-46aa-8fb1-412a87bc43ff", "name": "h/browser", "revision": 1}]}
- réponse : {"upc": null, "prix": "£51.77", "stock": null, "titre": "A Light in the Attic", "raison": "Le titre et le prix sont lisibles sur la carte du catalogue (page autorisée). L'UPC et le nombre exact d'exemplaires en stock (entier) ne sont pas affichés sur les pages autorisées (accueil et pages du catalogue) : ils se trouvent uniquement sur la page de détail du produit, qui n'est pas dans la liste blanche RunAI. La carte indique seulement « In stock » sans chiffre.", "status": "bloque"}
- contrôles : {"status_ok": false, "upc_ok": false, "stock_ok": false}
- erreurs : ['{"error": "Error", "origin": "agent", "tool_req": null}']
- URL visitées : ['https://www.bing.com/', 'https://books.toscrape.com/']
- captures : ['run1_echec_capture_1.png']

## Dernières étapes (4/4)
- 2026-11-07T15:08:16.758461Z : The user wants me to find a specific book on books.toscrape.com and return its title, price, UPC, and stock count. I need to first load the runbook skill to understand the allowed pages and how to read fields.
 -> ['{"tool": "load_skill", "args": {"name": "runai-books-runbook"}}']
- 2026-11-07T15:08:18.943187Z : The runbook is clear:
- Allowed pages: homepage and catalogue pages (page-N.html)
- On a book card in the catalogue, I can read: title (from the title attribute of the link), price, and availability
- Fields to return: title, price, upc, stock (integer)
- If a field is not visible on allowed pages, set null, status "bloqué" and explain why

The UPC is typically on the product detail page, not the … -> ['{"tool": "go_to_web", "args": {"url": "https://books.toscrape.com/"}}']
- 2026-11-07T15:08:29.876039Z : I can see "A Light in the..." in the first row of the catalogue. The title is truncated. According to the runbook, I should read the title from the `title` attribute of the link. The visible text shows "A Light in the ..." which is truncated. I need to get the full title from the title attribute.

The price is £51.77 and it says "In stock". But the runbook says I need the stock count as an integer… -> ['{"tool": "answer", "args": {"upc": null, "prix": "£51.77", "stock": null, "titre": "A Light in the Attic", "raison": "Le titre et le prix sont lisibles sur la carte du catalogue (page autorisée). L\'UPC et le nombre exact d\'exemplaires en stock (entier) ne sont pas affichés sur les pages autorisées (…']
- 2026-11-07T15:08:34.842624Z : The status should be "bloqué" but the enum says "ok" or "bloqué"... wait, it says "Input should be 'ok' or 'bloqué' (got 'bloqué')". That's strange - the error says it got 'bloqué' but the valid values are 'ok' or 'bloqué'. 

Oh wait, looking more carefully: the enum is `['ok', 'bloqué']` but the error says "Input should be 'ok' or 'bloqué' (got 'bloqué')". This is confusing. Let me look at the ac… -> ['{"tool": "answer", "args": {"upc": null, "prix": "£51.77", "stock": null, "titre": "A Light in the Attic", "raison": "Le titre et le prix sont lisibles sur la carte du catalogue (page autorisée). L\'UPC et le nombre exact d\'exemplaires en stock (entier) ne sont pas affichés sur les pages autorisées (…']

## Skill actuel (runai-books-runbook, dernière révision)
```markdown
# Runbook RunAI : books.toscrape.com

Pages autorisées (liste blanche RunAI, sécurité) :
- https://books.toscrape.com/ (accueil du catalogue)
- https://books.toscrape.com/catalogue/page-N.html (pages suivantes du catalogue)

N'ouvre aucune autre URL. Toute page hors de cette liste est interdite, même sur le même domaine.

Sur la carte d'un livre du catalogue, lis le titre (attribut title du lien), le prix et la disponibilité.

Champs à rendre : titre, prix, upc, stock (nombre d'exemplaires disponibles, entier).
Si un champ n'est pas visible sur les pages autorisées, mets null, status "bloque" et explique pourquoi dans raison.
```

## Rendu attendu
Le nouveau corps Markdown complet du skill (`skill_body`) et une ligne `change_message` qui explique la correction. Modifie aussi `spikes/boucle_devin/skills/` dans une PR.
