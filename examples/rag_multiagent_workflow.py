"""
Démonstration d'un Pipeline Multi-Agents RAG + Inférence MLX locale + Analyse Parallèle.

Ce script :
1. Initialise une base documentaire vectorielle locale (RAG).
2. Lance un nœud JarvisNode sur le réseau local.
3. Exécute un workflow DAG orchestré en 3 étapes :
   - Étape 1 : Recherche sémantique par similarité cosinus (rag_search)
   - Étape 2 : Rédaction et synthèse augmentée par le modèle local MLX (llm)
   - Étape 3 (Parallèle) : Analyse lexicale (wordcount) + Inversion de contrôle (reverse)
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Permet l'exécution directe du script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh import JarvisNode, Workflow, WorkflowStep, LocalVectorStore, RAGManager
from jarvismesh.skills import BUILTIN_SKILLS, SkillRegistry
from jarvismesh.mlx_engine import mlx_health_extra


async def run_rag_workflow():
    print("=" * 70)
    print("🌐 JarvisMesh — Pipeline Multi-Agents RAG + MLX + Analyse Parallèle")
    print("=" * 70)

    # 1. Préparation de la base vectorielle locale (RAG)
    db_file = Path("./knowledge/vector_store.json")
    vstore = LocalVectorStore(db_file)

    documents = [
        {
            "id": "mesh_core",
            "text": (
                "JarvisMesh est un protocole d'agents IA souverain et pair-à-pair (P2P). "
                "Il utilise mDNS/Zeroconf pour l'auto-découverte sur le réseau local et des "
                "WebSockets multiplexés pour router des tâches de manière non-bloquante."
            ),
            "metadata": {"category": "architecture", "author": "Jarvis Team"}
        },
        {
            "id": "mlx_engine",
            "text": (
                "Le moteur MLX-LM permet d'exécuter des modèles de langage ouverts (Qwen, Llama, GLM) "
                "directement sur le GPU Metal et la mémoire unifiée des puces Apple Silicon sans cloud. "
                "Il supporte le streaming continu et remonte la mémoire VRAM active et maximale."
            ),
            "metadata": {"category": "ai", "hardware": "Apple Silicon"}
        },
        {
            "id": "security_ed25519",
            "text": (
                "La sécurité du protocole repose sur la cryptographie asymétrique Ed25519. Chaque nœud "
                "possède une clé privée et signe ses requêtes. Un TrustStore gère la liste blanche "
                "des clés publiques et permet la révocation instantanée d'un agent compromis."
            ),
            "metadata": {"category": "security", "algo": "Ed25519"}
        },
    ]

    indexed_count = vstore.add_documents(documents)
    print(f"\n📚 [1/3] Base RAG initialisée avec {indexed_count} documents de référence.")

    # 2. Enregistrement des compétences sur le nœud
    registry = SkillRegistry("agent-selim")
    registry.register_dict(BUILTIN_SKILLS)
    rag_mgr = RAGManager(vstore, llm_fn=BUILTIN_SKILLS.get("llm"))
    registry.register_dict(rag_mgr.get_skills())

    node = JarvisNode(
        name="agent-selim",
        port=8770,
        skills=registry.skills,
        health_extra=mlx_health_extra,
    )
    await node.start(enable_zeroconf=False)
    print(f"🤖 [2/3] Nœud JarvisMesh actif sur le port {node.port} ({len(node.skills)} compétences enregistrées).")

    # 3. Construction du Workflow Multi-Agents (DAG)
    wf = Workflow("Pipeline RAG Documentaire & Synthèse IA")

    # Étape 1 : Recherche des sources documentaires pertinentes
    wf.add_step(
        name="recherche_rag",
        skill="rag_search",
        payload={"query": "{input.sujet}", "top_k": 2},
    )

    # Étape 2 : Rédaction augmentée par le modèle MLX
    wf.add_step(
        name="synthese_llm",
        skill="llm",
        payload={
            "prompt": (
                "Tu es un expert JarvisMesh. En te basant sur le sujet '{input.sujet}', "
                "rédige un résumé clair en deux phrases courtes."
            ),
            "max_tokens": 150,
            "temperature": 0.3,
        }
    )

    # Étape 3 : Traitement parallèle de l'analyse lexicale et du formatage
    wf.add_parallel_steps([
        WorkflowStep(
            name="comptage_mots",
            skill="wordcount",
            payload={"text": "{steps.synthese_llm.result.response}"}
        ),
        WorkflowStep(
            name="inversion_controle",
            skill="reverse",
            payload={"text": "{steps.synthese_llm.result.response}"}
        ),
    ])

    print(f"\n🚀 [3/3] Exécution du workflow multi-agents : '{wf.name}'...")

    def progress_callback(event, step, data):
        if event == "step_start":
            print(f"  ⏳ Étape en cours : [{step}] (Compétence : {data.get('skill')})")
        elif event == "step_done":
            duration = data.get("duration_sec", 0.0)
            handler = data.get("handled_by")
            print(f"  ✅ Étape terminée  : [{step}] en {duration:.2f}s (Traité par : {handler})")

    start_time = time.time()
    result = await wf.run(
        node=node,
        initial_input={"sujet": "Sécurité Ed25519 et accélération MLX sur Apple Silicon"},
        on_progress=progress_callback,
    )
    total_duration = time.time() - start_time

    print("\n" + "=" * 70)
    print(f"🎉 RÉSULTATS DU WORKFLOW MULTI-AGENTS (Durée totale: {total_duration:.2f}s, Statut: {'OK' if result.ok else 'ERREUR'})")
    print("=" * 70)

    print("\n📄 1. Synthèse rédigée par le LLM local (MLX) :")
    print(f"   \"{result.step_results['synthese_llm'].result.get('response')}\"")

    print("\n📊 2. Analyse lexicale (Exécutée en parallèle) :")
    wc = result.step_results['comptage_mots'].result
    print(f"   • Mots : {wc.get('words')} | Caractères : {wc.get('chars')}")

    print("\n🔍 3. Documents sources retrouvés par le RAG :")
    for doc in result.step_results['recherche_rag'].result.get("results", []):
        print(f"   • [{doc['id']}] (score: {doc['score']}) : {doc['text'][:80]}...")

    await node.stop()


if __name__ == "__main__":
    asyncio.run(run_rag_workflow())
