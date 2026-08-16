# 🌐 JarvisMesh — Protocole d'Agents IA Locaux, Souverain & Distribué

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![MLX: Metal](https://img.shields.io/badge/MLX-Apple%20Silicon-purple.svg)](https://github.com/ml-explore/mlx)
[![Security: Ed25519](https://img.shields.io/badge/Security-Ed25519%20%2F%20HMAC-green.svg)](#sécurité--authentification-asymétrique-ed25519--hmac)
[![MCP: Supported](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-orange.svg)](#passerelle-mcp-bi-directionnelle)
[![Architecture: P2P & WAN](https://img.shields.io/badge/Architecture-P2P%20%2F%20mDNS%20%2F%20WAN-cyan.svg)](#architecture--principes-fondamentaux)

**JarvisMesh** est un écosystème pair-à-pair (P2P), souverain et extensible pour agents d'intelligence artificielle distribués.

Au lieu que chaque agent dépende d'une API cloud centralisée et propriétaire, les agents tournant sur vos machines (Mac Apple Silicon, serveurs Linux, stations de travail locales ou distantes) :
1. **Se découvrent automatiquement** via mDNS/Zeroconf ou via serveur de relais WAN (Tailscale/VPN).
2. **S'échangent et se délèguent des tâches** via des WebSockets persistants et multiplexés.
3. **Exécutent des modèles de langage locaux (LLM)** accélérés sur GPU Metal (MLX-LM) avec streaming token-par-token.
4. **Coordonnent des pipelines complexes** via un moteur de workflows DAG multi-agents séquentiel et parallèle.
5. **Intègrent l'écosystème MCP (Model Context Protocol)** de manière bi-directionnelle (consommation d'outils MCP et exposition du mesh en tant que serveur MCP).
6. **Partagent une mémoire et une base documentaire sémantique (RAG local distribué)**.
7. **Sécurisent leurs échanges par cryptographie asymétrique Ed25519** avec révocation granulaire sans secret partagé global.
8. **Se supervisent en direct** via un Dashboard Web interactif (Dark Mode, Glassmorphism, télémétrie VRAM GPU).

> **Zéro cloud obligatoire. Zéro serveur centralisé imposé. Zéro clé API externe. Vos données et votre puissance de calcul restent 100% vôtres.**

---

## Sommaire

- [Architecture & Principes Fondamentaux](#architecture--principes-fondamentaux)
- [Installation](#installation)
- [Démarrage Rapide](#démarrage-rapide)
- [Dashboard Web de Supervision](#dashboard-web-de-supervision)
- [Inférence LLM Locale avec MLX-LM](#inférence-llm-locale-avec-mlx-lm)
- [Sécurité : Authentification Asymétrique Ed25519 & HMAC](#sécurité--authentification-asymétrique-ed25519--hmac)
- [Passerelle MCP Bi-directionnelle](#passerelle-mcp-bi-directionnelle)
- [Mémoire Partagée & RAG Local Distribué](#mémoire-partagée--rag-local-distribué)
- [Interconnexion WAN & Relais Multi-Réseaux (Tailscale)](#interconnexion-wan--relais-multi-réseaux-tailscale)
- [Système de Plugins & Décorateur `@skill`](#système-de-plugins--décorateur-skill)
- [Orchestrateur & Pipelines Multi-Agents](#orchestrateur--pipelines-multi-agents)
- [Référence de la CLI](#référence-de-la-cli)
- [Référence de l'API Python](#référence-de-lapi-python)
- [Arborescence du Projet](#arborescence-du-projet)
- [Exécution des Tests](#exécution-des-tests)

---

## Architecture & Principes Fondamentaux

```
 ┌────────────────────────────────────────────────────────────────────────┐
 │                      TOPOLOGIE DISTRIBUÉE (LAN / WAN)                  │
 │                                                                        │
 │   ┌──────────────────┐          mDNS / WAN          ┌────────────────┐ │
 │   │  Nœud "A" (Mac)  │◄────────────────────────────►│ Nœud "B" (GPU) │ │
 │   │  • Orchestrateur │                              │ • llm (MLX)    │ │
 │   │  • RAG Local     │     WebSockets Multiplexés   │ • llm-stream   │ │
 │   │  • MCP Gateway   │◄────────────────────────────►│ • wordcount    │ │
 │   │  • Ed25519 Auth  │                              │ • Ed25519 Auth │ │
 │   └────────┬─────────┘                              └───────┬────────┘ │
 └────────────┼────────────────────────────────────────────────┼──────────┘
              │                                                │
              ▼                                                ▼
    ┌──────────────────┐                             ┌──────────────────┐
    │  Dashboard Web   │                             │  Apple Silicon   │
    │  (Port 8080)     │                             │  (Metal / GPU)   │
    └──────────────────┘                             └──────────────────┘
```

1. **Découverte Hybride** : Découverte locale mDNS (`_jarvismesh._tcp.local.`) et découverte WAN distante via le serveur de relais `MeshRelayServer` ou adresses statiques.
2. **Multiplexage & Connexions Persistantes** : Un seul socket WebSocket partagé par paire de nœuds, gérant des dizaines de requêtes concurrentes sans blocage via `request_id`.
3. **Routage Adaptatif par Charge (`_health`)** : Mesure continue de la VRAM Metal libre, des cœurs CPU et des tâches en cours pour router vers le pair le plus disponible.
4. **Auto-Failover** : Bascule automatique transparente sur le pair suivant en cas de crash ou d'indisponibilité d'un nœud.

---

## Installation

### Prérequis
- **Python 3.10+**
- macOS (Apple Silicon recommandé pour MLX) ou Linux.

```bash
# Installation complète avec MLX, Cryptographie, Validation et Dev
uv pip install -e ".[dev,mlx,validation]"

# Ou via pip standard
pip install -e ".[mlx,validation]" --break-system-packages
```

---

## Démarrage Rapide

### 1. Générer une identité Ed25519 pour le nœud
```bash
python -m jarvismesh.cli keygen --out node_selim.key
```

### 2. Démarrer un nœud IA avec MLX et RAG
```bash
python -m jarvismesh.cli start --name mac-selim --port 8765 \
  --identity-file node_selim.key \
  --model mlx-community/Qwen3.5-4B-MLX-4bit \
  --rag-dir ./knowledge
```

### 3. Déléguer une tâche en streaming
```bash
python -m jarvismesh.cli ask llm-stream '{"prompt": "Résume le protocole JarvisMesh en 3 points"}' --stream
```

---

## Dashboard Web de Supervision

JarvisMesh inclut un serveur HTTP/SSE et une interface Web moderne (Dark Mode, Glassmorphism).

```bash
python -m jarvismesh.cli dashboard --port 8080 --name mac-dashboard
```
Ouvrez **`http://localhost:8080`** :
- **Topologie du Mesh** : Vue dynamique des nœuds connectés, adresses, latences et compétences.
- **Télémétrie GPU Metal** : Jauges de VRAM Active, Pic, Cache et charge CPU en direct.
- **Studio de Streaming** : Playground d'inférence avec calcul du débit en **tokens/seconde**.
- **Runner de Workflows** : Visualisation de l'avancement des pipelines multi-agents.

---

## Inférence LLM Locale avec MLX-LM

Exploitez directement la mémoire unifiée et l'accélération GPU Metal des puces Apple Silicon.

- **Modèle par défaut** : `mlx-community/Qwen3.5-4B-MLX-4bit` (ou tout modèle MLX Hugging Face).
- **Streaming continu** : Compétence `llm-stream` pour affichage token-par-token.
- **Gestion de mémoire** : Modèle maintenu sous forme de singleton avec télémétrie GPU (`metal_active_mb`, `metal_peak_mb`).

```bash
python -m jarvismesh.cli ask llm '{
  "system_prompt": "Tu es un assistant technique expert en réseaux.",
  "prompt": "Comment fonctionne le routage P2P ?",
  "temperature": 0.3
}'
```

---

## Sécurité : Authentification Asymétrique Ed25519 & HMAC

### 1. Mode Asymétrique Ed25519 (Recommandé)
Chaque agent possède sa clé privée. Le nœud récepteur dispose d'un `TrustStore` listant les clés publiques autorisées.
- **Protection anti-rejeu** : Vérification stricte de l'horodatage (`ts`).
- **Révocation instantanée** : La révocation d'une clé publique bloque immédiatement le nœud sans reconfigurer le reste du réseau.

```bash
# Génère une clé et l'ajoute au TrustStore
python -m jarvismesh.cli keygen --out agent_a.key --add-to truststore.json --name agent-a

# Démarre le serveur avec TrustStore
python -m jarvismesh.cli start --name agent-serveur --port 8765 --authorized-keys truststore.json

# Le client s'authentifie avec sa clé privée
python -m jarvismesh.cli ask secret_skill --identity-file agent_a.key
```

### 2. Mode Symétrique PSK (HMAC-SHA256)
Tous les nœuds partagent une variable secrète `JARVISMESH_PSK`.

---

## Passerelle MCP Bi-directionnelle

JarvisMesh s'intègre avec le **Model Context Protocol** d'Anthropic :

### 1. Consommer des outils MCP sur le Mesh (Mode Client)
Connectez n'importe quel serveur MCP stdio (ex: filesystem, git, sqlite, scripts custom) pour exposer automatiquement ses outils comme des compétences distribuées :
```bash
python -m jarvismesh.cli start --name mac-tools --port 8767 \
  --mcp-command "npx -y @modelcontextprotocol/server-filesystem /Users/selim/Documents"
```
Les outils deviennent immédiatement disponibles pour tout le réseau : `mcp_read_file`, `mcp_list_directory`, etc.

### 2. Exposer le Mesh comme Serveur MCP (Mode Serveur)
Permet à **Claude Desktop**, **Cursor** ou **Antigravity** d'utiliser l'ensemble du réseau JarvisMesh comme fournisseur d'outils MCP :
```bash
python -m jarvismesh.cli mcp-server
```

---

## Mémoire Partagée & RAG Local Distribué

Un moteur de base vectorielle embarquée et de recherche sémantique cosinus :

- **`rag_index`** : Indexation de documents ou snippets de texte avec métadonnées.
- **`rag_search`** : Recherche sémantique retournant les passages les plus pertinents avec scores.
- **`rag_ask`** : Pipeline RAG complet qui retrouve les contextes pertinents et formule la réponse via le LLM MLX.

```bash
# Indexer un document
python -m jarvismesh.cli ask rag_index '{"text": "Le projet JarvisMesh est sécurisé par Ed25519.", "id": "sec_doc"}'

# Poser une question sur la base de connaissances
python -m jarvismesh.cli ask rag_ask '{"question": "Comment est sécurisé JarvisMesh ?"}'
```

---

## Interconnexion WAN & Relais Multi-Réseaux (Tailscale)

Connectez vos agents situés sur des réseaux différents (ex: Mac Studio au bureau + MacBook en déplacement) :

### 1. Détection automatique Tailscale / VPN
JarvisMesh détecte automatiquement les adresses IP du maillage Tailscale (`100.x.y.z`).

### 2. Serveur Relais de Rendez-vous (`jarvismesh relay`)
Permet l'auto-découverte sans multicast :
```bash
# Sur un serveur ou une machine fixe (ex: IP 100.64.0.1)
python -m jarvismesh.cli relay --port 9000

# Sur chaque nœud distant
python -m jarvismesh.cli start --name mac-portable --port 8765 --relay-url http://100.64.0.1:9000
```

---

## Système de Plugins & Décorateur `@skill`

Créez vos propres plugins Python avec validation Pydantic :

```python
# plugins/math_tools.py
from jarvismesh import skill
from pydantic import BaseModel, Field

class FibPayload(BaseModel):
    n: int = Field(ge=0, le=50)

@skill(name="fibonacci", schema=FibPayload, description="Calcule le N-ième terme de Fibonacci")
def fibonacci(payload: dict) -> dict:
    n = payload["n"]
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return {"n": n, "result": a}
```

Chargement :
```bash
python -m jarvismesh.cli start --name mac-dev --port 8765 --skills-dir ./plugins
```

---

## Orchestrateur & Pipelines Multi-Agents

Combinez plusieurs compétences en un pipeline séquentiel et parallèle avec injection de variables :

```python
from jarvismesh import Workflow, WorkflowStep

wf = Workflow("Pipeline Résumé & Analyse")
wf.add_step("redaction", skill="llm", payload={"prompt": "Rédige un article sur : {input.topic}"})
wf.add_parallel_steps([
    WorkflowStep("comptage", skill="wordcount", payload={"text": "{steps.redaction.result.response}"}),
    WorkflowStep("indexation", skill="rag_index", payload={"text": "{steps.redaction.result.response}"}),
])

result = await wf.run(node, initial_input={"topic": "L'informatique quantique"})
```

Exécution depuis un fichier JSON :
```bash
python -m jarvismesh.cli workflow pipeline.json --input '{"topic": "Les réseaux P2P"}'
```

---

## Référence de la CLI

| Commande | Arguments principaux | Description |
| :--- | :--- | :--- |
| `jarvismesh keygen` | `--out <file>`, `--add-to <truststore>`, `--name <str>` | Génère une paire de clés asymétriques Ed25519. |
| `jarvismesh start` | `--name <str>`, `--port <int>`, `--identity-file <file>`, `--authorized-keys <file>`, `--rag-dir <dir>`, `--mcp-command <cmd>`, `--relay-url <url>`, `--skills-dir <dir>`, `--model <str>` | Démarre un nœud complet avec toutes ses extensions. |
| `jarvismesh ask` | `<skill> [payload]`, `--peer <str>`, `--stream`, `--identity-file <file>`, `--psk <str>` | Délègue une tâche à un agent du réseau en direct. |
| `jarvismesh dashboard` | `--port <int>`, `--node-port <int>`, `--name <str>`, `--skills-dir <dir>` | Lance le Dashboard Web interactif de supervision. |
| `jarvismesh workflow` | `<file.json>`, `--input <json>`, `--psk <str>` | Exécute un workflow multi-agents défini en JSON. |
| `jarvismesh relay` | `--port <int>`, `--host <str>` | Démarre le serveur de relais / rendez-vous WAN. |
| `jarvismesh mcp-server` | `--name <str>` | Exécute JarvisMesh en tant que serveur d'outils MCP stdio. |

---

## Référence de l'API Python

```python
from jarvismesh import (
    JarvisNode, NodeIdentity, TrustStore, 
    Workflow, WorkflowStep, 
    LocalVectorStore, RAGManager,
    MCPClientBridge, MCPServerBridge,
    MeshRelayServer, WANPeerManager,
    skill, SkillRegistry
)
```

---

## Arborescence du Projet

```text
jarvismesh/
├── jarvismesh/               # Code source du package
│   ├── __init__.py           # Exports de l'API publique
│   ├── protocol.py           # Protocoles de messages JSON, signatures HMAC & Ed25519
│   ├── crypto.py             # Gestion des clés Ed25519 & TrustStore
│   ├── e2ee.py               # Chiffrement de bout en bout X25519 & ChaCha20-Poly1305
│   ├── node.py               # Nœud P2P, multiplexage, découverte, routage adaptatif
│   ├── skills.py             # Registre de compétences, décorateur @skill & outils de base
│   ├── mlx_engine.py         # Moteur MLX-LM dédié, streaming Metal, métriques VRAM
│   ├── orchestrator.py       # Moteur de workflows multi-agents (séquentiel/parallèle)
│   ├── agent.py              # Agent Autonome ReAct & Function Calling Distribué
│   ├── memory.py             # Base vectorielle SQLite persistante & mémoire épisodique
│   ├── mcp_bridge.py         # Passerelle bi-directionnelle Model Context Protocol (MCP)
│   ├── rag.py                # Base vectorielle locale TF-IDF & compétences RAG
│   ├── wan.py                # Détection Tailscale, relais WAN & synchronisation distante
│   ├── daemon.py             # Service démon d'arrière-plan macOS launchd / Linux systemd
│   ├── gossip.py             # Protocole Gossip SWIM pour cluster haute échelle
│   ├── cli.py                # Interface en ligne de commande complète
│   └── dashboard/            # Serveur HTTP/SSE & Dashboard Web interactif
├── tests/                    # Suites de tests automatisées (100% pytest pass rate)
│   ├── conftest.py           # Configuration de test et bootstrap PYTHONPATH
│   ├── test_agent_react.py   # Tests de l'agent ReAct et auto-réparation (self-healing)
│   ├── test_e2ee.py          # Tests du chiffrement E2EE X25519/ChaCha20
│   ├── test_memory_sqlite.py # Tests de la mémoire SQLite et embeddings denses
│   ├── test_gossip_daemon.py # Tests du protocole Gossip SWIM et launchd/systemd
│   ├── test_crypto_ed25519.py# Tests de signature Ed25519, TrustStore et anti-rejeu
│   ├── test_mcp_bridge.py    # Tests du pont d'outils MCP stdio
│   ├── test_rag.py           # Tests d'indexation, recherche cosinus et RAG
│   ├── test_wan_relay.py     # Tests de découverte et routage WAN via relais
│   ├── test_skills_loader.py # Tests du décorateur @skill et chargement dynamique
│   ├── test_orchestrator.py  # Tests du moteur de workflows DAG
│   ├── test_dashboard.py     # Tests de l'API REST et du serveur Web
│   ├── test_mlx.py           # Tests d'inférence MLX et streaming Metal
│   ├── test_core_mesh.py     # Tests du flux de base, multiplexage et failover
│   └── test_improvements.py  # Tests d'authentification HMAC et routage par santé
├── examples/                 # Scripts et cas d'usage réels
│   ├── rag_multiagent_workflow.py # Pipeline complet RAG + LLM MLX + Analyse Parallèle
│   └── mcp_system_tools.py        # Intégration d'outils système via passerelle MCP
├── workflows/                # Définitions de pipelines multi-agents (JSON)
│   └── rag_pipeline.json     # Workflow déclaratif RAG & Synthèse
├── pyproject.toml            # Métadonnées et packaging du projet
├── .gitignore                # Fichiers et dossiers ignorés par Git
└── README.md                 # Documentation exhaustive du projet
```

---

## Exécution des Tests

L'intégralité des 14 suites de tests valide l'ensemble du maillage en une seule commande :

```bash
# Lancer tous les tests (22 tests validés à 100%)
.venv/bin/python -m pytest tests/

# Ou lancer un test spécifique
.venv/bin/python tests/test_agent_react.py
.venv/bin/python tests/test_e2ee.py
.venv/bin/python tests/test_memory_sqlite.py
.venv/bin/python tests/test_gossip_daemon.py
```

---

## Licence

Distribué sous licence **MIT**.

