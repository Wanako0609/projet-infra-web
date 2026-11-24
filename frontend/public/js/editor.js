// Atelier visuel « plug & play » (Étape 4)
// Gère le glisser-déposer de modules, le tracé de liens SVG, l'inspecteur,
// la sauvegarde PUT, le mode lecture seule et le pilotage Docker.

const MODULE_META = {
    postgres: { icon: '🗄️', prefix: 'db', defaultLabel: 'Base PostgreSQL' },
    linux_net: { icon: '🖥️', prefix: 'pc', defaultLabel: 'Poste Linux' },
    linux_desktop: { icon: '🪟', prefix: 'desk', defaultLabel: 'Bureau Graphique' },
};

const NODE_WIDTH = 210;
const NODE_HEIGHT = 86;

const editorState = {
    infraId: null,
    infra: null,
    modules: [],
    runtime: null,
    selectedNodeId: null,
    isReadOnly: false,
    isDirty: false,
    // Interactions souris en cours
    draggingNode: null, // { nodeId, offsetX, offsetY }
    linkingFrom: null, // { sourceId, cursorX, cursorY }
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    const el = document.getElementById('editor-toast');
    el.textContent = message;
    el.className = `editor-toast ${type}`;
    el.hidden = false;
}

function hideToast() {
    document.getElementById('editor-toast').hidden = true;
}

function markDirty(dirty = true) {
    if (editorState.isReadOnly) return;
    editorState.isDirty = dirty;
    document.getElementById('editor-dirty-badge').hidden = !dirty;
}

function getCatalogSpec(moduleType) {
    return editorState.modules.find((m) => m.type === moduleType) || null;
}

function getRuntimeNode(nodeId) {
    if (!editorState.runtime || !editorState.runtime.nodes) return null;
    return editorState.runtime.nodes.find((n) => n.node_id === nodeId) || null;
}

function nextNodeId(moduleType) {
    const prefix = MODULE_META[moduleType]?.prefix || 'mod';
    const existing = new Set((editorState.infra.definition.nodes || []).map((n) => n.id));
    let i = 1;
    while (existing.has(`${prefix}-${i}`)) {
        i += 1;
    }
    return `${prefix}-${i}`;
}

function nextLinkId() {
    const existing = new Set((editorState.infra.definition.links || []).map((l) => l.id));
    let i = 1;
    while (existing.has(`link-${i}`)) {
        i += 1;
    }
    return `link-${i}`;
}

function getCanvasCoords(clientX, clientY) {
    const stage = document.getElementById('canvas-stage');
    const rect = stage.getBoundingClientRect();
    return {
        x: Math.max(16, Math.round(clientX - rect.left + stage.scrollLeft)),
        y: Math.max(16, Math.round(clientY - rect.top + stage.scrollTop)),
    };
}

// --- Rendu barre supérieure & mode lecture seule ---

function renderTopbar() {
    const infra = editorState.infra;
    const rt = editorState.runtime;

    document.getElementById('editor-infra-name').textContent = infra.name;
    document.title = `${infra.name} — Atelier Infra Web`;

    const accessBadge = document.getElementById('editor-access-badge');
    if (editorState.isReadOnly) {
        accessBadge.textContent = `Lecture seule (${infra.owner_username})`;
        accessBadge.className = 'badge badge-readonly';
    } else {
        accessBadge.textContent = 'Propriétaire';
        accessBadge.className = 'badge badge-owner';
    }

    const currentStatus = rt ? rt.status : infra.status;
    const isRunning = currentStatus === 'running';
    const statusBadge = document.getElementById('editor-status-badge');
    statusBadge.textContent = currentStatus;
    statusBadge.className = `badge ${isRunning ? 'badge-running' : 'badge-status'}`;

    const netEl = document.getElementById('editor-network-info');
    if (rt && rt.network_name) {
        netEl.textContent = `${rt.network_name} (${rt.subnet || 'IPAM'})`;
    } else if (rt && !rt.docker_available) {
        netEl.textContent = 'Docker indisponible';
    } else {
        netEl.textContent = '';
    }

    // Verrouillage des contrôles en lecture seule
    document.getElementById('readonly-banner').hidden = !editorState.isReadOnly;
    document.getElementById('btn-save').hidden = editorState.isReadOnly;
    document.getElementById('btn-start').hidden = editorState.isReadOnly || isRunning;
    document.getElementById('btn-stop').hidden = editorState.isReadOnly || !isRunning;
}

// --- Rendu palette gauche ---

function renderPalette() {
    const container = document.getElementById('palette-list');
    const hint = document.getElementById('palette-hint');
    hint.textContent = editorState.isReadOnly
        ? 'Ajout désactivé en lecture seule.'
        : "Glissez un module sur le canevas (ou cliquez dessus) pour l'ajouter.";

    container.innerHTML = editorState.modules
        .map((mod) => {
            const meta = MODULE_META[mod.type] || { icon: '📦' };
            return `
                <div class="palette-item ${editorState.isReadOnly ? 'disabled' : ''}"
                     draggable="${!editorState.isReadOnly}"
                     data-module-type="${escapeHtml(mod.type)}">
                    <div class="palette-item-top">
                        <strong>${meta.icon} ${escapeHtml(mod.label)}</strong>
                        <span class="badge badge-neutral">~${mod.memory_mb} Mo</span>
                    </div>
                    <p class="palette-item-desc">${escapeHtml(mod.description)}</p>
                </div>
            `;
        })
        .join('');

    container.querySelectorAll('.palette-item').forEach((item) => {
        const modType = item.dataset.moduleType;
        item.addEventListener('dragstart', (event) => {
            if (editorState.isReadOnly) {
                event.preventDefault();
                return;
            }
            event.dataTransfer.setData('text/plain', modType);
            event.dataTransfer.effectAllowed = 'copy';
        });
        item.addEventListener('click', () => {
            if (editorState.isReadOnly) return;
            const offset = (editorState.infra.definition.nodes.length % 6) * 35;
            addNodeToCanvas(modType, 120 + offset, 110 + offset);
        });
    });
}

// --- Ajout / suppression de nœuds & liens ---

function addNodeToCanvas(moduleType, x, y) {
    if (editorState.isReadOnly) return;
    const spec = getCatalogSpec(moduleType);
    if (!spec) return;

    const id = nextNodeId(moduleType);
    const meta = MODULE_META[moduleType] || { defaultLabel: spec.label };
    const defaultCfg = { ...(spec.default_config || {}) };
    if ('hostname' in defaultCfg) {
        defaultCfg.hostname = id;
    }

    const newNode = {
        id,
        module_type: moduleType,
        name: `${meta.defaultLabel} ${id.split('-').pop()}`,
        x: Math.round(x),
        y: Math.round(y),
        config: defaultCfg,
        files: {},
    };

    editorState.infra.definition.nodes.push(newNode);
    editorState.selectedNodeId = id;
    markDirty(true);
    renderCanvas();
    renderInspector();
}

function addLink(sourceId, targetId) {
    if (editorState.isReadOnly) return;
    if (!sourceId || !targetId || sourceId === targetId) return;

    const links = editorState.infra.definition.links;
    const alreadyExists = links.some(
        (l) =>
            (l.source === sourceId && l.target === targetId) ||
            (l.source === targetId && l.target === sourceId)
    );
    if (alreadyExists) {
        showToast(`Un lien existe déjà entre ${sourceId} et ${targetId}.`, 'info');
        return;
    }

    links.push({ id: nextLinkId(), source: sourceId, target: targetId });
    markDirty(true);
    renderLinksSvg();
    showToast(`Lien réseau créé : ${sourceId} ↔ ${targetId}`, 'success');
}

function removeLink(linkId) {
    if (editorState.isReadOnly) return;
    editorState.infra.definition.links = editorState.infra.definition.links.filter(
        (l) => l.id !== linkId
    );
    markDirty(true);
    renderLinksSvg();
}

function handleDeleteSelectedNode() {
    if (editorState.isReadOnly || !editorState.selectedNodeId) return;
    const nodeId = editorState.selectedNodeId;
    editorState.infra.definition.nodes = editorState.infra.definition.nodes.filter(
        (n) => n.id !== nodeId
    );
    editorState.infra.definition.links = editorState.infra.definition.links.filter(
        (l) => l.source !== nodeId && l.target !== nodeId
    );
    editorState.selectedNodeId = null;
    markDirty(true);
    renderCanvas();
    renderInspector();
}

// --- Rendu du canevas (boîtes + câbles SVG) ---

function getNodeCenter(node) {
    const el = document.querySelector(`.canvas-node[data-node-id="${CSS.escape(node.id)}"]`);
    const w = el ? el.offsetWidth : NODE_WIDTH;
    const h = el ? el.offsetHeight : NODE_HEIGHT;
    return { x: node.x + w / 2, y: node.y + h / 2 };
}

function renderLinksSvg() {
    const svg = document.getElementById('links-svg');
    const nodesById = new Map(editorState.infra.definition.nodes.map((n) => [n.id, n]));

    let markup = '';
    for (const link of editorState.infra.definition.links) {
        const src = nodesById.get(link.source);
        const dst = nodesById.get(link.target);
        if (!src || !dst) continue;

        const p1 = getNodeCenter(src);
        const p2 = getNodeCenter(dst);
        const dx = Math.max(40, Math.abs(p2.x - p1.x) * 0.45);
        const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
        const midX = (p1.x + p2.x) / 2;
        const midY = (p1.y + p2.y) / 2;

        markup += `<path class="link-path" d="${d}"></path>`;
        if (!editorState.isReadOnly) {
            markup += `
                <g class="link-delete-group" data-link-id="${escapeHtml(link.id)}">
                    <circle class="link-delete-circle" cx="${midX}" cy="${midY}" r="9"></circle>
                    <text class="link-delete-text" x="${midX}" y="${midY}">×</text>
                </g>
            `;
        }
    }

    // Câble temporaire pendant que l'utilisateur tire un lien à la souris
    if (editorState.linkingFrom) {
        const src = nodesById.get(editorState.linkingFrom.sourceId);
        if (src) {
            const p1 = getNodeCenter(src);
            const p2 = { x: editorState.linkingFrom.cursorX, y: editorState.linkingFrom.cursorY };
            const dx = Math.max(30, Math.abs(p2.x - p1.x) * 0.4);
            const d = `M ${p1.x} ${p1.y} C ${p1.x + dx} ${p1.y}, ${p2.x - dx} ${p2.y}, ${p2.x} ${p2.y}`;
            markup += `<path class="link-path temp" d="${d}"></path>`;
        }
    }

    svg.innerHTML = markup;
    svg.querySelectorAll('.link-delete-group').forEach((g) => {
        g.addEventListener('click', (event) => {
            event.stopPropagation();
            removeLink(g.dataset.linkId);
        });
    });
}

function renderCanvas() {
    const layer = document.getElementById('nodes-layer');
    const nodes = editorState.infra.definition.nodes || [];
    document.getElementById('canvas-empty-hint').hidden = nodes.length > 0;

    layer.innerHTML = nodes
        .map((node) => {
            const meta = MODULE_META[node.module_type] || { icon: '📦' };
            const rtNode = getRuntimeNode(node.id);
            const isRunning = rtNode && rtNode.state === 'running';
            const ipDisplay = rtNode?.ip_address || node.config?.ip_address || 'IP auto';
            const selectedClass = editorState.selectedNodeId === node.id ? 'selected' : '';
            const readonlyClass = editorState.isReadOnly ? 'readonly' : '';

            return `
                <div class="canvas-node type-${escapeHtml(node.module_type)} ${selectedClass} ${readonlyClass}"
                     data-node-id="${escapeHtml(node.id)}"
                     style="left: ${node.x}px; top: ${node.y}px;">
                    <div class="node-head">
                        <span class="node-title">${meta.icon} ${escapeHtml(node.name)}</span>
                        <span class="status-dot ${isRunning ? 'running' : ''}"
                              title="${isRunning ? 'Démarré' : 'Arrêté'}"></span>
                    </div>
                    <div class="node-sub">
                        <code>${escapeHtml(node.id)}</code>
                        <span>${escapeHtml(node.module_type)}</span>
                    </div>
                    <div class="node-ip">${escapeHtml(ipDisplay)}</div>
                    ${
                        editorState.isReadOnly
                            ? ''
                            : '<div class="node-connect-handle" title="Tirer vers un autre module pour créer un lien réseau"></div>'
                    }
                </div>
            `;
        })
        .join('');

    layer.querySelectorAll('.canvas-node').forEach((nodeEl) => {
        const nodeId = nodeEl.dataset.nodeId;

        // Sélection & démarrage du glisser-déposer d'un nœud
        nodeEl.addEventListener('pointerdown', (event) => {
            if (event.target.classList.contains('node-connect-handle')) {
                return;
            }
            event.stopPropagation();
            editorState.selectedNodeId = nodeId;
            highlightSelectedNode();
            renderInspector();

            if (editorState.isReadOnly) return;
            const node = editorState.infra.definition.nodes.find((n) => n.id === nodeId);
            if (!node) return;
            const coords = getCanvasCoords(event.clientX, event.clientY);
            editorState.draggingNode = {
                nodeId,
                offsetX: coords.x - node.x,
                offsetY: coords.y - node.y,
            };
        });

        // Double-clic : prêt pour l'Étape 5 (terminal web / explorateur SQL / bureau KasmVNC)
        nodeEl.addEventListener('dblclick', (event) => {
            event.stopPropagation();
            editorState.selectedNodeId = nodeId;
            highlightSelectedNode();
            renderInspector();
            showToast(
                `Module « ${nodeId} » ouvert dans l'inspecteur (l'accès interactif direct par double-clic arrive à l'Étape 5).`,
                'info'
            );
        });

        // Poignée pour tirer un lien réseau
        const handle = nodeEl.querySelector('.node-connect-handle');
        if (handle) {
            handle.addEventListener('pointerdown', (event) => {
                event.stopPropagation();
                if (editorState.isReadOnly) return;
                const coords = getCanvasCoords(event.clientX, event.clientY);
                editorState.linkingFrom = {
                    sourceId: nodeId,
                    cursorX: coords.x,
                    cursorY: coords.y,
                };
                renderLinksSvg();
            });
        }
    });

    renderLinksSvg();
}

function highlightSelectedNode() {
    document.querySelectorAll('.canvas-node').forEach((el) => {
        el.classList.toggle('selected', el.dataset.nodeId === editorState.selectedNodeId);
    });
}

// --- Inspecteur de droite ---

function renderInspector() {
    const emptyEl = document.getElementById('inspector-empty');
    const contentEl = document.getElementById('inspector-content');
    const node = editorState.infra.definition.nodes.find(
        (n) => n.id === editorState.selectedNodeId
    );

    if (!node) {
        emptyEl.hidden = false;
        contentEl.hidden = true;
        return;
    }

    emptyEl.hidden = true;
    contentEl.hidden = false;

    const spec = getCatalogSpec(node.module_type);
    const rtNode = getRuntimeNode(node.id);
    const isRunning = rtNode && rtNode.state === 'running';

    document.getElementById('insp-type-label').textContent = spec ? spec.label : node.module_type;
    document.getElementById('insp-node-id').textContent = node.id;

    const rtBadge = document.getElementById('insp-runtime-badge');
    rtBadge.textContent = rtNode ? rtNode.state : 'stopped';
    rtBadge.className = `badge ${isRunning ? 'badge-running' : 'badge-status'}`;

    document.getElementById('insp-ip').textContent = rtNode?.ip_address || '—';
    const portRow = document.getElementById('insp-port-row');
    if (rtNode?.host_port) {
        portRow.hidden = false;
        document.getElementById('insp-port').textContent = `127.0.0.1:${rtNode.host_port}`;
    } else {
        portRow.hidden = true;
    }

    const controlsEl = document.getElementById('insp-node-controls');
    if (!editorState.isReadOnly && editorState.runtime?.status === 'running') {
        controlsEl.innerHTML = isRunning
            ? `<button type="button" class="btn-warn btn-sm" onclick="handleStopNode('${escapeHtml(node.id)}')">Arrêter ce module</button>`
            : `<button type="button" class="btn-success btn-sm" onclick="handleStartNode('${escapeHtml(node.id)}')">Démarrer${spec?.on_demand ? ' (à la demande)' : ''}</button>`;
    } else {
        controlsEl.innerHTML = '';
    }

    const nameInput = document.getElementById('insp-name');
    nameInput.value = node.name;
    nameInput.disabled = editorState.isReadOnly;

    const pgBox = document.getElementById('insp-postgres-fields');
    const linuxBox = document.getElementById('insp-linux-fields');
    const cfg = node.config || {};
    const files = node.files || {};

    if (node.module_type === 'postgres') {
        pgBox.hidden = false;
        linuxBox.hidden = true;
        setInputValue('insp-db-name', cfg.db_name ?? 'app_db');
        setInputValue('insp-db-user', cfg.db_user ?? 'postgres');
        setInputValue('insp-db-password', cfg.db_password ?? 'password');
        setInputValue('insp-db-ip', cfg.ip_address ?? '');
        setInputValue('insp-init-sql', files['init.sql'] ?? '');
    } else {
        pgBox.hidden = true;
        linuxBox.hidden = false;
        setInputValue('insp-hostname', cfg.hostname ?? node.id);
        setInputValue('insp-linux-ip', cfg.ip_address ?? '');
        setInputValue('insp-gateway', cfg.gateway ?? '');
        setInputValue('insp-workspace-file', files['workspace/consigne.txt'] ?? '');
    }

    document.getElementById('btn-delete-node').hidden = editorState.isReadOnly;
}

function setInputValue(elementId, value) {
    const el = document.getElementById(elementId);
    el.value = value;
    el.disabled = editorState.isReadOnly;
}

function bindInspectorInputs() {
    const updateSelected = (updater) => {
        if (editorState.isReadOnly || !editorState.selectedNodeId) return;
        const node = editorState.infra.definition.nodes.find(
            (n) => n.id === editorState.selectedNodeId
        );
        if (!node) return;
        node.config = node.config || {};
        node.files = node.files || {};
        updater(node);
        markDirty(true);
        renderCanvas();
    };

    document.getElementById('insp-name').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.name = e.target.value;
        });
    });

    document.getElementById('insp-db-name').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.db_name = e.target.value;
        });
    });
    document.getElementById('insp-db-user').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.db_user = e.target.value;
        });
    });
    document.getElementById('insp-db-password').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.db_password = e.target.value;
        });
    });
    document.getElementById('insp-db-ip').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.ip_address = e.target.value.trim();
        });
    });
    document.getElementById('insp-init-sql').addEventListener('input', (e) => {
        updateSelected((n) => {
            if (e.target.value.trim()) {
                n.files['init.sql'] = e.target.value;
            } else {
                delete n.files['init.sql'];
            }
        });
    });

    document.getElementById('insp-hostname').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.hostname = e.target.value;
        });
    });
    document.getElementById('insp-linux-ip').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.ip_address = e.target.value.trim();
        });
    });
    document.getElementById('insp-gateway').addEventListener('input', (e) => {
        updateSelected((n) => {
            n.config.gateway = e.target.value.trim();
        });
    });
    document.getElementById('insp-workspace-file').addEventListener('input', (e) => {
        updateSelected((n) => {
            if (e.target.value.trim()) {
                n.files['workspace/consigne.txt'] = e.target.value;
            } else {
                delete n.files['workspace/consigne.txt'];
            }
        });
    });
}

// --- Interactions globales sur le canevas (Drop, Drag, Tracé de liens) ---

function bindCanvasEvents() {
    const stage = document.getElementById('canvas-stage');

    // Déposer un module glissé depuis la palette
    stage.addEventListener('dragover', (event) => {
        if (editorState.isReadOnly) return;
        event.preventDefault();
        stage.classList.add('drag-over');
    });

    stage.addEventListener('dragleave', () => {
        stage.classList.remove('drag-over');
    });

    stage.addEventListener('drop', (event) => {
        stage.classList.remove('drag-over');
        if (editorState.isReadOnly) return;
        event.preventDefault();
        const modType = event.dataTransfer.getData('text/plain');
        if (!modType) return;
        const coords = getCanvasCoords(event.clientX, event.clientY);
        addNodeToCanvas(modType, coords.x - NODE_WIDTH / 2, coords.y - NODE_HEIGHT / 2);
    });

    // Clic dans le vide du canevas -> désélectionner
    stage.addEventListener('pointerdown', (event) => {
        if (event.target === stage || event.target.id === 'nodes-layer') {
            editorState.selectedNodeId = null;
            highlightSelectedNode();
            renderInspector();
        }
    });

    // Suivi du curseur pour déplacement d'un nœud ou tracé d'un lien
    window.addEventListener('pointermove', (event) => {
        if (editorState.draggingNode) {
            const { nodeId, offsetX, offsetY } = editorState.draggingNode;
            const node = editorState.infra.definition.nodes.find((n) => n.id === nodeId);
            if (!node) return;
            const coords = getCanvasCoords(event.clientX, event.clientY);
            node.x = Math.max(12, Math.round(coords.x - offsetX));
            node.y = Math.max(12, Math.round(coords.y - offsetY));

            const el = document.querySelector(`.canvas-node[data-node-id="${CSS.escape(nodeId)}"]`);
            if (el) {
                el.style.left = `${node.x}px`;
                el.style.top = `${node.y}px`;
            }
            markDirty(true);
            renderLinksSvg();
        } else if (editorState.linkingFrom) {
            const coords = getCanvasCoords(event.clientX, event.clientY);
            editorState.linkingFrom.cursorX = coords.x;
            editorState.linkingFrom.cursorY = coords.y;

            // Surligne le module cible sous la souris
            document.querySelectorAll('.canvas-node').forEach((el) => {
                const rect = el.getBoundingClientRect();
                const isOver =
                    event.clientX >= rect.left &&
                    event.clientX <= rect.right &&
                    event.clientY >= rect.top &&
                    event.clientY <= rect.bottom &&
                    el.dataset.nodeId !== editorState.linkingFrom.sourceId;
                el.classList.toggle('link-target-highlight', isOver);
            });
            renderLinksSvg();
        }
    });

    window.addEventListener('pointerup', (event) => {
        if (editorState.draggingNode) {
            editorState.draggingNode = null;
        }
        if (editorState.linkingFrom) {
            const sourceId = editorState.linkingFrom.sourceId;
            let targetId = null;
            document.querySelectorAll('.canvas-node').forEach((el) => {
                el.classList.remove('link-target-highlight');
                const rect = el.getBoundingClientRect();
                if (
                    event.clientX >= rect.left &&
                    event.clientX <= rect.right &&
                    event.clientY >= rect.top &&
                    event.clientY <= rect.bottom &&
                    el.dataset.nodeId !== sourceId
                ) {
                    targetId = el.dataset.nodeId;
                }
            });
            editorState.linkingFrom = null;
            if (targetId) {
                addLink(sourceId, targetId);
            } else {
                renderLinksSvg();
            }
        }
    });
}

// --- Actions API (Sauvegarder, Démarrer/Arrêter, Exporter) ---

async function handleSave() {
    if (editorState.isReadOnly) return;
    hideToast();
    try {
        const updated = await apiFetch(`/infrastructures/${editorState.infraId}`, {
            method: 'PUT',
            body: JSON.stringify({
                name: editorState.infra.name,
                description: editorState.infra.description,
                definition: editorState.infra.definition,
            }),
        });
        editorState.infra = updated;
        markDirty(false);
        renderTopbar();
        renderCanvas();
        renderInspector();
        showToast('Infrastructure sauvegardée !', 'success');
    } catch (error) {
        showToast(`Erreur de sauvegarde : ${error.message}`, 'error');
    }
}

async function refreshRuntimeStatus() {
    try {
        editorState.runtime = await apiFetch(`/infrastructures/${editorState.infraId}/status`, {
            method: 'GET',
        });
        renderTopbar();
        renderCanvas();
        renderInspector();
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleStartInfra() {
    if (editorState.isReadOnly) return;
    if (editorState.isDirty) {
        await handleSave();
        if (editorState.isDirty) return; // Échec de sauvegarde
    }
    showToast('Démarrage du réseau isolé et des conteneurs Docker...', 'info');
    try {
        editorState.runtime = await apiFetch(`/infrastructures/${editorState.infraId}/start`, {
            method: 'POST',
        });
        editorState.infra.status = editorState.runtime.status;
        renderTopbar();
        renderCanvas();
        renderInspector();
        showToast(
            `Infrastructure démarrée sur ${editorState.runtime.network_name} (${editorState.runtime.subnet || 'IPAM'}).`,
            'success'
        );
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleStopInfra() {
    if (editorState.isReadOnly) return;
    showToast('Arrêt des conteneurs et nettoyage du réseau...', 'info');
    try {
        editorState.runtime = await apiFetch(`/infrastructures/${editorState.infraId}/stop`, {
            method: 'POST',
        });
        editorState.infra.status = editorState.runtime.status;
        renderTopbar();
        renderCanvas();
        renderInspector();
        showToast('Infrastructure arrêtée.', 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleStartNode(nodeId) {
    if (editorState.isReadOnly) return;
    showToast(`Démarrage du module ${nodeId}...`, 'info');
    try {
        editorState.runtime = await apiFetch(
            `/infrastructures/${editorState.infraId}/nodes/${nodeId}/start`,
            { method: 'POST' }
        );
        renderTopbar();
        renderCanvas();
        renderInspector();
        showToast(`Module « ${nodeId} » démarré.`, 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleStopNode(nodeId) {
    if (editorState.isReadOnly) return;
    try {
        editorState.runtime = await apiFetch(
            `/infrastructures/${editorState.infraId}/nodes/${nodeId}/stop`,
            { method: 'POST' }
        );
        renderTopbar();
        renderCanvas();
        renderInspector();
        showToast(`Module « ${nodeId} » arrêté.`, 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

async function handleExport() {
    if (editorState.isDirty && !editorState.isReadOnly) {
        showToast('Pensez à sauvegarder avant d\'exporter pour inclure vos dernières modifications.', 'info');
    }
    try {
        const filename = await apiDownload(
            `/infrastructures/${editorState.infraId}/export`,
            `infrastructure-${editorState.infraId}.zip`
        );
        showToast(`Archive « ${filename} » téléchargée.`, 'success');
    } catch (error) {
        showToast(error.message, 'error');
    }
}

// --- Initialisation ---

window.addEventListener('beforeunload', (event) => {
    if (editorState.isDirty) {
        event.preventDefault();
        event.returnValue = '';
    }
});

window.addEventListener('DOMContentLoaded', async () => {
    const user = await requireAuth();
    if (!user) return;

    const params = new URLSearchParams(window.location.search);
    const hashId = window.location.hash.replace(/^#/, '').trim();
    const idParam = Number(params.get('id') || hashId);
    if (!idParam || Number.isNaN(idParam)) {
        window.location.href = 'dashboard.html';
        return;
    }
    editorState.infraId = idParam;

    bindInspectorInputs();
    bindCanvasEvents();

    try {
        const [modules, infra, runtime] = await Promise.all([
            apiFetch('/modules', { method: 'GET' }),
            apiFetch(`/infrastructures/${idParam}`, { method: 'GET' }),
            apiFetch(`/infrastructures/${idParam}/status`, { method: 'GET' }),
        ]);

        editorState.modules = modules;
        editorState.infra = infra;
        editorState.runtime = runtime;
        editorState.isReadOnly = infra.access_level !== 'owner';

        renderTopbar();
        renderPalette();
        renderCanvas();
        renderInspector();
    } catch (error) {
        showToast(`Impossible de charger l'infrastructure : ${error.message}`, 'error');
    }
});
