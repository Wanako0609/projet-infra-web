#!/bin/bash

echo "🐳 1/3 - Démarrage de la base de données (Docker)..."
docker compose up -d

echo "🐍 2/3 - Démarrage du Back-end (FastAPI)..."
cd backend
# Activation de l'environnement virtuel et lancement en arrière-plan (&)
source venv/bin/activate
uvicorn main:app --reload &
BACKEND_PID=$!
cd ..

echo "🌐 3/3 - Démarrage du Front-end (Node)..."
cd frontend
npm start &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ Projet en cours d'exécution !"
echo "➡️  Front-end (Interface) : http://localhost:3000"
echo "➡️  Back-end (API)        : http://127.0.0.1:8000"
echo "🔴 Appuyez sur CTRL+C pour tout arrêter."

# Cette commande intercepte le CTRL+C pour tuer les processus et arrêter Docker
trap "echo -e '\n🛑 Arrêt des services...'; kill $FRONTEND_PID $BACKEND_PID; docker compose stop; echo '✅ Tout est arrêté !'; exit" SIGINT SIGTERM

# Garde le script ouvert pour afficher les logs et attendre votre CTRL+C
wait