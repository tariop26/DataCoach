import streamlit as st
import requests
import pandas as pd
import authentification as strava_auth
import random
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Run Coach", page_icon="🏃‍♂️", layout="wide")

# --- FONCTIONS UTILITAIRES (CALCULS COACH) ---

def format_duration(seconds):
    """Transforme des secondes en format H:MM"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{int(hours)}h {int(minutes)}min"

def calculate_pace(speed_ms):
    """Transforme m/s en min/km"""
    if speed_ms == 0: return 0
    pace_min = 16.666666666667 / speed_ms
    minutes = int(pace_min)
    seconds = int((pace_min - minutes) * 60)
    return f"{minutes}'{seconds:02d}''/km"

def generate_mock_data():
    """Génère des données riches pour la démo"""
    data = []
    # On génère 30 activités sur les 60 derniers jours
    today = datetime.now()
    for i in range(30):
        date_act = today - timedelta(days=random.randint(0, 60))
        dist = random.randint(5000, 22000)
        # On simule : Plus c'est court, plus c'est intense (souvent)
        speed = random.uniform(2.5, 3.5) if dist > 15000 else random.uniform(3.0, 4.2)
        hr = random.randint(135, 175)
        
        data.append({
            "name": f"Sortie {'Longue' if dist > 15000 else 'Footing' if dist > 10000 else 'Fractionné'}",
            "distance": dist,
            "moving_time": int(dist / speed),
            "total_elevation_gain": random.randint(50, 500),
            "start_date_local": date_act.isoformat(),
            "average_heartrate": hr,
            "average_speed": speed,
            "type": "Run"
        })
    # On trie par date
    data.sort(key=lambda x: x['start_date_local'], reverse=True)
    return data

# --- GESTION DES SECRETS ---
CLIENT_ID = None
CLIENT_SECRET = None

try:
    if "STRAVA_CLIENT_ID" in st.secrets:
        CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
        CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
except Exception:
    pass

if not CLIENT_ID or not CLIENT_SECRET:
    st.sidebar.warning("⚠️ Mode Configuration")
    CLIENT_ID = st.sidebar.text_input("Strava Client ID")
    CLIENT_SECRET = st.sidebar.text_input("Strava Client Secret", type="password")

if "localhost" in st.query_params.get("base_url", "") or not st.secrets:
    REDIRECT_URI = "http://localhost:8501"
else:
    REDIRECT_URI = "http://localhost:8501"

if "access_token" not in st.session_state:
    st.session_state.access_token = None

# --- UI : HEADER ---
st.title("🏃‍♂️ Smart Run Coach")
st.markdown("**Ton analyseur de performance :** *On ne court pas plus, on court mieux.*")

# --- LOGIQUE PRINCIPALE ---

if not st.session_state.access_token:
    # ... (Logique de connexion inchangée, je condense pour la lisibilité)
    query_params = st.query_params
    auth_code = query_params.get("code")
    
    if auth_code:
        with st.spinner("Connexion au vestiaire..."):
            if CLIENT_ID and CLIENT_SECRET:
                token_response = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, auth_code)
                if token_response:
                    st.session_state.access_token = token_response.get("access_token")
                    st.session_state.athlete = token_response.get("athlete")
                    st.query_params.clear()
                    st.rerun()
    else:
        col1, col2 = st.columns(2)
        with col1:
            if CLIENT_ID and CLIENT_SECRET:
                login_url = strava_auth.get_login_url(CLIENT_ID, REDIRECT_URI)
                st.link_button("Se connecter avec Strava", login_url, type="primary")
            else:
                st.info("👈 Configurez les clés API")
        with col2:
            if st.button("🛠️ Mode Démo (Données Fictives)"):
                demo_data = strava_auth.get_demo_token()
                st.session_state.access_token = demo_data["access_token"]
                st.session_state.athlete = demo_data["athlete"]
                st.rerun()

else:
    # --- DASHBOARD DU COACH ---
    athlete = st.session_state.athlete
    
    if st.button("Se déconnecter", key="logout_top"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    
    # 1. RÉCUPÉRATION DES DONNÉES
    if st.session_state.access_token == "demo_fake_token":
        st.warning("⚠️ MODE DÉMO ACTIVÉ")
        activities = generate_mock_data()
        api_success = True
    else:
        headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
        # On demande 50 activités pour avoir de l'historique pour les graphs
        params = {"per_page": 50} 
        response = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
        if response.status_code == 200:
            activities = response.json()
            api_success = True
        else:
            api_success = False
            st.error(f"Erreur API : {response.status_code}")

    if api_success and activities:
        # 2. NETTOYAGE & ENRICHISSEMENT (PANDAS)
        df = pd.json_normalize(activities)
        
        # Conversion des dates
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        df['week_start'] = df['start_date_local'].dt.to_period('W').apply(lambda r: r.start_time)
        
        # Conversions unités
        df['distance_km'] = df['distance'] / 1000
        df['duration_h'] = df['moving_time'] / 3600
        
        # Calcul Allure (min/km) pour le graph
        df['pace_decimal'] = 16.666666666667 / df['average_speed'] # min/km en décimal pour le plot
        
        # --- BLOC KPI (Haut de page) ---
        st.subheader(f"👋 Analyse pour {athlete.get('firstname', 'Athlète')}")
        
        # On isole les 4 dernières semaines
        current_date = datetime.now()
        last_4_weeks = df[df['start_date_local'] > (current_date - timedelta(days=28))]
        
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        vol_total = last_4_weeks['distance_km'].sum()
        nb_sorties = len(last_4_weeks)
        avg_fc = last_4_weeks['average_heartrate'].mean() if 'average_heartrate' in last_4_weeks else 0
        
        kpi1.metric("Volume (30j)", f"{int(vol_total)} km")
        kpi2.metric("Sorties (30j)", f"{nb_sorties}")
        kpi3.metric("Cardio Moyen", f"{int(avg_fc)} bpm")
        
        # KPI Intelligent : Tendance Volume (Dernière semaine vs Moyenne 3 semaines avant)
        last_week = df[df['start_date_local'] > (current_date - timedelta(days=7))]
        vol_last_week = last_week['distance_km'].sum()
        avg_vol_prev = (vol_total - vol_last_week) / 3 if (vol_total - vol_last_week) > 0 else vol_last_week
        
        delta = ((vol_last_week - avg_vol_prev) / avg_vol_prev) * 100 if avg_vol_prev > 0 else 0
        kpi4.metric("Tendance Charge", f"{int(vol_last_week)} km", f"{int(delta)} %")

        # --- ONGLETS D'ANALYSE ---
        tab1, tab2, tab3 = st.tabs(["📊 Vue d'ensemble", "❤️ Cardio & Intensité", "📋 Journal"])

        with tab1:
            st.markdown("### Évolution du Volume")
            # Agrégation par semaine
            weekly_vol = df.groupby('week_start')['distance_km'].sum().reset_index()
            weekly_vol = weekly_vol.sort_values('week_start')
            
            # Graphique Plotly Barres
            fig_vol = px.bar(weekly_vol, x='week_start', y='distance_km',
                             title="Volume Hebdomadaire (km)",
                             labels={'week_start': 'Semaine', 'distance_km': 'Distance (km)'},
                             color='distance_km',
                             color_continuous_scale='Teal')
            st.plotly_chart(fig_vol, use_container_width=True)
            
            # Le Conseil du Coach basé sur le graph
            if delta > 20:
                st.warning("⚠️ **Alerte Surcharge :** Tu as augmenté ton volume de plus de 20% cette semaine. Attention au risque de blessure. Prévois une semaine 'light' la semaine prochaine.")
            elif delta < -20:
                st.info("ℹ️ **Récupération :** Semaine plus légère détectée. C'est bien d'assimiler l'entraînement !")
            else:
                st.success("✅ **Progression Saine :** Ton volume est stable et progressif. Continue !")

        with tab2:
            st.markdown("### Analyse de l'Intensité")
            col_graph, col_advice = st.columns([2, 1])
            
            with col_graph:
                # Scatter Plot : Distance vs Allure vs Cardio
                # Plus le point est gros, plus la sortie était longue
                # Plus le point est rouge, plus le cardio était haut
                if 'average_heartrate' in df.columns:
                    fig_scatter = px.scatter(df, x='start_date_local', y='pace_decimal',
                                             size='distance_km', color='average_heartrate',
                                             color_continuous_scale='RdYlGn_r', # Rouge en haut (dur), Vert en bas (cool)
                                             title="Distribution des séances (Taille = Distance)",
                                             labels={'pace_decimal': 'Allure (min/km)', 'start_date_local': 'Date', 'average_heartrate': 'BPM Moyen'})
                    
                    # Inverser l'axe Y pour que "plus rapide" soit en haut (optionnel, mais en running souvent on préfère voir l'allure baisse)
                    # Ici on laisse l'axe : 5 min/km est plus "haut" que 4 min/km graphiquement si on ne touche rien, c'est ok.
                    fig_scatter.update_layout(yaxis_autorange="reversed") # En haut = plus vite (chiffre plus petit)
                    st.plotly_chart(fig_scatter, use_container_width=True)
                else:
                    st.info("Pas de données cardiaques suffisantes pour ce graphique.")

            with col_advice:
                st.markdown("**Le regard du coach :**")
                st.write("Ce graphique permet de voir si ton entraînement est **polarisé**.")
                st.markdown("- **Points Verts :** Endurance fondamentale (Base foncière).")
                st.markdown("- **Points Rouges :** Séances au seuil ou VMA.")
                st.info("💡 Idéalement, 80% de tes points devraient être verts/jaunes et 20% oranges/rouges.")

        with tab3:
            st.markdown("### Historique des sorties")
            
            # Préparation tableau joli
            display_df = df[['name', 'start_date_local', 'distance_km', 'moving_time', 'average_speed']].copy()
            display_df['Date'] = display_df['start_date_local'].dt.strftime('%d/%m/%Y')
            display_df['Distance'] = display_df['distance_km'].round(2).astype(str) + " km"
            display_df['Durée'] = display_df['moving_time'].apply(format_duration)
            display_df['Allure'] = display_df['average_speed'].apply(calculate_pace)
            
            st.dataframe(display_df[['Date', 'name', 'Distance', 'Durée', 'Allure']], use_container_width=True, hide_index=True)

    else:
        st.info("Connecte-toi ou active le Mode Démo pour voir l'analyse.")
