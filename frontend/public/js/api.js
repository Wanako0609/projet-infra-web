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
