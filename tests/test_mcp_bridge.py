"""
Tests unitaires pour la passerelle Model Context Protocol (MCP).
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.core import JarvisNode
from jarvismesh.agents import MCPClientBridge


async def test_mcp_bridge():
    print("== Test 1: Création d'un serveur MCP stdio de test ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        server_script = Path(tmp_dir) / "system_mcp_server.py"
        # Script simulant un serveur MCP JSON-RPC standard
        server_code = """
import sys
import json

while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        res = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "system-mcp"}}
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}) + "\\n")
        sys.stdout.flush()
    elif method == "tools/list":
        tools = [
            {"name": "mcp_add", "description": "Additionne 2 entiers", "inputSchema": {"type": "object"}},
            {"name": "mcp_echo", "description": "Echo MCP", "inputSchema": {"type": "object"}}
        ]
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}) + "\\n")
        sys.stdout.flush()
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "mcp_add":
            val = args.get("a", 0) + args.get("b", 0)
            content = [{"type": "text", "text": f"Résultat = {val}"}]
        else:
            content = [{"type": "text", "text": f"Echo: {args.get('text', '')}"}]
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"content": content}}) + "\\n")
        sys.stdout.flush()
"""
        server_script.write_text(server_code, encoding="utf-8")

        print("== Test 2: Démarrage de la passerelle MCPClientBridge ==")
        bridge = MCPClientBridge(f"{sys.executable} {server_script}", prefix="")
        skills = await bridge.start()
        print(f"  -> Compétences MCP importées: {list(skills.keys())}")
        assert "mcp_add" in skills
        assert "mcp_echo" in skills

        print("\n== Test 3: Exécution d'une compétence MCP via JarvisNode ==")
        node = JarvisNode("mcp-node", 9501, skills=skills)
        await node.start(enable_zeroconf=False)

        resp = await node.delegate("mcp_add", {"a": 25, "b": 17})
        print(f"  -> mcp_add: ok={resp.ok} result={resp.result}")
        assert resp.ok is True
        assert "42" in resp.result["content"]

        resp_echo = await node.delegate("mcp_echo", {"text": "JarvisMesh MCP Native"})
        print(f"  -> mcp_echo: ok={resp_echo.ok} result={resp_echo.result}")
        assert resp_echo.ok is True
        assert "Echo: JarvisMesh MCP Native" in resp_echo.result["content"]

        await node.stop()
        await bridge.stop()

    print("\nTous les tests de la passerelle MCP sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_mcp_bridge())
