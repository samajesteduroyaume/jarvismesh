"""
JarvisMesh — Réseau maillé P2P souverain et distribué pour agents d'IA locaux (Apple Silicon MLX).

Architecture Modulaire Organisée en 7 Sous-Packages :
- jarvismesh.core       : Réseau P2P, Protocole WebSocket, NAT STUN/ICE, WAN Relay, SWIM Gossip, Binary Protocol.
- jarvismesh.security   : Cryptographie Ed25519, E2EE X25519/ChaCha20, RBAC, Sandbox d'exécution.
- jarvismesh.engines    : MLX-LM Metal GPU, Multi-Model Manager LRU, Vision VLM, Audio Whisper STT.
- jarvismesh.memory     : SQLite Vector Store, Conversation Memory, GraphRAG, TF-IDF RAG, Semantic Reranker.
- jarvismesh.agents     : Agent ReAct autonome, Orchestrateur DAG, Consensus, Queue Store & Forward, MCP.
- jarvismesh.skills     : Registre de compétences (@skill), chargeur dynamique de plugins.
- jarvismesh.system     : Démon système launchd/systemd, CLI unifiée, Dashboard Web SSE.
"""
from __future__ import annotations

# 1. Imports Core
from .core import (
    JarvisNode,
    TaskRequest,
    TaskResponse,
    TaskChunk,
    PROTOCOL_VERSION,
    SERVICE_TYPE,
    DESCRIBE_SKILL,
    HEALTH_SKILL,
    RESERVED_SKILLS,
    sign_request,
    verify_request,
    parse_message,
    BinaryMessageEncoder,
    MAGIC_BINARY_HEADER,
    STUNClient,
    NATTraversalManager,
    STUNEndpoint,
    MeshRelayServer,
    WANPeerManager,
    detect_tailscale_ip,
    GossipCluster,
    GossipMember,
    MemberState,
)

# 2. Imports Security
from .security import (
    NodeIdentity,
    TrustStore,
    verify_ed25519_signature,
    E2EEIdentity,
    E2EESession,
    encrypt_for_peer,
    decrypt_from_peer,
    RBACManager,
    DEFAULT_ROLES,
    SandboxSkillExecutor,
    DynamicSkillManager,
    get_sandbox_skills,
)

# 3. Imports Engines
from .engines import (
    MLXModelManager,
    llm,
    llm_stream,
    mlx_health_extra,
    LLMPayload,
    DEFAULT_MODEL_NAME,
    MultiModelManager,
    ModelSlot,
    VLMModelManager,
    get_vlm_skills,
    DEFAULT_VLM_MODEL,
    AudioTranscriber,
    get_audio_skills,
    DEFAULT_AUDIO_MODEL,
)

# 4. Imports Memory
from .memory import (
    SQLiteVectorStore,
    DenseEmbeddingEngine,
    ConversationMemory,
    MemorySkillsManager,
    LocalVectorStore,
    RAGManager,
    SemanticReranker,
    get_reranker_skills,
    KnowledgeGraphStore,
    get_graph_skills,
)

# 5. Imports Agents
from .agents import (
    AutonomousAgent,
    AgentStep,
    AgentTrace,
    Workflow,
    WorkflowStep,
    WorkflowResult,
    MultiAgentConsensus,
    ConsensusResult,
    AgentVote,
    PersistentTaskQueue,
    QueuedTask,
    MCPClientBridge,
    MCPServerBridge,
)

# 6. Imports Skills
from .skills import (
    SkillRegistry,
    default_registry,
    skill,
    BUILTIN_SKILLS,
    DEFAULT_SKILLS,
    echo,
    reverse,
    wordcount,
    slow_echo,
)

# 7. Imports System
from .system import (
    ServiceManager,
    DashboardServer,
    run_dashboard,
)

# Sous-packages
from . import core, security, engines, memory, agents, skills, system

__all__ = [
    # Subpackages
    "core",
    "security",
    "engines",
    "memory",
    "agents",
    "skills",
    "system",
    # Core
    "JarvisNode",
    "TaskRequest",
    "TaskResponse",
    "TaskChunk",
    "PROTOCOL_VERSION",
    "SERVICE_TYPE",
    "DESCRIBE_SKILL",
    "HEALTH_SKILL",
    "RESERVED_SKILLS",
    "sign_request",
    "verify_request",
    "parse_message",
    "BinaryMessageEncoder",
    "MAGIC_BINARY_HEADER",
    "STUNClient",
    "NATTraversalManager",
    "STUNEndpoint",
    "MeshRelayServer",
    "WANPeerManager",
    "detect_tailscale_ip",
    "GossipCluster",
    "GossipMember",
    "MemberState",
    # Security
    "NodeIdentity",
    "TrustStore",
    "verify_ed25519_signature",
    "E2EEIdentity",
    "E2EESession",
    "encrypt_for_peer",
    "decrypt_from_peer",
    "RBACManager",
    "DEFAULT_ROLES",
    "SandboxSkillExecutor",
    "DynamicSkillManager",
    "get_sandbox_skills",
    # Engines
    "MLXModelManager",
    "llm",
    "llm_stream",
    "mlx_health_extra",
    "LLMPayload",
    "DEFAULT_MODEL_NAME",
    "MultiModelManager",
    "ModelSlot",
    "VLMModelManager",
    "get_vlm_skills",
    "DEFAULT_VLM_MODEL",
    "AudioTranscriber",
    "get_audio_skills",
    "DEFAULT_AUDIO_MODEL",
    # Memory
    "SQLiteVectorStore",
    "DenseEmbeddingEngine",
    "ConversationMemory",
    "MemorySkillsManager",
    "LocalVectorStore",
    "RAGManager",
    "SemanticReranker",
    "get_reranker_skills",
    "KnowledgeGraphStore",
    "get_graph_skills",
    # Agents
    "AutonomousAgent",
    "AgentStep",
    "AgentTrace",
    "Workflow",
    "WorkflowStep",
    "WorkflowResult",
    "MultiAgentConsensus",
    "ConsensusResult",
    "AgentVote",
    "PersistentTaskQueue",
    "QueuedTask",
    "MCPClientBridge",
    "MCPServerBridge",
    # Skills
    "SkillRegistry",
    "default_registry",
    "skill",
    "BUILTIN_SKILLS",
    "DEFAULT_SKILLS",
    "echo",
    "reverse",
    "wordcount",
    "slow_echo",
    # System
    "ServiceManager",
    "DashboardServer",
    "run_dashboard",
]
