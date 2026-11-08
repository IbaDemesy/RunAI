from pathlib import Path

from scripts import check_design_tokens as design

TOKENS = Path(__file__).resolve().parents[1] / "docs/design/tokens.css"


def test_design_tokens_pairs_and_required_names():
    assert design.errors(TOKENS.read_text(encoding="utf-8")) == []


def test_design_tokens_root_block_is_well_formed():
    source = TOKENS.read_text(encoding="utf-8")
    assert source.count("{") == source.count("}")
    root = design.root_tokens(source)
    assert len(root) > 80 and all(value.strip() for value in root.values())


def test_contrast_table_in_doc_is_current():
    doc = (TOKENS.parent / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")
    assert design.markdown(TOKENS.read_text(encoding="utf-8")) in doc
