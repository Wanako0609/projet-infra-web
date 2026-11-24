const API_BASE_URL = 'http://localhost:8000/api';

function extractErrorMessage(errorPayload) {
    if (!errorPayload) return 'Erreur lors de la requête';
    if (typeof errorPayload.detail === 'string') return errorPayload.detail;
    if (Array.isArray(errorPayload.detail) && errorPayload.detail.length > 0) {
        return errorPayload.detail.map((item) => item.msg || JSON.stringify(item)).join(' ; ');
    }
    return 'Erreur lors de la requête';
}

async function apiFetch(endpoint, options = {}) {
    const token = localStorage.getItem('access_token');
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Erreur réseau' }));
        throw new Error(extractErrorMessage(error));
    }

    // Les routes DELETE renvoient 204 No Content (corps vide)
    if (response.status === 204) {
        return null;
    }

    return response.json();
}

// Envoi multipart/form-data (upload de fichier .zip) : ne pas fixer Content-Type à la main
async function apiUpload(endpoint, formData) {
    const token = localStorage.getItem('access_token');
    const headers = {};
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'POST',
        headers,
        body: formData,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Erreur lors de l\'import' }));
        throw new Error(extractErrorMessage(error));
    }

    return response.json();
}

// Téléchargement binaire authentifié (un lien <a href> ne peut pas envoyer le header Bearer)
async function apiDownload(endpoint, fallbackFilename = 'infrastructure.zip') {
    const token = localStorage.getItem('access_token');
    const headers = {};
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        method: 'GET',
        headers,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Erreur lors du téléchargement' }));
        throw new Error(extractErrorMessage(error));
    }

    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : fallbackFilename;

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    return filename;
}
