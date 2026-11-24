// Construit le bon chemin vers une page de /pages/ quel que soit l'emplacement actuel
function getPageUrl(pageName) {
    return window.location.pathname.includes('/pages/') ? pageName : `pages/${pageName}`;
}

// Vérifie rapidement si un token est présent dans le navigateur
function isAuthenticated() {
    return Boolean(localStorage.getItem('access_token'));
}

// Récupère le profil de l'utilisateur connecté depuis l'API (valide réellement le JWT)
async function fetchCurrentUser() {
    return apiFetch('/users/me', { method: 'GET' });
}

// Protège une page : vérifie le token côté serveur, sinon redirige vers la connexion
async function requireAuth() {
    if (!isAuthenticated()) {
        window.location.href = getPageUrl('login.html');
        return null;
    }

    try {
        return await fetchCurrentUser();
    } catch (error) {
        localStorage.removeItem('access_token');
        window.location.href = getPageUrl('login.html');
        return null;
    }
}

// Inscription d'un nouvel utilisateur
async function registerUser(username, email, password) {
    const response = await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, email, password }),
    });
    return response;
}

// Connexion de l'utilisateur
async function loginUser(username, password) {
    // FastAPI OAuth2PasswordRequestForm attend un corps "application/x-www-form-urlencoded"
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: formData,
    });

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: 'Identifiants incorrects' }));
        throw new Error(error.detail || 'Identifiants incorrects');
    }

    const data = await response.json();
    localStorage.setItem('access_token', data.access_token);
    window.location.href = getPageUrl('dashboard.html');
}

function logout() {
    localStorage.removeItem('access_token');
    window.location.href = getPageUrl('login.html');
}
