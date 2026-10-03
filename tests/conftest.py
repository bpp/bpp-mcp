import pytest


@pytest.fixture(autouse=True)
def _isolated_install_home(tmp_path_factory, monkeypatch):
    """Keep tests away from any real `bpp-mcp install-tools` folder."""
    monkeypatch.setenv("BPP_MCP_HOME", str(tmp_path_factory.mktemp("bpp-mcp-home")))
