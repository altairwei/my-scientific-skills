# bioinformatics/locus-novelty/tests/test_cli_boot.py
def test_cli_imports_cleanly():
    import locus_novelty
    assert hasattr(locus_novelty, "run_pipeline")
    assert hasattr(locus_novelty, "main")
