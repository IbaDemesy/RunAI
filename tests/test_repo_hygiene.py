from scripts.check_repo_hygiene import main, violations


def test_flags_private_partner_files_and_env():
    paths = ["Infos/README.md", "Infos/credits.pdf", "Infos/notes.txt", "docs/offer.PDF", ".env", ".env.local", ".env.example", "runai/app/server.py"]
    flagged = {line.split(":")[0] for line in violations(paths)}
    assert flagged == {"Infos/credits.pdf", "Infos/notes.txt", "docs/offer.PDF", ".env", ".env.local"}


def test_current_repository_is_clean():
    assert main() == 0
