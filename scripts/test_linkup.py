from dotenv import load_dotenv
from linkup import LinkupClient

load_dotenv()

client = LinkupClient()
response = client.search(
    query="semi-marathon de Lisbonne mars 2027 date inscription",
    depth="fast",
    output_type="searchResults",
)
results = response.results
print(f"Nombre de résultats : {len(results)}")
if not results:
    raise SystemExit("Aucun résultat Linkup.")
print(f"Première URL : {results[0].url}")
