import requests
import streamlit as st

# Configuration des URLs de Strava
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

def get_login_url(client_id, redirect_uri):
    """
    Génère le lien OAuth2.
    """
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "approval_prompt": "force",
        "scope": "activity:read_all,profile:read_all"
    }
    url_parts = [f"{key}={value}" for key, value in params.items()]
    return f"{STRAVA_AUTH_URL}?" + "&".join(url_parts)

def exchange_code_for_token(client_id, client_secret, code):
    """
    Échange le code contre un token avec gestion d'erreur 403.
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    }
    
    try:
        response = requests.post(STRAVA_TOKEN_URL, data=payload)
        
        # Cas succès
        if response.status_code == 200:
            return response.json()
            
        # Cas limitation Strava (Le problème actuel)
        elif response.status_code == 403:
            st.error("⛔ ERREUR STRAVA 403 : Application bloquée.")
            st.warning("""
            Votre application est restreinte car elle n'a pas d'icône sur Strava Developers.
            1. Allez sur strava.com/settings/api
            2. Ajoutez une image (Icône) à votre application.
            3. Attendez 10 minutes.
            """)
            return None
            
        # Autres erreurs
        else:
            st.error(f"Erreur d'authentification ({response.status_code}) : {response.text}")
            return None
            
    except Exception as e:
        st.error(f"Erreur de connexion : {str(e)}")
        return None

def refresh_access_token(client_id, client_secret, refresh_token):
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    try:
        response = requests.post(STRAVA_TOKEN_URL, data=payload)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except:
        return None

# --- NOUVEAU : MODE DÉMO / BYPASS ---
def get_demo_token():
    """
    Permet de simuler une connexion réussie SANS Strava.
    Utile pour le développement quand l'API bloque.
    """
    return {
        "access_token": "demo_fake_token",
        "refresh_token": "demo_fake_refresh",
        "athlete": {
            "id": 12345,
            "firstname": "Jean-Michel",
            "lastname": "Testeur",
            "city": "Grenoble",
            "country": "France",
            "profile": "avatar_url"
        }
    }
