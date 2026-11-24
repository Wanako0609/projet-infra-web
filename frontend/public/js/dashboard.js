// Logique du tableau de bord : catalogue, Mes infrastructures, Partagées avec moi

let state = {
    user: null,
    modules: [],
    owned: [],
    shared: [],
    selectedInfra: null,
    selectedRuntime: null,
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

function showDashboardMessage(message, type = 'success') {
    const el = document.getElementById('dashboard-message');
    el.textContent = message;
    el.className = `form-message ${type}`;
    el.hidden = false;
}

function clearDashboardMessage() {
    const el = document.getElementById('dashboard-message');
    el.hidden = true;
}

function buildSampleDefinition() {
    return {
        schema_version: '1.0',
        nodes: [
            {
                id: 'db-1',
                module_type: 'postgres',
                name: 'Base Clients',
                x: 140,
                y: 180,
                config: {
                    db_name: 'clients_db',
                    db_user: 'admin',
                    db_password: 'tp_password',
                    ip_address: '10.10.0.10',
                },
                files: {
                    'init.sql':
                        "CREATE TABLE clients (id SERIAL PRIMARY KEY, nom TEXT);\nINSERT INTO clients (nom) VALUES ('Alice'), ('Bob');",
                },
            },
            {
                id: 'pc-1',
                module_type: 'linux_net',
                name: 'Poste Étudiant',
                x: 460,
                y: 180,
                config: {
                    hostname: 'poste-etudiant',
                    ip_address: '10.10.0.20',
                    gateway: '',
                },
                files: {
                    'workspace/consigne.txt':
                        'Objectif : interroger la base clients_db sur 10.10.0.10.',
                },
            },
        ],
        links: [{ id: 'link-1', source: 'pc-1', target: 'db-1' }],
    };
}

function renderCatalog() {
    const container = document.getElementById('module-catalog-list');
    container.innerHTML = state.modules
        .map(
            (mod) => `
            <article class="card catalog-card">
                <div class="card-header">
                    <strong>${escapeHtml(mod.label)}</strong>
                    <span class="badge badge-neutral">${escapeHtml(mod.category_label)}</span>
                </div>
                <p class="card-desc">${escapeHtml(mod.description)}</p>
                <div class="card-meta">
                    <span>Type : <code>${escapeHtml(mod.type)}</code></span>
                    <span>~${mod.memory_mb} Mo</span>
                    ${mod.on_demand ? '<span class="badge badge-warn">À la demande</span>' : ''}
                </div>
            </article>
        `
        )
        .join('');
}

function renderOwnedInfrastructures() {
    const container = document.getElementById('owned-infras-list');
    if (state.owned.length === 0) {
        container.innerHTML =
            '<p class="empty-state">Aucune infrastructure personnelle pour le moment. Créez-en une ci-dessus !</p>';
        return;
    }

    container.innerHTML = state.owned
        .map((infra) => {
            const nodeCount = infra.definition?.nodes?.length || 0;
            const linkCount = infra.definition?.links?.length || 0;
            const sharesHtml =
                infra.shares.length === 0
                    ? '<span class="muted">Non partagée</span>'
                    : infra.shares
                          .map(
                              (share) => `
                        <span class="share-pill">
                            ${escapeHtml(share.username)} (lecture seule)
                            <button type="button" class="pill-remove" title="Révoquer le partage"
                                onclick="handleRevokeShare(${infra.id}, ${share.user_id})">×</button>
                        </span>
                    `
                          )
                          .join('');

            const isRunning = infra.status === 'running';
            return `
                <article class="card infra-card">
                    <div class="card-header">
                        <h4>${escapeHtml(infra.name)}</h4>
                        <span class="badge ${isRunning ? 'badge-running' : 'badge-status'}">${escapeHtml(infra.status)}</span>
                    </div>
                    <p class="card-desc">${escapeHtml(infra.description || 'Sans description')}</p>
                    <div class="card-meta">
                        <span>${nodeCount} module(s)</span>
                        <span>${linkCount} lien(s)</span>
                    </div>

                    <div class="shares-box">
                        <div class="shares-list"><strong>Partages :</strong> ${sharesHtml}</div>
                        <form class="share-form" onsubmit="handleShare(event, ${infra.id})">
                            <input type="text" name="username" placeholder="Partager avec (pseudo)..." required>
                            <button type="submit" class="btn-secondary">Partager</button>
                        </form>
                    </div>

                    <div class="card-actions">
                        <a class="btn-primary btn-inline btn-link" href="editor.html?id=${infra.id}">
                            Ouvrir l'atelier
                        </a>
                        ${
                            isRunning
                                ? `<button type="button" class="btn-warn" onclick="handleStopInfrastructure(${infra.id})">Arrêter</button>`
                                : `<button type="button" class="btn-success" onclick="handleStartInfrastructure(${infra.id})">Démarrer</button>`
                        }
                        <button type="button" class="btn-secondary" onclick="inspectInfrastructure(${infra.id})">
                            Inspecter
                        </button>
                        <button type="button" class="btn-secondary" onclick="handleExportInfrastructure(${infra.id})">
                            Exporter (.zip)
                        </button>
                        <button type="button" class="btn-danger" onclick="handleDeleteInfrastructure(${infra.id})">
                            Supprimer
                        </button>
                    </div>
                </article>
            `;
        })
        .join('');
}

function renderSharedInfrastructures() {
    const container = document.getElementById('shared-infras-list');
    if (state.shared.length === 0) {
        container.innerHTML =
            '<p class="empty-state">Aucune infrastructure ne vous a encore été partagée.</p>';
        return;
    }

    container.innerHTML = state.shared
        .map((infra) => {
            const nodeCount = infra.definition?.nodes?.length || 0;
            const linkCount = infra.definition?.links?.length || 0;
            return `
                <article class="card infra-card">
                    <div class="card-header">
                        <h4>${escapeHtml(infra.name)}</h4>
                        <span class="badge badge-readonly">Lecture seule</span>
                    </div>
                    <p class="card-desc">${escapeHtml(infra.description || 'Sans description')}</p>
                    <div class="card-meta">
                        <span>Par <strong>${escapeHtml(infra.owner_username)}</strong></span>
                        <span>${nodeCount} module(s)</span>
                        <span>${linkCount} lien(s)</span>
                    </div>
                    <div class="card-actions">
                        <a class="btn-primary btn-inline btn-link" href="editor.html?id=${infra.id}">
                            Ouvrir (lecture seule)
                        </a>
                        <button type="button" class="btn-secondary" onclick="inspectInfrastructure(${infra.id})">
                            Consulter
                        </button>
                        <button type="button" class="btn-secondary" onclick="handleExportInfrastructure(${infra.id})">
                            Exporter (.zip)
                        </button>
                    </div>
                </article>
            `;
        })
        .join('');
}

function renderSelectedInfrastructure() {
    const panel = document.getElementById('infra-detail-panel');
    const infra = state.selectedInfra;
    if (!infra) {
        panel.hidden = true;
        return;
    }

    panel.hidden = false;
    document.getElementById('detail-title').textContent = infra.name;
    const accessBadge = document.getElementById('detail-access-badge');
    if (infra.access_level === 'owner') {
        accessBadge.textContent = 'Propriétaire (lecture / écriture)';
        accessBadge.className = 'badge badge-owner';
    } else {
        accessBadge.textContent = `Lecture seule (partagée par ${infra.owner_username})`;
        accessBadge.className = 'badge badge-readonly';
    }

    const runtimeBox = document.getElementById('detail-runtime-box');
    const rt = state.selectedRuntime;
    if (!rt) {
        runtimeBox.innerHTML = '<p class="muted">Chargement de l\'état Docker...</p>';
    } else if (!rt.docker_available) {
        runtimeBox.innerHTML =
            '<p class="form-message error">Démon Docker indisponible. Vérifiez que Docker tourne pour piloter cette infrastructure.</p>';
    } else {
        const isOwner = infra.access_level === 'owner';
        const netInfo = rt.network_name
            ? `Réseau isolé : <code>${escapeHtml(rt.network_name)}</code> (${escapeHtml(rt.subnet || 'IPAM auto')})`
            : 'Réseau isolé : inactif (infrastructure arrêtée)';

        const rows = (rt.nodes || [])
            .map((node) => {
                const running = node.state === 'running';
                const portNote = node.host_port
                    ? `<span class="badge badge-neutral">Bureau local : 127.0.0.1:${node.host_port}</span>`
                    : '';
                let nodeBtn = '';
                if (isOwner && rt.status === 'running') {
                    nodeBtn = running
                        ? `<button type="button" class="btn-warn btn-sm" onclick="handleStopNode(${infra.id}, '${escapeHtml(node.node_id)}')">Arrêter</button>`
                        : `<button type="button" class="btn-success btn-sm" onclick="handleStartNode(${infra.id}, '${escapeHtml(node.node_id)}')">Démarrer${node.on_demand ? ' (à la demande)' : ''}</button>`;
                }
                return `
                    <div class="runtime-node-row">
                        <div>
                            <strong>${escapeHtml(node.name)}</strong>
                            <code>${escapeHtml(node.node_id)}</code>
                            <span class="muted">(${escapeHtml(node.module_type)})</span>
                            ${node.on_demand ? '<span class="badge badge-warn">À la demande</span>' : ''}
                        </div>
                        <div class="runtime-node-meta">
                            <span class="badge ${running ? 'badge-running' : 'badge-status'}">${escapeHtml(node.state)}</span>
                            <span>IP : <code>${escapeHtml(node.ip_address || '—')}</code></span>
                            ${portNote}
                            ${nodeBtn}
                        </div>
                    </div>
                `;
            })
            .join('');

        runtimeBox.innerHTML = `
            <div class="runtime-header">
                <strong>État Docker :</strong>
                <span class="badge ${rt.status === 'running' ? 'badge-running' : 'badge-status'}">${escapeHtml(rt.status)}</span>
                <span class="muted">${netInfo}</span>
            </div>
            <div class="runtime-nodes-list">${rows || '<p class="muted">Aucun module dans cette infrastructure.</p>'}</div>
        `;
    }

    document.getElementById('detail-json').textContent = JSON.stringify(infra.definition, null, 2);
}

async function refreshSelectedStatus() {
    if (!state.selectedInfra) return;
    try {
        state.selectedRuntime = await apiFetch(`/infrastructures/${state.selectedInfra.id}/status`, {
            method: 'GET',
        });
        renderSelectedInfrastructure();
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function refreshInfrastructures() {
    const data = await apiFetch('/infrastructures', { method: 'GET' });
    state.owned = data.owned || [];
    state.shared = data.shared || [];
    renderOwnedInfrastructures();
    renderSharedInfrastructures();

    // Si une infra était ouverte dans le panneau de détail, on la rafraîchit
    if (state.selectedInfra) {
        const all = [...state.owned, ...state.shared];
        state.selectedInfra = all.find((item) => item.id === state.selectedInfra.id) || null;
        if (!state.selectedInfra) {
            state.selectedRuntime = null;
        }
        renderSelectedInfrastructure();
    }
}

async function inspectInfrastructure(infraId) {
    clearDashboardMessage();
    try {
        const [infra, runtime] = await Promise.all([
            apiFetch(`/infrastructures/${infraId}`, { method: 'GET' }),
            apiFetch(`/infrastructures/${infraId}/status`, { method: 'GET' }),
        ]);
        state.selectedInfra = infra;
        state.selectedRuntime = runtime;
        renderSelectedInfrastructure();
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

function closeDetailPanel() {
    state.selectedInfra = null;
    state.selectedRuntime = null;
    renderSelectedInfrastructure();
}

async function handleStartInfrastructure(infraId) {
    clearDashboardMessage();
    showDashboardMessage('Démarrage du réseau isolé et des conteneurs Docker...');
    try {
        const runtime = await apiFetch(`/infrastructures/${infraId}/start`, { method: 'POST' });
        await refreshInfrastructures();
        const found = state.owned.find((item) => item.id === infraId);
        if (found) {
            state.selectedInfra = found;
            state.selectedRuntime = runtime;
            renderSelectedInfrastructure();
        }
        showDashboardMessage(`Infrastructure démarrée sur ${runtime.network_name} (${runtime.subnet || 'IPAM'}).`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleStopInfrastructure(infraId) {
    clearDashboardMessage();
    showDashboardMessage('Arrêt des conteneurs et suppression du réseau isolé...');
    try {
        const runtime = await apiFetch(`/infrastructures/${infraId}/stop`, { method: 'POST' });
        await refreshInfrastructures();
        if (state.selectedInfra && state.selectedInfra.id === infraId) {
            state.selectedRuntime = runtime;
            renderSelectedInfrastructure();
        }
        showDashboardMessage('Infrastructure arrêtée et nettoyée.');
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleStartNode(infraId, nodeId) {
    clearDashboardMessage();
    showDashboardMessage(`Démarrage du module ${nodeId}...`);
    try {
        const runtime = await apiFetch(`/infrastructures/${infraId}/nodes/${nodeId}/start`, {
            method: 'POST',
        });
        state.selectedRuntime = runtime;
        await refreshInfrastructures();
        showDashboardMessage(`Module « ${nodeId} » démarré.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleStopNode(infraId, nodeId) {
    clearDashboardMessage();
    try {
        const runtime = await apiFetch(`/infrastructures/${infraId}/nodes/${nodeId}/stop`, {
            method: 'POST',
        });
        state.selectedRuntime = runtime;
        await refreshInfrastructures();
        showDashboardMessage(`Module « ${nodeId} » arrêté.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleCreateInfrastructure(event) {
    event.preventDefault();
    clearDashboardMessage();

    const name = document.getElementById('infra-name').value.trim();
    const description = document.getElementById('infra-description').value.trim();
    const withSample = document.getElementById('infra-with-sample').checked;

    const payload = {
        name,
        description,
        definition: withSample ? buildSampleDefinition() : { schema_version: '1.0', nodes: [], links: [] },
    };

    try {
        const created = await apiFetch('/infrastructures', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        event.target.reset();
        await refreshInfrastructures();
        state.selectedInfra = created;
        renderSelectedInfrastructure();
        showDashboardMessage(`Infrastructure « ${created.name} » créée.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleExportInfrastructure(infraId) {
    clearDashboardMessage();
    try {
        const filename = await apiDownload(
            `/infrastructures/${infraId}/export`,
            `infrastructure-${infraId}.zip`
        );
        showDashboardMessage(`Archive « ${filename} » téléchargée.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleImportInfrastructure(event) {
    event.preventDefault();
    clearDashboardMessage();

    const fileInput = document.getElementById('import-file');
    const nameInput = document.getElementById('import-name');
    const file = fileInput.files[0];
    if (!file) {
        showDashboardMessage('Veuillez sélectionner un fichier .zip.', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    if (nameInput.value.trim()) {
        formData.append('name', nameInput.value.trim());
    }

    try {
        const imported = await apiUpload('/infrastructures/import', formData);
        event.target.reset();
        await refreshInfrastructures();
        state.selectedInfra = imported;
        renderSelectedInfrastructure();
        showDashboardMessage(`Infrastructure « ${imported.name} » importée avec succès.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleDeleteInfrastructure(infraId) {
    clearDashboardMessage();
    const infra = state.owned.find((item) => item.id === infraId);
    const infraName = infra ? infra.name : `#${infraId}`;
    if (!confirm(`Supprimer définitivement l'infrastructure « ${infraName} » ?`)) {
        return;
    }

    try {
        await apiFetch(`/infrastructures/${infraId}`, { method: 'DELETE' });
        await refreshInfrastructures();
        showDashboardMessage(`Infrastructure « ${infraName} » supprimée.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleShare(event, infraId) {
    event.preventDefault();
    clearDashboardMessage();
    const input = event.target.querySelector('input[name="username"]');
    const username = input.value.trim();
    if (!username) return;

    try {
        await apiFetch(`/infrastructures/${infraId}/shares`, {
            method: 'POST',
            body: JSON.stringify({ username }),
        });
        input.value = '';
        await refreshInfrastructures();
        showDashboardMessage(`Partagée en lecture seule avec ${username}.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

async function handleRevokeShare(infraId, userId) {
    clearDashboardMessage();
    const infra = state.owned.find((item) => item.id === infraId);
    const share = infra?.shares?.find((s) => s.user_id === userId);
    const username = share ? share.username : `#${userId}`;
    try {
        await apiFetch(`/infrastructures/${infraId}/shares/${userId}`, {
            method: 'DELETE',
        });
        await refreshInfrastructures();
        showDashboardMessage(`Partage révoqué pour ${username}.`);
    } catch (error) {
        showDashboardMessage(error.message, 'error');
    }
}

window.addEventListener('DOMContentLoaded', async () => {
    const user = await requireAuth();
    if (!user) return;
    state.user = user;

    document.getElementById('user-badge').textContent = `${user.username} (${user.email})`;
    document.getElementById('welcome-text').textContent =
        `Bienvenue ${user.username} ! Gérez vos infrastructures personnelles et consultez celles qui vous sont partagées.`;

    try {
        const [modules] = await Promise.all([
            apiFetch('/modules', { method: 'GET' }),
            refreshInfrastructures(),
        ]);
        state.modules = modules;
        renderCatalog();
    } catch (error) {
        showDashboardMessage(`Erreur de chargement : ${error.message}`, 'error');
    }
});
