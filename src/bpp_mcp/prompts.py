"""Prompts: ready-made openings for the three common jobs.

They only order the tool calls; every BPP fact still comes from the tools.
"""
from __future__ import annotations


def novice_setup(data: str = "") -> str:
    """Go from raw data to a tested BPP control file, step by step."""
    about = f"My data: {data}\n\n" if data.strip() else ""
    return (
        f"{about}I am new to BPP. Help me set up an analysis, from my data files to a control "
        "file that has passed a test run.\n\n"
        "Work through these steps in order, one at a time, and explain each in plain language:\n"
        "1. check_environment. If it is not ready, help me fix that first.\n"
        "2. Ask me what data I have and what I want to learn, then inspect_data.\n"
        "3. convert_data. Tell me how many loci passed and why any were dropped.\n"
        "4. Ask me for the species tree or guide tree, then build_species_tree (or "
        "read_species_tree if I have a tree file). Show me the diagram and wait for me to "
        "confirm it.\n"
        "5. Explain the analysis types and the other choices that are mine to make, quoting "
        "the manual (lookup_docs), and ask me to choose. Do not choose for me.\n"
        "6. make_control_file, then lint_control_file until server.status is \"valid\", "
        "changing things with set_keyword.\n"
        "7. smoke_test.\n"
        "8. run_command, and tell me how to start the full analysis myself.\n\n"
        "Do not say the file is ready before the lint is valid and the test run succeeded."
    )


def upgrade_old_file(ctl: str) -> str:
    """Bring a control file written for an older BPP up to date."""
    return (
        f"My control file `{ctl}` was written for an older version of BPP. Help me bring it "
        "up to date.\n\n"
        "1. check_environment.\n"
        f"2. upgrade_control_file on `{ctl}` with apply=false. Show me the diff and explain "
        "each change, using explain_diagnostic and lookup_docs.\n"
        "3. Ask me before changing anything. If I agree, call it again with apply=true (the "
        "original is kept as a .bak file).\n"
        "4. For each error that remains, explain it, ask me what I want where the choice is "
        "scientific, and fix it with set_keyword. Repeat until server.status is \"valid\".\n"
        "5. smoke_test, then run_command.\n\n"
        "Do not edit the file by hand, and quote the manual for any syntax you state."
    )


def check_my_ctl(ctl: str) -> str:
    """Review an existing control file without changing it."""
    return (
        f"Please review my BPP control file `{ctl}`. Do not change it unless I ask.\n\n"
        "1. check_environment.\n"
        f"2. lint_control_file on `{ctl}`. Explain every error and warning in plain language "
        "(explain_diagnostic, lookup_docs), including report.prior_check and "
        "server.data_checks.\n"
        "3. If server.status is \"valid\", run smoke_test and tell me the result.\n"
        "4. Summarise what the file sets up (analysis type, data, tree, priors, chain length), "
        "quoting the manual for what each setting means, and list anything I should "
        "reconsider.\n\n"
        "If I then ask for changes, make them with set_keyword and lint again."
    )
