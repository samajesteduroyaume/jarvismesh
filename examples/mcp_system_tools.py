"""
Passerelle Model Context Protocol (MCP) pour JarvisMesh avec outils système réels.

Ce script :
1. Démarre un serveur d'outils MCP standard (JSON-RPC stdio) exposant des outils système réels (system_info, file_reader).
2. Démarre un nœud 'agent-mcp-host' qui connecte ce serveur MCP via MCPClientBridge.
3. Démarre un second nœud 'agent-client' qui découvre et appelle les outils MCP à travers le maillage P2P.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Permet l'exécution directe du script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh import JarvisNode, MCPClientBridge


async def run_mcp_system():
    print("=" * 70)
    print("🔌 JarvisMesh — Passerelle MCP Réelle (Model Context Protocol)")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmp_dir:
        mcp_server_script = Path(tmp_dir) / "system_mcp_server.py"

        # Code du serveur MCP simulant des outils système réels
        mcp_code = """
import sys
import json
import platform
import os

while True:
    line = sys.stdin.readline()
    if not line:
        break
    req = json.loads(line)
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        res = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "system-inspector-mcp", "version": "1.0.0"}
        }
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": res}) + "\\n")
        sys.stdout.flush()

    elif method == "tools/list":
        tools = [
            {
                "name": "system_info",
                "description": "Retourne les informations matérielles et OS de la machine",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "file_reader",
                "description": "Lit le contenu d'un fichier local de manière sécurisée",
                "inputSchema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            }
        ]
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}) + "\\n")
        sys.stdout.flush()

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        if tool_name == "system_info":
            info = {
                "os": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
            }
            content = [{"type": "text", "text": json.dumps(info, indent=2)}]
        elif tool_name == "file_reader":
            p = args.get("path", "")
            if os.path.exists(p):
                content = [{"type": "text", "text": open(p, "r").read()[:500]}]
            else:
                content = [{"type": "text", "text": f"Erreur: fichier '{p}' introuvable"}]
        else:
            content = [{"type": "text", "text": "Outil inconnu"}]

        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"content": content}}) + "\\n")
        sys.stdout.flush()
"""
        mcp_server_script.write_text(mcp_code, encoding="utf-8")

        # 1. Démarrage du pont MCP
        print(f"\n📦 [1/3] Démarrage du sous-processus MCP stdio...")
        bridge = MCPClientBridge(f"{sys.executable} {mcp_server_script}", prefix="mcp_")
        mcp_skills = await bridge.start()
        print(f"  -> Outils MCP découverts & transformés en compétences : {list(mcp_skills.keys())}")

        # 2. Enregistrement sur le nœud serveur
        host_node = JarvisNode("mcp-worker-node", port=8775, skills=mcp_skills)
        await host_node.start(enable_zeroconf=False)
        print(f"🤖 [2/3] Nœud hébergeur MCP 'mcp-worker-node' démarré sur le port {host_node.port}.")

        # 3. Nœud client distant qui découvre et consomme les outils MCP
        client_node = JarvisNode("client-orchestrator", port=8776, skills={})
        await client_node.start(enable_zeroconf=False)
        client_node.add_static_peer("mcp-worker-node", "127.0.0.1", 8775, skills=list(mcp_skills.keys()))
        print(f"💻 [3/3] Nœud client connecté au maillage.")

        # 4. Appel de l'outil MCP 'mcp_system_info' depuis le client
        print("\n🚀 Exécution 1 : Appel distribué de l'outil MCP 'mcp_system_info'...")
        resp1 = await client_node.delegate("mcp_system_info", {})
        print(f"  ✅ Réponse reçue de '{resp1.handled_by}' :")
        print(resp1.result.get("content"))

        # 5. Appel de l'outil MCP 'mcp_file_reader' depuis le client
        print("\n🚀 Exécution 2 : Appel distribué de l'outil MCP 'mcp_file_reader'...")
        resp2 = await client_node.delegate("mcp_file_reader", {"path": "pyproject.toml"})
        print(f"  ✅ Extrait du fichier lu à distance via MCP :")
        print(resp2.result.get("content")[:200] + "...")

        await client_node.stop()
        await host_node.stop()
        await bridge.stop()

    print("\n" + "=" * 70)
    print("🎉 DÉMONSTRATION DE LA PASSERELLE MCP TERMINÉE AVEC SUCCÈS !")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_mcp_system())
