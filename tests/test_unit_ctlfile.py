import pytest

from bpp_mcp import ctlfile

CTL = """\
* comment line
          seed = -1
       seqfile = data.txt   * trailing comment
      Imapfile = data.imap
# thetaprior = ???            # REQUIRED -- e.g. invgamma 3 0.002
  species&tree = 3  A  B  C
                  2  2  2
                  ((A,B),C);
         nloci = 2
         print = 1 0 0 0 0
    printlocus = 2 1 2
"""


def test_get():
    assert ctlfile.get(CTL, "seed") == "-1"
    assert ctlfile.get(CTL, "seqfile") == "data.txt"
    assert ctlfile.get(CTL, "imapfile") == "data.imap"   # case-insensitive
    assert ctlfile.get(CTL, "thetaprior") is None        # placeholder is a comment
    assert ctlfile.get(CTL, "print") == "1 0 0 0 0"      # not printlocus
    assert ctlfile.get(CTL, "missing") is None


def test_set_existing_keeps_layout():
    out = ctlfile.set_value(CTL, "nloci", "1")
    assert "         nloci = 1\n" in out
    assert out.replace("nloci = 1", "nloci = 2") == CTL


def test_set_replaces_placeholder():
    out = ctlfile.set_value(CTL, "thetaprior", "invgamma 3 0.01")
    assert "thetaprior = invgamma 3 0.01\n" in out
    assert "???" not in out
    assert out.count("\n") == CTL.count("\n")


def test_set_appends_new():
    out = ctlfile.set_value(CTL, "threads", "4 1 1")
    assert out == CTL + "threads = 4 1 1\n"
    assert ctlfile.set_value("seed = 1", "nloci", "2") == "seed = 1\nnloci = 2\n"


def test_set_rejects_multiline():
    with pytest.raises(ValueError):
        ctlfile.set_value(CTL, "seed", "1\nnloci = 9")


def test_species():
    assert ctlfile.species(CTL) == ["A", "B", "C"]
    assert ctlfile.species("seed = 1\n") is None
