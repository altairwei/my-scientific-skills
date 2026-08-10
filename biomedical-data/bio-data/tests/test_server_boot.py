# biomedical-data/bio-data/tests/test_server_boot.py
def test_server_imports_cleanly():
    import server
    assert server.mcp is not None  # MCPServer constructed; decorators ran
