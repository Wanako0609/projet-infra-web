// Inscription d'un nouvel utilisateur
async function registerUser(username, email, password) {
    try {
        const response = await apiFetch('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ username, email, password })
        });
        alert("Inscription réussie ! Vous pouvez maintenant vous connecter.");
        return response;
    } catch (error) {
        alert("Erreur d'inscription : " + error.message);
    }
}

// Connexion de l'utilisateur
async function loginUser(username, password) {
    try {
        // FastAPI OAuth2 requiert un format "form-urlencoded" pour le login
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: formData
        });

        if (!response.ok) {
            throw new Error("Identifiants incorrects");
        }

        const data = await response.json();
        
        // Sauvegarde du token JWT comme vous l'aviez prévu
        localStorage.setItem('access_token', data.access_token);
        alert("Connexion réussie !");
        
        // Redirection vers le tableau de bord
        window.location.href = '../pages/dashboard.html';
    } catch (error) {
        alert("Erreur de connexion : " + error.message);
    }
}

function logout() {
    // 1. Delete the token from the browser's local storage
    localStorage.removeItem('access_token');
    
    // 2. Redirect the user back to the login page
    window.location.href = 'login.html';
}