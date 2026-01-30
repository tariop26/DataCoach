import requests
import streamlit as st
import time

# Configuration des URLs de Strava
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

def get_login_url(client_id, redirect_uri):
    """
    Génère le lien sur lequel l'utilisateur doit cliquer pour se connecter à Strava.
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "approval_prompt": "force",
        "scope": "activity:read_all,profile:read_all"  # On demande la permission de lire les activités et le profil
    }
    # Construction de l'URL avec les paramètres
    url_parts = [f"{key}={value}" for key, value in params.items()]
    return f"{STRAVA_AUTH_URL}?" + "&".join(url_parts)

def exchange_code_for_token(client_id, client_secret, code):
    """
    Échange le code temporaire reçu après la connexion contre un Token d'accès durable.
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    }
    response = requests.post(STRAVA_TOKEN_URL, data=payload)
    if response.status_code == 200:
        return response.json()
    else:
        st.error(f"Erreur lors de l'authentification : {response.text}")
        return None

def refresh_access_token(client_id, client_secret, refresh_token):
    """
    Si le token est expiré (toutes les 6h), utilise le refresh_token pour en avoir un nouveau.
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    response = requests.post(STRAVA_TOKEN_URL, data=payload)
    if response.status_code == 200:
        return response.json()
    else:
        st.error("Impossible de rafraîchir le token.")
        return None