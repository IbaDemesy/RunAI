"""Cache des résultats bruts du finder : rejouer la démo sans réseau.

Un `DiscoveryResult` est stocké en JSON sous `<cache_key>.json`. Le classement (qui dépend du
niveau du coureur) est refait à chaque lecture, donc un même fichier sert à plusieurs profils.
"""

from pathlib import Path

from runai.coach.models import DiscoveryResult, SearchQuery

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class DiscoveryCache:
    """Lit dans `directory` puis dans `fallbacks` (par défaut les fixtures du package) ; écrit dans `directory`."""

    def __init__(self, directory: Path = FIXTURES_DIR, fallbacks: tuple[Path, ...] = (FIXTURES_DIR,)):
        self.directory = Path(directory)
        self.fallbacks = tuple(Path(p) for p in fallbacks if Path(p) != self.directory)

    def path(self, query: SearchQuery) -> Path:
        return self.directory / f"{query.cache_key()}.json"

    def get(self, query: SearchQuery) -> DiscoveryResult | None:
        name = f"{query.cache_key()}.json"
        for folder in (self.directory, *self.fallbacks):
            file = folder / name
            if file.is_file():
                return DiscoveryResult.model_validate_json(file.read_text(encoding="utf-8"))
        return None

    def put(self, result: DiscoveryResult) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        file = self.path(result.query)
        file.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        return file

    def list(self) -> list[DiscoveryResult]:
        files = {f.name: f for folder in (*reversed(self.fallbacks), self.directory) if folder.is_dir() for f in folder.glob("*.json")}
        return [DiscoveryResult.model_validate_json(f.read_text(encoding="utf-8")) for _, f in sorted(files.items())]
