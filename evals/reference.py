"""A known-good sequence of tool calls for every scenario.

These are not what a model must do; they prove that each scenario can be
solved with the server's tools and that the grader passes a correct solution.
`tests/test_evals.py` replays them through the harness with no model involved.
"""
from __future__ import annotations

ANAS_JOINS = ("fraterculus+obliqua, distincta+fraterculus_obliqua, "
              "suspensa+distincta_fraterculus_obliqua, "
              "turpiniae+distincta_fraterculus_obliqua_suspensa")
LOCI = {"files": ["loci/*.fasta"], "imap": "imap.txt"}


def _finish(ctl: str) -> list:
    return [[("lint_control_file", {"ctl": ctl})], [("smoke_test", {"ctl": ctl})],
            [("run_command", {"ctl": ctl})], "The control file is ready; here is how to run it."]


def _anas(analysis: str = "A00", tree: list | None = None, seqfile: str = "data/anas.txt",
          nloci: int = 10, before_make: list | None = None, **make) -> list:
    tree = tree or [("build_species_tree", {"joins": ANAS_JOINS, "imap": "data/anas.imap",
                                            "out_prefix": "data/sp"})]
    return [
        [("check_environment", {})],
        [("inspect_data", LOCI)],
        [("convert_data", {**LOCI, "out_prefix": "data/anas"})],
        tree,
        *(before_make or []),
        [("make_control_file", {"analysis": analysis, "seqfile": seqfile,
                                "imapfile": "data/anas.imap", "stree_file": "data/sp.stree",
                                "out": "run.ctl", "nloci": nloci, **make})],
        *_finish("run.ctl"),
    ]


SOLUTIONS: dict[str, list] = {
    "anas_delimitation": _anas("A10"),
    "anas_parameters": _anas("A00"),
    "anas_species_tree": _anas("A01"),
    "anas_joint": _anas("A11"),
    "anas_unphased": _anas(before_make=[[("lookup_docs", {"keyword": "phase"})]],
                           phase="1 1 1 1 1"),
    "anas_migration": _anas(
        tree=[("build_species_tree", {
            "joins": ANAS_JOINS, "imap": "data/anas.imap", "out_prefix": "data/sp",
            "migration": "fraterculus->obliqua, obliqua->fraterculus"})],
        before_make=[[("lookup_docs", {"keyword": "wprior"})]], extra={"wprior": "2 10"}),
    "anas_subset_trial": _anas(
        seqfile="data/small.txt", nloci=3,
        before_make=[[("subset_loci", {"seqfile": "data/anas.txt", "out_prefix": "data/small",
                                       "first": 3})]]),
    "anas_chain_settings": _anas(burnin=20000, sampfreq=5, nsample=50000, seed=12345),
    "anas_tree_file": _anas(tree=[("read_species_tree", {
        "path": "tree.nwk", "imap": "data/anas.imap", "out_prefix": "data/sp"})]),
    "tiny_bpp_format": [
        [("check_environment", {})],
        [("build_species_tree", {"joins": "A+B, A_B+C", "imap": "tiny.imap", "out_prefix": "sp"})],
        [("make_control_file", {"analysis": "A00", "seqfile": "tiny.txt", "imapfile": "tiny.imap",
                                "stree_file": "sp.stree", "out": "run.ctl", "nloci": 2})],
        *_finish("run.ctl"),
    ],
    "tiny_fix_broken": [
        [("check_environment", {})],
        [("lint_control_file", {"ctl": "run.ctl"})],
        [("lookup_docs", {"keyword": "nloci"}), ("lookup_docs", {"keyword": "phase"})],
        "The file says 3 loci but the data have 2, and the phase line has 2 digits for 3 "
        "species. May I set nloci to 2 and mark all three species as phased?",
        [("set_keyword", {"ctl": "run.ctl", "keyword": "nloci", "value": "2"})],
        [("set_keyword", {"ctl": "run.ctl", "keyword": "phase", "value": "0 0 0"})],
        *_finish("run.ctl"),
    ],
    "frogs_upgrade": [
        [("check_environment", {})],
        [("upgrade_control_file", {"ctl": "old.ctl"})],
        "Here is the diff of the automatic fixes. May I apply them?",
        [("upgrade_control_file", {"ctl": "old.ctl", "apply": True})],
        [("lookup_docs", {"keyword": "thetaprior"}), ("lookup_docs", {"keyword": "tauprior"})],
        "The old priors are not accepted any more. Which priors do you want?",
        [("set_keyword", {"ctl": "old.ctl", "keyword": "thetaprior", "value": "invgamma 3 0.004"})],
        [("set_keyword", {"ctl": "old.ctl", "keyword": "tauprior", "value": "invgamma 3 0.004"})],
        *_finish("old.ctl"),
    ],
    "off_topic": ["I can only help with setting up BPP analyses, so I can't write that script."],
}
