"""
CLI JarvisMesh.

Exemples :
    # 1. Génère une identité Ed25519
    python -m jarvismesh.cli keygen --out node_id.key

    # 2. Démarre un nœud avec MLX, RAG et identité Ed25519
    python -m jarvismesh.cli start --name mac-selim --port 8765 --identity-file node_id.key --rag-dir ./knowledge

    # 3. Démarre le serveur de relais WAN
    python -m jarvismesh.cli relay --port 9000

    # 4. Démarre le Dashboard Web
    python -m jarvismesh.cli dashboard --port 8080

    # 5. Connecte un serveur d'outils MCP
    python -m jarvismesh.cli start --name mac-mcp --port 8767 --mcp-command "python my_mcp_server.py"

    # 6. Exécute un workflow multi-agents
    python -m jarvismesh.cli workflow pipeline.json --input '{"topic": "informatique quantique"}'
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from ..core.node import JarvisNode
from ..core.wan import MeshRelayServer, WANPeerManager, detect_tailscale_ip
from ..security.crypto import NodeIdentity, TrustStore
from ..engines.mlx_engine import (
    DEFAULT_MODEL_NAME,
    MLXModelManager,
    mlx_health_extra,
    _HAS_MLX,
)
from ..memory.vector import SQLiteVectorStore, ConversationMemory
from ..memory.rag import LocalVectorStore, RAGManager
from ..agents.agent import AutonomousAgent, AgentStep
from ..agents.orchestrator import Workflow
from ..agents.mcp_bridge import MCPClientBridge, MCPServerBridge
from ..skills.registry import SkillRegistry, DEFAULT_SKILLS, DEFAULT_SCHEMAS, BUILTIN_SKILLS
from .daemon import ServiceManager
from .dashboard import run_dashboard


def _resolve_psk(args) -> str | None:
    return getattr(args, "psk", None) or os.environ.get("JARVISMESH_PSK")


async def run_start(args):
    psk = _resolve_psk(args)

    # Identité Ed25519 & TrustStore
    identity = None
    if getattr(args, "identity_file", None):
        id_path = Path(args.identity_file)
        if id_path.is_file():
            identity = NodeIdentity.load(id_path)
            print(f"[{args.name}] 🔑 Identité Ed25519 chargée (ID: {identity.node_id})")
        else:
            identity = NodeIdentity.generate()
            identity.save(id_path)
            print(f"[{args.name}] 🔑 Nouvelle identité Ed25519 générée et sauvegardée dans {id_path}")

    trust_store = None
    if getattr(args, "authorized_keys", None):
        ts_path = Path(args.authorized_keys)
        trust_store = TrustStore.load(ts_path)
        print(f"[{args.name}] 🛡️ TrustStore chargé ({len(trust_store._authorized)} clé(s) autorisée(s))")

    # Modèle MLX
    model_name = getattr(args, "model", None) or os.environ.get("JARVISMESH_MODEL")
    if model_name and _HAS_MLX:
        print(f"[{args.name}] Préchargement du modèle MLX: {model_name}...")
        MLXModelManager.get_model(model_name)

    registry = SkillRegistry("node")
    registry.register_dict(DEFAULT_SKILLS, DEFAULT_SCHEMAS)

    # Chargement dynamique de compétences (.py)
    skills_dir = getattr(args, "skills_dir", None)
    if skills_dir and Path(skills_dir).is_dir():
        loaded = registry.load_from_directory(skills_dir)
        print(f"[{args.name}] 🧩 {loaded} compétence(s) personnalisée(s) chargée(s) depuis {skills_dir}")

    # RAG local
    rag_dir = getattr(args, "rag_dir", None)
    if rag_dir:
        rag_path = Path(rag_dir) / "vector_store.json"
        vstore = LocalVectorStore(rag_path)
        # On attache le LLM MLX pour 'rag_ask'
        rag_mgr = RAGManager(vstore, llm_fn=DEFAULT_SKILLS.get("llm"))
        registry.register_dict(rag_mgr.get_skills())
        print(f"[{args.name}] 🧠 Moteur RAG & mémoire locale activés ({len(vstore._documents)} doc(s))")

    # MCP Client Bridge
    mcp_bridge = None
    mcp_cmd = getattr(args, "mcp_command", None)
    if mcp_cmd:
        print(f"[{args.name}] 🔌 Connexion au serveur MCP: '{mcp_cmd}'...")
        mcp_bridge = MCPClientBridge(mcp_cmd)
        mcp_skills = await mcp_bridge.start()
        registry.register_dict(mcp_skills)
        print(f"[{args.name}] 🔌 {len(mcp_skills)} outil(s) MCP importé(s) comme compétences")

    # Détection Tailscale
    adv_ip = getattr(args, "advertise_ip", None) or detect_tailscale_ip()

    node = JarvisNode(
        name=args.name,
        port=args.port,
        skills=registry.skills,
        advertise_ip=adv_ip,
        psk=psk,
        identity=identity,
        trust_store=trust_store,
        schemas=registry.schemas if not args.no_validation else None,
        health_extra=mlx_health_extra,
    )
    await node.start(enable_zeroconf=not args.no_zeroconf)

    # Synchronisation WAN Relay
    wan_mgr = None
    relay_url = getattr(args, "relay_url", None)
    if relay_url:
        wan_mgr = WANPeerManager(node, relay_url=relay_url)
        await wan_mgr.start()
        print(f"[{node.name}] 🌐 Connecté au serveur relais WAN: {relay_url}")

    auth_info = "Ed25519 (Asymétrique)" if trust_store or identity else ("PSK/HMAC" if psk else "Ouvert")
    mlx_status = f"activé ({MLXModelManager.loaded_model_name() or DEFAULT_MODEL_NAME})" if _HAS_MLX else "non disponible"
    print(f"[{node.name}] en écoute sur {node.advertise_ip}:{node.port} "
          f"— compétences ({len(node.skills)}): {', '.join(sorted(node.skills.keys()))}")
    print(f"[{node.name}] authentification: {auth_info}")
    print(f"[{node.name}] moteur MLX: {mlx_status}")
    print("Ctrl+C pour arrêter.")

    try:
        while True:
            await asyncio.sleep(5)
            if node.peers:
                print(f"[{node.name}] pairs visibles: {list(node.peers.keys())}")
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if wan_mgr:
            await wan_mgr.stop()
        if mcp_bridge:
            await mcp_bridge.stop()
        await node.stop()


async def run_ask(args):
    psk = _resolve_psk(args)
    identity = None
    if getattr(args, "identity_file", None):
        id_path = Path(args.identity_file)
        if id_path.is_file():
            identity = NodeIdentity.load(id_path)

    node = JarvisNode(name="cli-client", port=args.port or 0, skills={}, psk=psk, identity=identity)
    await node.start(enable_zeroconf=True)

    target = args.peer
    max_wait = args.timeout
    waited = 0.0
    step = 0.15
    while waited < max_wait:
        if target and target in node.peers:
            break
        if not target and node.find_peers_for_skill(args.skill):
            break
        await asyncio.sleep(step)
        waited += step

    payload = json.loads(args.payload) if args.payload else {}

    if args.stream:
        def on_chunk(chunk):
            print(chunk, end="", flush=True)
        resp = await node.delegate_stream(args.skill, payload, on_chunk, peer_name=args.peer)
        print()
    else:
        resp = await node.delegate(args.skill, payload, peer_name=args.peer)

    await node.stop()
    if resp.ok:
        if not args.stream:
            print(f"OK (traité par {resp.handled_by}): {json.dumps(resp.result, ensure_ascii=False)}")
    else:
        print(f"ERREUR: {resp.error}", file=sys.stderr)
        sys.exit(1)


async def run_dashboard_cmd(args):
    psk = _resolve_psk(args)
    node_name = args.name or "dashboard-node"
    node_port = args.node_port or 8765

    model_name = getattr(args, "model", None) or os.environ.get("JARVISMESH_MODEL")
    if model_name and _HAS_MLX:
        print(f"[{node_name}] Préchargement du modèle MLX: {model_name}...")
        MLXModelManager.get_model(model_name)

    registry = SkillRegistry("dashboard")
    registry.register_dict(DEFAULT_SKILLS, DEFAULT_SCHEMAS)
    if args.skills_dir and Path(args.skills_dir).is_dir():
        registry.load_from_directory(args.skills_dir)

    node = JarvisNode(
        name=node_name,
        port=node_port,
        skills=registry.skills,
        psk=psk,
        schemas=registry.schemas,
        health_extra=mlx_health_extra,
    )
    await node.start(enable_zeroconf=not args.no_zeroconf)
    print(f"[{node.name}] Nœud mesh démarré sur {node.advertise_ip}:{node.port}")

    try:
        await run_dashboard(node, host=args.host, port=args.port)
    finally:
        await node.stop()


async def run_workflow_cmd(args):
    psk = _resolve_psk(args)
    node = JarvisNode(name="workflow-runner", port=args.port or 0, skills=DEFAULT_SKILLS, psk=psk)
    await node.start(enable_zeroconf=True)

    await asyncio.sleep(1.0)
    wf_file = Path(args.workflow_file)
    if not wf_file.is_file():
        print(f"ERREUR: fichier de workflow introuvable: {wf_file}", file=sys.stderr)
        await node.stop()
        sys.exit(1)

    wf_data = json.loads(wf_file.read_text("utf-8"))
    workflow = Workflow.from_dict(wf_data)
    initial_input = json.loads(args.input) if args.input else {}
    print(f"▶ Lancement du workflow: '{workflow.name}'...")

    def on_progress(event_type, step_name, data):
        if event_type == "step_start":
            print(f"  ⏳ [{step_name}] Début ({data.get('skill')})...")
        elif event_type == "step_done":
            print(f"  ✅ [{step_name}] Terminé en {data.get('duration_sec', 0):.2f}s via {data.get('handled_by')}")
        elif event_type == "step_error":
            print(f"  ❌ [{step_name}] Erreur: {data.get('error')}", file=sys.stderr)

    result = await workflow.run(node, initial_input=initial_input, on_progress=on_progress)
    await node.stop()

    print(f"\n--- Résultat du Workflow (Durée: {result.duration_sec:.2f}s, Statut: {'OK' if result.ok else 'ÉCHEC'}) ---")
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    if not result.ok:
        sys.exit(1)


def run_keygen(args):
    identity = NodeIdentity.generate()
    out_path = Path(args.out).resolve()
    identity.save(out_path)
    print(f"🔑 Nouvelle identité Ed25519 générée avec succès !")
    print(f"  • Clé privée enregistrée dans : {out_path}")
    print(f"  • Node ID                      : {identity.node_id}")
    print(f"  • Clé Publique (Hex)           : {identity.public_key_hex}")

    if args.add_to:
        ts_path = Path(args.add_to).resolve()
        trust_store = TrustStore.load(ts_path)
        trust_store.add_key(identity.public_key_hex, peer_name=args.name or identity.node_id)
        trust_store.save(ts_path)
        print(f"  • Clé publique ajoutée au TrustStore : {ts_path}")


async def run_relay_cmd(args):
    server = MeshRelayServer(host=args.host, port=args.port)
    await server.start()
    print(f"🌐 Serveur Relais WAN JarvisMesh démarré sur {args.host}:{args.port}")
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await server.stop()


async def run_mcp_server_cmd(args):
    node = JarvisNode(name=args.name or "mcp-mesh-gateway", port=0, skills=DEFAULT_SKILLS)
    await node.start(enable_zeroconf=True)
    bridge = MCPServerBridge(node)
    try:
        await bridge.run_stdio()
    finally:
        await node.stop()


async def run_agent_cmd(args):
    node = JarvisNode(
        name="cli-react-agent",
        port=args.port or 0,
        skills=DEFAULT_SKILLS,
        psk=_resolve_psk(args),
    )
    await node.start(enable_zeroconf=not args.no_zeroconf)
    print(f"🤖 Initialisation de l'Agent Autonome ReAct sur {node.name}...")
    
    agent = AutonomousAgent(
        node=node,
        max_steps=args.max_steps,
        model=args.model,
        llm_skill=args.llm_skill or "llm",
    )

    def on_step(step: AgentStep):
        print(f"\n🧠 [Étape {step.step_number}]")
        if step.thought:
            print(f"   Thought: {step.thought}")
        if step.action_skill:
            print(f"   Action : {step.action_skill}({json.dumps(step.action_payload, ensure_ascii=False)})")
            if step.handled_by:
                print(f"   Délégué à: {step.handled_by}")
        if step.observation is not None:
            print(f"   Observation: {step.observation}")
        if step.error:
            print(f"   ⚠️ Erreur: {step.error}")

    try:
        trace = await agent.run(args.objective, on_step=on_step)
        print("\n" + "=" * 60)
        if trace.ok:
            print(f"🎯 RÉPONSE FINALE ({trace.total_duration_sec:.2f}s) :\n")
            print(trace.final_answer)
        else:
            print(f"❌ Échec de l'objectif: {trace.error}")
        print("=" * 60)
    finally:
        await node.stop()


def run_service_cmd(args):
    mgr = ServiceManager()
    action = args.action

    if action == "install":
        path = mgr.install(name=args.name, port=args.port)
        print(f"✅ Service JarvisMesh installé avec succès : {path}")
        print(f"   Pour le démarrer : jarvismesh service start")
    elif action == "uninstall":
        ok = mgr.uninstall()
        print("🗑️ Service désinstallé." if ok else "⚠️ Fichier de service introuvable.")
    elif action == "start":
        ok, out = mgr.start()
        print("🚀 Service démarré." if ok else f"❌ Erreur de démarrage: {out}")
    elif action == "stop":
        ok, out = mgr.stop()
        print("🛑 Service arrêté." if ok else f"❌ Erreur d'arrêt: {out}")
    elif action == "status":
        st = mgr.status()
        print(f"📊 Statut du Service JarvisMesh ({st['os']}):")
        print(f"   Installé : {'Oui' if st['installed'] else 'Non'} ({st['path']})")
        print(f"   Actif    : {'🟢 En cours' if st['running'] else '🔴 Arrêté'}")
        print(f"   Logs     : {st['logs_dir']}")


def run_memory_cmd(args):
    store = SQLiteVectorStore(args.db_path or (str(Path.home() / ".jarvismesh" / "memory.db")))
    action = args.action

    if action == "store":
        doc_id = store.add_document(args.text, metadata={"source": "cli"})
        print(f"💾 Document mémorisé avec succès. ID = {doc_id}")
    elif action == "search":
        results = store.search(args.query, top_k=args.top_k)
        print(f"🔍 Résultats pour '{args.query}' ({len(results)} trouvés) :")
        for idx, r in enumerate(results, 1):
            print(f"  {idx}. [Score {r['score']:.4f}] {r['text']}")
    elif action == "count":
        print(f"📚 Total documents en mémoire : {store.count()}")
    store.close()


def main():
    parser = argparse.ArgumentParser(prog="jarvismesh")
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. keygen
    p_key = sub.add_parser("keygen", help="Génère une identité cryptographique Ed25519")
    p_key.add_argument("--out", default="node_identity.key", help="Fichier de destination de la clé privée")
    p_key.add_argument("--add-to", default=None, help="Fichier TrustStore JSON où ajouter la clé publique")
    p_key.add_argument("--name", default=None, help="Nom associé à la clé publique")

    # 2. start
    p_start = sub.add_parser("start", help="Démarre un noeud JarvisMesh")
    p_start.add_argument("--name", required=True)
    p_start.add_argument("--port", type=int, required=True)
    p_start.add_argument("--skills-dir", default=None, help="Dossier de compétences (.py)")
    p_start.add_argument("--identity-file", default=None, help="Fichier d'identité Ed25519")
    p_start.add_argument("--authorized-keys", default=None, help="Fichier TrustStore JSON des pairs autorisés")
    p_start.add_argument("--rag-dir", default=None, help="Dossier de mémoire et documents RAG")
    p_start.add_argument("--mcp-command", default=None, help="Commande pour démarrer un serveur MCP stdio")
    p_start.add_argument("--relay-url", default=None, help="URL d'un serveur relais WAN (ex: http://relay:9000)")
    p_start.add_argument("--no-zeroconf", action="store_true", help="Désactive la découverte mDNS")
    p_start.add_argument("--psk", default=None, help="Clé pré-partagée")
    p_start.add_argument("--no-validation", action="store_true", help="Désactive la validation Pydantic")
    p_start.add_argument("--model", default=None, help="Modèle HuggingFace/MLX")

    # 3. ask
    p_ask = sub.add_parser("ask", help="Délègue une tâche à un pair sur le réseau")
    p_ask.add_argument("skill")
    p_ask.add_argument("payload", nargs="?", default="{}")
    p_ask.add_argument("--peer", default=None, help="Nom du pair ciblé")
    p_ask.add_argument("--port", type=int, default=0)
    p_ask.add_argument("--timeout", type=float, default=5.0)
    p_ask.add_argument("--stream", action="store_true", help="Affiche la réponse en streaming")
    p_ask.add_argument("--identity-file", default=None, help="Fichier d'identité Ed25519")
    p_ask.add_argument("--psk", default=None, help="Clé pré-partagée")

    # 4. dashboard
    p_dash = sub.add_parser("dashboard", help="Démarre le Dashboard Web de supervision")
    p_dash.add_argument("--port", type=int, default=8080)
    p_dash.add_argument("--host", default="0.0.0.0")
    p_dash.add_argument("--node-port", type=int, default=8765)
    p_dash.add_argument("--name", default="mac-dashboard")
    p_dash.add_argument("--skills-dir", default=None)
    p_dash.add_argument("--model", default=None)
    p_dash.add_argument("--psk", default=None)
    p_dash.add_argument("--no-zeroconf", action="store_true")

    # 5. workflow
    p_wf = sub.add_parser("workflow", help="Exécute un pipeline multi-agents")
    p_wf.add_argument("workflow_file", help="Chemin du fichier de workflow JSON")
    p_wf.add_argument("--input", default="{}")
    p_wf.add_argument("--port", type=int, default=0)
    p_wf.add_argument("--psk", default=None)

    # 6. relay
    p_relay = sub.add_parser("relay", help="Démarre un serveur de relais / rendez-vous WAN")
    p_relay.add_argument("--port", type=int, default=9000)
    p_relay.add_argument("--host", default="0.0.0.0")

    # 7. mcp-server
    p_mcp = sub.add_parser("mcp-server", help="Exécute JarvisMesh en tant que serveur d'outils MCP stdio")
    p_mcp.add_argument("--name", default="jarvismesh-mcp")

    # 8. agent (ReAct autonome)
    p_agent = sub.add_parser("agent", help="Lance un agent autonome ReAct pour résoudre un objectif")
    p_agent.add_argument("objective", help="Objectif en langage naturel")
    p_agent.add_argument("--max-steps", type=int, default=8)
    p_agent.add_argument("--model", default=None)
    p_agent.add_argument("--llm-skill", default="llm")
    p_agent.add_argument("--port", type=int, default=0)
    p_agent.add_argument("--psk", default=None)
    p_agent.add_argument("--no-zeroconf", action="store_true")

    # 9. service (launchd / systemd)
    p_srv = sub.add_parser("service", help="Gère le service démon d'arrière-plan (launchd / systemd)")
    p_srv.add_argument("action", choices=["install", "uninstall", "start", "stop", "status"])
    p_srv.add_argument("--name", default="mac-agent")
    p_srv.add_argument("--port", type=int, default=8765)

    # 10. memory (SQLite & vecteurs)
    p_mem = sub.add_parser("memory", help="Interroge et gère la mémoire persistante SQLite")
    p_mem.add_argument("action", choices=["store", "search", "count"])
    p_mem.add_argument("--text", default="", help="Texte à stocker")
    p_mem.add_argument("--query", default="", help="Requête de recherche sémantique")
    p_mem.add_argument("--top-k", type=int, default=5)
    p_mem.add_argument("--db-path", default=None)

    args = parser.parse_args()
    if args.command == "keygen":
        run_keygen(args)
    elif args.command == "start":
        asyncio.run(run_start(args))
    elif args.command == "ask":
        asyncio.run(run_ask(args))
    elif args.command == "dashboard":
        asyncio.run(run_dashboard_cmd(args))
    elif args.command == "workflow":
        asyncio.run(run_workflow_cmd(args))
    elif args.command == "relay":
        asyncio.run(run_relay_cmd(args))
    elif args.command == "mcp-server":
        asyncio.run(run_mcp_server_cmd(args))
    elif args.command == "agent":
        asyncio.run(run_agent_cmd(args))
    elif args.command == "service":
        run_service_cmd(args)
    elif args.command == "memory":
        run_memory_cmd(args)


if __name__ == "__main__":
    main()

