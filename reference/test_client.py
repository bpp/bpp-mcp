"""End-to-end check: drive bpp-mcp over stdio exactly as a frontier host would."""
import asyncio, json, os, shutil, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJ = sys.argv[1]
EX = "/home/claude/bpp-seqs/examples/01-fasta-anastrepha"


def show(name, res):
    txt = res.content[0].text if res.content else ""
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        d = txt
    print(f"\n### {name}  (isError={res.is_error})")
    print(json.dumps(d, indent=1)[:900] if not isinstance(d, str) else d[:900])
    return d


async def main():
    shutil.rmtree(PROJ, ignore_errors=True)
    shutil.copytree(EX, PROJ)
    params = StdioServerParameters(command=sys.executable, args=["-m", "bpp_mcp.server"],
                                   env={**os.environ, "BPP_MCP_ROOT": PROJ},
                                   cwd="/home/claude/bpp-mcp")
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("server instructions:", (init.instructions or "")[:120], "...")
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            loci = sorted(f"loci/{f}" for f in os.listdir(f"{PROJ}/loci"))

            show("inspect_data", await s.call_tool("inspect_data", {"files": loci, "imap": "imap.txt"}))
            d = show("convert_data", await s.call_tool("convert_data", {"files": loci, "imap": "imap.txt", "out_prefix": "anas"}))
            nloci = d["report"]["summary"]["n_loci_passed"]
            show("build_species_tree", await s.call_tool("build_species_tree", {
                "joins": "fraterculus+obliqua, distincta+fraterculus_obliqua, "
                         "suspensa+distincta_fraterculus_obliqua, "
                         "turpiniae+distincta_fraterculus_obliqua_suspensa",
                "imap": "anas.imap", "out_prefix": "sp"}))
            show("make_control_file", await s.call_tool("make_control_file", {
                "analysis": "A10", "seqfile": "anas.txt", "imapfile": "anas.imap",
                "stree_file": "sp.stree", "out": "a10.ctl", "nloci": nloci, "jobname": "a10"}))
            show("lint_control_file", await s.call_tool("lint_control_file", {"ctl": "a10.ctl"}))
            show("lookup_docs", await s.call_tool("lookup_docs", {"query": "speciesdelimitation"}))
            show("smoke_test", await s.call_tool("smoke_test", {"ctl": "a10.ctl"}))
            show("sandbox escape attempt", await s.call_tool("lint_control_file", {"ctl": "../../etc/passwd"}))


asyncio.run(main())
