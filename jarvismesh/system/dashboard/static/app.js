// JarvisMesh Dashboard Frontend Logic
document.addEventListener("DOMContentLoaded", () => {
  // Navigation Tabs
  const navButtons = document.querySelectorAll(".nav-item");
  const tabContents = document.querySelectorAll(".tab-content");
  const viewTitle = document.getElementById("currentViewTitle");
  const viewDesc = document.getElementById("currentViewDesc");

  const tabMeta = {
    topology: { title: "Topologie du Mesh", desc: "Découverte mDNS en temps réel et statut des nœuds connectés" },
    telemetry: { title: "Télémétrie & Santé", desc: "Métriques VRAM Metal, charge CPU et tâches concurrentes" },
    studio: { title: "Studio d'Inférence", desc: "Déléguez des requêtes et recevez les flux de tokens en direct" },
    workflows: { title: "Workflows Multi-Agents", desc: "Exécutez des pipelines distribués avec interpolation de contexte" }
  };

  navButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      const tabKey = btn.getAttribute("data-tab");
      navButtons.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const targetTab = document.getElementById(`tab-${tabKey}`);
      if (targetTab) targetTab.classList.add("active");
      if (tabMeta[tabKey]) {
        viewTitle.textContent = tabMeta[tabKey].title;
        viewDesc.textContent = tabMeta[tabKey].desc;
      }
    });
  });

  // State
  let meshState = {
    node: { name: "", port: 0, ip: "", skills: [], health: {} },
    peers: {},
    peers_health: {}
  };

  // Initial Fetch & SSE Setup
  async function fetchInitialStatus() {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        meshState = {
          node: {
            name: data.name,
            port: data.port,
            ip: data.ip,
            skills: data.skills || [],
            health: data.health || {}
          },
          peers: data.peers || {},
          peers_health: data.peers_health || {}
        };
        updateUI();
      }
    } catch (e) {
      console.error("Erreur lors du fetch initial:", e);
    }
  }

  function setupSSE() {
    const evtSource = new EventSource("/api/events");
    evtSource.addEventListener("telemetry", (e) => {
      try {
        const data = JSON.parse(e.data);
        meshState.node = data.node || meshState.node;
        meshState.peers = data.peers || {};
        meshState.peers_health = data.peers_health || {};
        updateUI();
      } catch (err) {
        console.error("Erreur parsing SSE:", err);
      }
    });

    evtSource.onerror = () => {
      console.warn("SSE déconnecté, reconnexion...");
    };
  }

  document.getElementById("btnRefresh")?.addEventListener("click", fetchInitialStatus);

  // Update Global UI
  function updateUI() {
    const node = meshState.node;
    const peers = meshState.peers || {};
    const peersHealth = meshState.peers_health || {};

    // 1. Sidebar Local Node
    document.getElementById("localNodeName").textContent = node.name || "Nœud Local";
    document.getElementById("localNodeMeta").textContent = `${node.ip}:${node.port}`;

    const peerCount = Object.keys(peers).length;
    document.getElementById("peerCountStat").textContent = peerCount;
    document.getElementById("totalNodesVal").textContent = peerCount + 1;

    // Collect all skills
    const allSkillsSet = new Set(node.skills || []);
    Object.values(peers).forEach(p => {
      (p.skills || []).forEach(s => allSkillsSet.add(s));
    });
    document.getElementById("skillCountStat").textContent = allSkillsSet.size;
    document.getElementById("totalSkillsVal").textContent = allSkillsSet.size;

    // 2. Topology Grid
    const grid = document.getElementById("nodesGrid");
    if (grid) {
      grid.innerHTML = "";

      // Local Node Card
      const localCard = createNodeCard(node.name, node.ip, node.port, node.skills, node.health, true);
      grid.appendChild(localCard);

      // Peer Cards
      Object.entries(peers).forEach(([pName, pInfo]) => {
        const pHealth = peersHealth[pName] || {};
        const peerCard = createNodeCard(pName, pInfo.address, pInfo.port, pInfo.skills || [], pHealth, false);
        grid.appendChild(peerCard);
      });
    }

    // 3. Telemetry Tab
    updateTelemetry(node.health, peersHealth);

    // 4. Update Peer Selector in Studio
    updatePeerSelector(peers);
  }

  function createNodeCard(name, ip, port, skills, health, isLocal) {
    const div = document.createElement("div");
    div.className = `node-card-item ${isLocal ? "is-local" : ""}`;

    const hasMlx = health.mlx_available || false;
    const vramMb = health.metal_active_mb ? `${health.metal_active_mb} MB` : (hasMlx ? "MLX" : "CPU");
    const activeTasks = health.active_tasks !== undefined ? health.active_tasks : 0;
    const loadAvg = health.load !== undefined && health.load !== null ? health.load.toFixed(2) : "N/A";

    const skillsHtml = skills.map(s => `<span class="skill-pill" data-skill="${s}">${s}</span>`).join("");

    div.innerHTML = `
      <div class="card-top">
        <div class="node-header-info">
          <h4>${name} ${isLocal ? '<span class="badge cyan">Local</span>' : '<span class="badge green">Pair Distant</span>'}</h4>
          <span class="node-ip">${ip}:${port}</span>
        </div>
        <span class="badge ${hasMlx ? 'purple' : ''}">${hasMlx ? 'Metal MLX' : 'Standard'}</span>
      </div>
      <div class="skills-section">
        <div style="font-size: 11px; color: var(--text-dim); margin-bottom: 6px; text-transform: uppercase;">Compétences (${skills.length})</div>
        <div class="skills-pill-list">${skillsHtml || '<span style="color: var(--text-dim); font-size: 12px;">Aucune</span>'}</div>
      </div>
      <div class="node-stats-mini">
        <div class="stat-item"><span class="k">Tâches</span><span class="v">${activeTasks}</span></div>
        <div class="stat-item"><span class="k">Load 1m</span><span class="v">${loadAvg}</span></div>
        <div class="stat-item"><span class="k">VRAM</span><span class="v">${vramMb}</span></div>
      </div>
    `;

    // Click skill pill -> fill studio form
    div.querySelectorAll(".skill-pill").forEach(pill => {
      pill.addEventListener("click", () => {
        const skillName = pill.getAttribute("data-skill");
        const skillSelect = document.getElementById("selectSkill");
        if (skillSelect) {
          skillSelect.value = skillName;
        }
        const studioBtn = document.querySelector('.nav-item[data-tab="studio"]');
        if (studioBtn) studioBtn.click();
      });
    });

    return div;
  }

  function updateTelemetry(localHealth, peersHealth) {
    const activeVram = localHealth.metal_active_mb || 0;
    const peakVram = localHealth.metal_peak_mb || 0;
    const cacheVram = localHealth.metal_cache_mb || 0;

    document.getElementById("vramActiveVal").textContent = `${activeVram} MB`;
    document.getElementById("vramPeakVal").textContent = `${peakVram} MB`;
    document.getElementById("vramCacheVal").textContent = `${cacheVram} MB`;

    // Max scale assumption for gauge (e.g. 16GB)
    const scaleMax = 16000;
    document.getElementById("vramActiveBar").style.width = `${Math.min(100, (activeVram / scaleMax) * 100)}%`;
    document.getElementById("vramPeakBar").style.width = `${Math.min(100, (peakVram / scaleMax) * 100)}%`;
    document.getElementById("vramCacheBar").style.width = `${Math.min(100, (cacheVram / scaleMax) * 100)}%`;

    document.getElementById("activeTasksCount").textContent = localHealth.active_tasks || 0;
    document.getElementById("loadAvgVal").textContent = localHealth.load !== undefined && localHealth.load !== null ? localHealth.load.toFixed(2) : "0.00";
    document.getElementById("cpuCountVal").textContent = `${localHealth.cpu_count || 8} cœurs`;

    const modelName = localHealth.loaded_model || "Qwen3.5-4B-MLX-4bit";
    document.getElementById("mlxModelVal").textContent = modelName.split("/").pop();

    // Table of peers health
    const tbody = document.getElementById("peerHealthTableBody");
    const peerEntries = Object.entries(meshState.peers || {});
    if (peerEntries.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">Aucun pair distant détecté pour l'instant.</td></tr>`;
    } else {
      tbody.innerHTML = peerEntries.map(([pName, pInfo]) => {
        const h = peersHealth[pName] || {};
        const vramText = h.metal_active_mb ? `${h.metal_active_mb} MB (MLX)` : (h.mlx_available ? "MLX" : "CPU");
        const load = h.load !== undefined && h.load !== null ? h.load.toFixed(2) : "N/A";
        const tasks = h.active_tasks !== undefined ? h.active_tasks : "0";
        const syncTime = h.ts ? `${Math.round(Date.now() / 1000 - h.ts)}s` : "En attente";

        return `
          <tr>
            <td><strong>${pName}</strong></td>
            <td>${pInfo.address}:${pInfo.port}</td>
            <td>${tasks}</td>
            <td>${load}</td>
            <td>${vramText}</td>
            <td>${syncTime}</td>
          </tr>
        `;
      }).join("");
    }
  }

  function updatePeerSelector(peers) {
    const sel = document.getElementById("selectTargetPeer");
    if (!sel) return;
    const currentVal = sel.value;
    sel.innerHTML = `<option value="">Routage automatique par charge (Recommandé)</option>`;
    Object.keys(peers).forEach(pName => {
      const opt = document.createElement("option");
      opt.value = pName;
      opt.textContent = `Cibler: ${pName}`;
      sel.appendChild(opt);
    });
    sel.value = currentVal;
  }

  // -------------------------------------------------------------
  // Studio Execution & Live Streaming
  // -------------------------------------------------------------
  const btnExecute = document.getElementById("btnExecuteTask");
  const outputConsole = document.getElementById("outputConsole");
  const streamBadge = document.getElementById("streamNodeBadge");
  const tokenSpeedBadge = document.getElementById("tokenSpeedBadge");

  btnExecute?.addEventListener("click", async () => {
    const skill = document.getElementById("selectSkill").value;
    const peer = document.getElementById("selectTargetPeer").value || null;
    const prompt = document.getElementById("promptInput").value;
    const maxTokens = parseInt(document.getElementById("maxTokensInput").value, 10) || 256;
    const temp = parseFloat(document.getElementById("tempInput").value) || 0.7;

    const payload = {
      prompt: prompt,
      text: prompt,
      max_tokens: maxTokens,
      temperature: temp
    };

    const isStream = skill.includes("stream");
    btnExecute.disabled = true;
    outputConsole.innerHTML = "";
    streamBadge.textContent = "Exécution en cours...";
    streamBadge.className = "badge cyan";
    tokenSpeedBadge.textContent = "0 tok/s";

    const tStart = performance.now();
    let tokenCount = 0;

    try {
      if (isStream) {
        const response = await fetch("/api/delegate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill, payload, peer, stream: true })
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop();

          for (const block of lines) {
            if (block.startsWith("event: chunk")) {
              const dataLine = block.split("\n").find(l => l.startsWith("data: "));
              if (dataLine) {
                const chunkObj = JSON.parse(dataLine.substring(6));
                outputConsole.textContent += chunkObj.chunk;
                tokenCount += 1;
                const elapsedSec = (performance.now() - tStart) / 1000;
                if (elapsedSec > 0.3) {
                  tokenSpeedBadge.textContent = `${(tokenCount / elapsedSec).toFixed(1)} tok/s`;
                }
                outputConsole.scrollTop = outputConsole.scrollHeight;
              }
            } else if (block.startsWith("event: done")) {
              const dataLine = block.split("\n").find(l => l.startsWith("data: "));
              if (dataLine) {
                const finalObj = JSON.parse(dataLine.substring(6));
                streamBadge.textContent = `Terminé via ${finalObj.handled_by || 'local'}`;
                streamBadge.className = "badge green";
              }
            }
          }
        }
      } else {
        const res = await fetch("/api/delegate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ skill, payload, peer, stream: false })
        });
        const data = await res.json();
        if (data.ok) {
          outputConsole.textContent = typeof data.result === "string" ? data.result : JSON.stringify(data.result, null, 2);
          streamBadge.textContent = `Succès (${data.handled_by})`;
          streamBadge.className = "badge green";
        } else {
          outputConsole.textContent = `ERREUR: ${data.error}`;
          streamBadge.textContent = "Erreur";
          streamBadge.className = "badge";
          streamBadge.style.background = "rgba(239, 68, 68, 0.2)";
          streamBadge.style.color = "#ef4444";
        }
      }
    } catch (err) {
      outputConsole.textContent = `Erreur réseau: ${err.message}`;
      streamBadge.textContent = "Échec";
    } finally {
      btnExecute.disabled = false;
    }
  });

  // -------------------------------------------------------------
  // Workflow Runner
  // -------------------------------------------------------------
  const sampleWorkflow = {
    name: "Pipeline IA et Analyse Sémantique",
    description: "Génère une explication avec le LLM MLX puis compte les mots et inverse le texte en parallèle.",
    stages: [
      {
        name: "generation_llm",
        skill: "llm",
        payload: {
          prompt: "Explique en 2 phrases concises le sujet: {input.topic}",
          max_tokens: 150
        }
      },
      [
        {
          name: "comptage_mots",
          skill: "wordcount",
          payload: {
            text: "{steps.generation_llm.result.response}"
          }
        },
        {
          name: "inversion_texte",
          skill: "reverse",
          payload: {
            text: "{steps.generation_llm.result.response}"
          }
        }
      ]
    ]
  };

  const wfEditor = document.getElementById("workflowJsonEditor");
  if (wfEditor) {
    wfEditor.value = JSON.stringify(sampleWorkflow, null, 2);
  }

  document.getElementById("btnLoadExampleWorkflow")?.addEventListener("click", () => {
    if (wfEditor) wfEditor.value = JSON.stringify(sampleWorkflow, null, 2);
  });

  const btnRunWf = document.getElementById("btnRunWorkflow");
  const timeline = document.getElementById("workflowTimeline");
  const wfStatusBadge = document.getElementById("workflowStatusBadge");

  btnRunWf?.addEventListener("click", async () => {
    let workflowDef;
    try {
      workflowDef = JSON.parse(wfEditor.value);
    } catch (e) {
      alert("JSON de workflow invalide : " + e.message);
      return;
    }

    const topicVal = document.getElementById("workflowInputParam").value;
    const initialInput = { topic: topicVal };

    btnRunWf.disabled = true;
    wfStatusBadge.textContent = "En cours d'exécution...";
    wfStatusBadge.className = "badge cyan";
    timeline.innerHTML = "";

    try {
      const response = await fetch("/api/workflow/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: workflowDef, input: initialInput, stream: true })
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n\n");
        buffer = lines.pop();

        for (const block of lines) {
          if (!block.trim()) continue;
          const eventLine = block.split("\n").find(l => l.startsWith("event: "));
          const dataLine = block.split("\n").find(l => l.startsWith("data: "));
          if (!eventLine || !dataLine) continue;

          const eventType = eventLine.substring(7).trim();
          const eventData = JSON.parse(dataLine.substring(6).trim());

          if (eventType === "step_start") {
            createOrUpdateStepCard(eventData.step, "running", eventData.data);
          } else if (eventType === "step_done") {
            createOrUpdateStepCard(eventData.step, "success", eventData.data);
          } else if (eventType === "step_error") {
            createOrUpdateStepCard(eventData.step, "error", eventData.data);
          } else if (eventType === "workflow_done") {
            wfStatusBadge.textContent = eventData.ok ? "Workflow Terminé avec Succès" : "Workflow Terminé avec Erreurs";
            wfStatusBadge.className = eventData.ok ? "badge green" : "badge";
            if (!eventData.ok) {
              wfStatusBadge.style.background = "rgba(239, 68, 68, 0.2)";
              wfStatusBadge.style.color = "#ef4444";
            }
          }
        }
      }
    } catch (err) {
      wfStatusBadge.textContent = "Erreur: " + err.message;
    } finally {
      btnRunWf.disabled = false;
    }
  });

  function createOrUpdateStepCard(stepName, status, data) {
    let card = document.getElementById(`step-card-${stepName}`);
    if (!card) {
      card = document.createElement("div");
      card.id = `step-card-${stepName}`;
      card.className = "step-card";
      timeline.appendChild(card);
    }

    card.className = `step-card ${status}`;
    const statusText = status === "running" ? "⏳ En cours" : (status === "success" ? "✅ Succès" : "❌ Échec");
    const duration = data && data.duration_sec ? ` (${data.duration_sec.toFixed(2)}s)` : "";
    const nodeHandled = data && data.handled_by ? ` @ ${data.handled_by}` : "";

    let resultHtml = "";
    if (data && (data.result !== undefined || data.error)) {
      const content = data.error ? `ERREUR: ${data.error}` : JSON.stringify(data.result, null, 2);
      resultHtml = `<div class="step-result-box">${content}</div>`;
    }

    card.innerHTML = `
      <div class="step-header">
        <span class="step-title">Étape: <strong>${stepName}</strong></span>
        <span class="badge ${status === 'success' ? 'green' : (status === 'running' ? 'cyan' : '')}">${statusText}${duration}${nodeHandled}</span>
      </div>
      ${resultHtml}
    `;
  }

  // Start app
  fetchInitialStatus();
  setupSSE();
});
