# bioinformatics/locus-novelty/tests/test_ld_plink.py
import ld_plink


LD_OUTPUT = """CHR_A\tBP_A\tSNP_A\tCHR_B\tBP_B\tSNP_B\tR2
9\t123773274\trs3945628\t9\t123780000\trs999\t0.95
9\t123773274\trs3945628\t9\t123785000\trs888\t0.15
"""


def test_plink_r2_parses_ld_file(monkeypatch, tmp_path):
    # Make the fake plink write a .ld file instead of running
    def fake_run(args):
        out_prefix = args[args.index("--out") + 1]
        open(out_prefix + ".ld", "w").write(LD_OUTPUT)
        return 0
    monkeypatch.setattr(ld_plink, "_run_subprocess", fake_run)
    pairs = ld_plink.plink_r2("rs3945628", ["rs999", "rs888"], "fake_bfile", tmp_path)
    assert pairs[("rs3945628", "rs999")] == 0.95
    assert pairs[("rs3945628", "rs888")] == 0.15
