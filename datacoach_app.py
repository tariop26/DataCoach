import streamlit as st
import requests
import pandas as pd
import authentification as strava_auth

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Run Coach", page_icon="🏃‍♂️", layout="centered")

# --- GESTION DES SECRETS (CLÉS API) ---
CLIENT_ID = None
CLIENT_SECRET = None

try:
    if "STRAVA_CLIENT_ID" in st.secrets:
        CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
        CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
except Exception:
    pass

# Mode dégradé si pas de secrets
if not CLIENT_ID or not CLIENT_SECRET:
    st.sidebar.warning("⚠️ Mode Configuration")
    CLIENT_ID = st.sidebar.text_input("Strava Client ID")
    CLIENT_SECRET = st.sidebar.text_input("Strava Client Secret", type="password")

# --- DÉTECTION DE L'ENVIRONNEMENT ---
if "localhost" in st.query_params.get("base_url", "") or not st.secrets:
    REDIRECT_URI = "http://localhost:8501"
else:
    REDIRECT_URI = "https://datacoach.streamlit.app/"

# --- GESTION DE LA SESSION ---
if "access_token" not in st.session_state:
    st.session_state.access_token = None

# --- UI : HEADER ---
st.title("🏃‍♂️ Smart Run Coach")
st.write("Ton analyseur de performance simplifié.")

# --- LOGIQUE PRINCIPALE ---

# 1. Si on n'est pas connecté
if not st.session_state.access_token:
    query_params = st.query_params
    auth_code = query_params.get("code")

    if auth_code:
        # Retour de Strava avec le code
        with st.spinner("Connexion à Strava en cours..."):
            if CLIENT_ID and CLIENT_SECRET:
                token_response = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, auth_code)
                
                if token_response:
                    st.session_state.access_token = token_response.get("access_token")
                    st.session_state.refresh_token = token_response.get("refresh_token")
                    st.session_state.athlete = token_response.get("athlete")
                    st.success("Connexion réussie !")
                    
                    # --- CORRECTION CRUCIALE ICI ---
                    # On nettoie l'URL pour ne pas réutiliser le code au prochain rafraîchissement
                    st.query_params.clear()
                    st.rerun()
                else:
                    # Si le code est invalide (déjà utilisé), on nettoie aussi pour sortir de la boucle d'erreur
                    st.query_params.clear()
                    st.error("Le lien de connexion a expiré. Veuillez cliquer à nouveau sur le bouton ci-dessous.")
                    if st.button("Réessayer"):
                        st.rerun()
            else:
                st.error("Clés API manquantes.")
    else:
        # Affichage du bouton de connexion
        if CLIENT_ID and CLIENT_SECRET:
            login_url = strava_auth.get_login_url(CLIENT_ID, REDIRECT_URI)
            st.link_button("Se connecter avec Strava", login_url, type="primary")
        else:
            st.info("👈 Veuillez configurer l'application dans la barre latérale.")

# 2. Si on est connecté (DASHBOARD)
else:
    athlete = st.session_state.athlete
    st.divider()
    
    if athlete:
        st.subheader(f"Bonjour {athlete.get('firstname', 'Coureur')} ! 👋")
    
    # Appel API Strava
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"per_page": 10}
    
    response = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
    
    if response.status_code == 200:
        activities = response.json()
        
        if activities:
            df = pd.json_normalize(activities)
            
            st.info("💡 **Analyse Flash :**")
            
            if 'distance' in df.columns:
                total_km = (df['distance'].sum() / 1000).round(1)
                st.metric(label="Total Km (10 dernières sorties)", value=f"{total_km} km")
            
            # Affichage du tableau épuré
            cols_dispo = [c for c in ['name', 'moving_time', 'start_date_local', 'average_heartrate'] if c in df.columns]
            if 'distance' in df.columns:
                df['Km'] = (df['distance'] / 1000).round(2)
                cols_dispo.insert(1, 'Km')
            
            st.dataframe(df[cols_dispo], use_container_width=True)
            
            if st.button("Se déconnecter"):
                st.session_state.clear()
                st.rerun()
        else:
            st.warning("Aucune activité trouvée.")
            
    else:
        # Gestion de l'expiration du token (erreur 401)
        if response.status_code == 401:
            st.warning("Session expirée, reconnexion automatique...")
            st.session_state.clear()
            st.rerun()
        else:
            st.error(f"Erreur connexion Strava (Code {response.status_code}).")
            if st.button("Réessayer"):
                st.session_state.clear()
                st.rerun()
