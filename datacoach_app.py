import streamlit as st
import requests
import pandas as pd
import authentification as strava_auth
import random
import json
import os
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Run Coach", page_icon="🏃‍♂️", layout="wide")

# --- FONCTIONS UTILITAIRES (CALCULS COACH & STORAGE) ---

GOALS_FILE = "goals.json"

def load_goals():
    """Charge les objectifs depuis un fichier JSON local"""
    if os.path.exists(GOALS_FILE):
        try:
            with open(GOALS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_goal(athlete_id, goal_data):
    """Sauvegarde l'objectif d'un athlète"""
    goals = load_goals()
    goals[str(athlete_id)] = goal_data
    with open(GOALS_FILE, "w") as f:
        json.dump(goals, f)

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
    today = datetime.now()
    for i in range(30):
        date_act = today - timedelta(days=random.randint(0, 60))
        dist = random.randint(5000, 22000)
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
    data.sort(key=lambda x: x['start_date_local'], reverse=True)
    return data

# --- GESTION DES SECRETS ET CONFIGURATION URL ---
CLIENT_ID = None
CLIENT_SECRET = None
REDIRECT_URI = "http://localhost:8501" # Valeur par défaut

try:
    if "STRAVA_CLIENT_ID" in st.secrets:
        CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
        CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
    
    if "APP_URL" in st.secrets:
        REDIRECT_URI = st.secrets["APP_URL"]
except Exception:
    pass

if not CLIENT_ID or not CLIENT_SECRET:
    st.sidebar.warning("⚠️ Mode Configuration")
    CLIENT_ID = st.sidebar.text_input("Strava Client ID")
    CLIENT_SECRET = st.sidebar.text_input("Strava Client Secret", type="password")


# --- GESTION DE LA SESSION ---
if "access_token" not in st.session_state:
    st.session_state.access_token = None

# --- UI : HEADER ---
st.title("🏃‍♂️ Smart Run Coach")
st.markdown("**Ton analyseur de performance :** *On ne court pas plus, on court mieux.*")

# --- LOGIQUE PRINCIPALE ---

if not st.session_state.access_token:
    # 1. Vérification des paramètres URL (Code retour Strava)
    query_params = st.query_params
    auth_code = query_params.get("code")
    
    if auth_code:
        # Cas idéal : La redirection a fonctionné
        with st.spinner("Connexion au vestiaire..."):
            if CLIENT_ID and CLIENT_SECRET:
                token_response = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, auth_code)
                if token_response:
                    st.session_state.access_token = token_response.get("access_token")
                    st.session_state.athlete = token_response.get("athlete")
                    st.query_params.clear()
                    st.rerun()
    else:
        # 2. Affichage des boutons de connexion
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

        # 3. ZONE DE DÉPANNAGE (Uniquement si on est en local)
        if "localhost" in REDIRECT_URI:
            st.divider()
            with st.expander("🆘 Dépannage (Localhost uniquement)"):
                st.warning("Si la redirection échoue sur Codespaces :")
                manual_code = st.text_input("Coller le code Strava ici")
                if st.button("Valider le code manuellement"):
                    if CLIENT_ID and CLIENT_SECRET and manual_code:
                        with st.spinner("Échange du code manuel..."):
                            token_response = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, manual_code)
                            if token_response:
                                st.session_state.access_token = token_response.get("access_token")
                                st.session_state.athlete = token_response.get("athlete")
                                st.rerun()

else:
    # --- DASHBOARD DU COACH ---
    athlete = st.session_state.athlete
    
    # 1. GESTION DU PROFIL & OBJECTIFS (SIDEBAR)
    athlete_id = str(athlete.get('id', 'demo'))
    goals_db = load_goals()
    user_goal = goals_db.get(athlete_id, {})
    
    with st.sidebar:
        st.header(f"Profil : {athlete.get('firstname', 'Athlète')}")
        st.write("---")
        st.subheader("🎯 Mon Objectif")
        
        # Formulaire d'objectif
        with st.form("goal_form"):
            goal_types = ["Entretien / Plaisir", "Prépa Marathon", "Prépa Semi", "Prépa 10km", "Perte de poids", "Ultra / Trail"]
            # Index par défaut
            default_ix = 0
            if user_goal.get("type") in goal_types:
                default_ix = goal_types.index(user_goal.get("type"))
            
            selected_type = st.selectbox("Je prépare...", goal_types, index=default_ix)
            
            # Gestion de la date
            default_date = None
            if user_goal.get("date"):
                try:
                    default_date = datetime.strptime(user_goal.get("date"), "%Y-%m-%d")
                except:
                    pass
            
            target_date = st.date_input("Date de l'objectif (optionnel)", value=default_date)
            custom_note = st.text_input("Note perso (ex: Moins de 4h)", value=user_goal.get("note", ""))
            
            if st.form_submit_button("Sauvegarder mon profil"):
                new_goal = {
                    "type": selected_type,
                    "date": target_date.strftime("%Y-%m-%d") if target_date else None,
                    "note": custom_note
                }
                save_goal(athlete_id, new_goal)
                st.success("Profil mis à jour !")
                st.rerun()
        
        st.write("---")
        if st.button("Se déconnecter", key="logout_side"):
            st.session_state.clear()
            st.rerun()

    # Affichage de l'objectif en haut du dashboard
    if user_goal:
        obj_txt = f"🎯 **Objectif :** {user_goal.get('type')}"
        if user_goal.get('note'):
            obj_txt += f" ({user_goal.get('note')})"
        if user_goal.get('date'):
            d_obj = datetime.strptime(user_goal.get('date'), "%Y-%m-%d")
            delta_days = (d_obj - datetime.now()).days
            if delta_days > 0:
                obj_txt += f" — **J-{delta_days}**"
            elif delta_days == 0:
                obj_txt += " — **C'est aujourd'hui !**"
            else:
                obj_txt += " — *Objectif passé*"
        st.info(obj_txt)


    # 2. RÉCUPÉRATION DES DONNÉES
    if st.session_state.access_token == "demo_fake_token":
        if not user_goal: st.warning("⚠️ MODE DÉMO ACTIVÉ")
        activities = generate_mock_data()
        api_success = True
    else:
        headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
        params = {"per_page": 50} 
        response = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
        if response.status_code == 200:
            activities = response.json()
            api_success = True
        else:
            api_success = False
            st.error(f"Erreur API : {response.status_code}")

    if api_success and activities:
        # 3. TRAITEMENT DES DONNÉES
        df = pd.json_normalize(activities)
        
        # --- CORRECTION DATE & TIMEZONE ---
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        if df['start_date_local'].dt.tz is not None:
             df['start_date_local'] = df['start_date_local'].dt.tz_localize(None)
        
        df['week_start'] = df['start_date_local'].dt.to_period('W').apply(lambda r: r.start_time)
        
        # Conversions unités
        df['distance_km'] = df['distance'] / 1000
        df['duration_h'] = df['moving_time'] / 3600
        df['pace_decimal'] = 16.666666666667 / df['average_speed']
        
        # --- BLOC KPI ---
        st.subheader(f"Analyse des 30 derniers jours")
        
        current_date = datetime.now()
        last_4_weeks = df[df['start_date_local'] > (current_date - timedelta(days=28))]
        
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        
        vol_total = last_4_weeks['distance_km'].sum()
        nb_sorties = len(last_4_weeks)
        avg_fc = last_4_weeks['average_heartrate'].mean() if 'average_heartrate' in last_4_weeks else 0
        
        kpi1.metric("Volume", f"{int(vol_total)} km")
        kpi2.metric("Sorties", f"{nb_sorties}")
        kpi3.metric("Cardio Moyen", f"{int(avg_fc)} bpm")
        
        last_week = df[df['start_date_local'] > (current_date - timedelta(days=7))]
        vol_last_week = last_week['distance_km'].sum()
        avg_vol_prev = (vol_total - vol_last_week) / 3 if (vol_total - vol_last_week) > 0 else vol_last_week
        
        delta = ((vol_last_week - avg_vol_prev) / avg_vol_prev) * 100 if avg_vol_prev > 0 else 0
        kpi4.metric("Tendance Charge", f"{int(vol_last_week)} km", f"{int(delta)} %")

        # --- ONGLETS D'ANALYSE ---
        tab1, tab2, tab3 = st.tabs(["📊 Vue d'ensemble", "❤️ Cardio & Intensité", "📋 Journal"])

        with tab1:
            st.markdown("### Évolution du Volume")
            weekly_vol = df.groupby('week_start')['distance_km'].sum().reset_index()
            weekly_vol = weekly_vol.sort_values('week_start')
            
            fig_vol = px.bar(weekly_vol, x='week_start', y='distance_km',
                             title="Volume Hebdomadaire (km)",
                             labels={'week_start': 'Semaine', 'distance_km': 'Distance (km)'},
                             color='distance_km',
                             color_continuous_scale='Teal')
            st.plotly_chart(fig_vol, use_container_width=True)
            
            # --- CONSEIL PERSONNALISÉ SELON L'OBJECTIF ---
            if user_goal.get("type") == "Prépa Marathon" and vol_total < 100:
                st.warning("⚠️ **Conseil Marathon :** Ton volume mensuel ({} km) semble un peu faible pour une prépa marathon. Vise une augmentation progressive.".format(int(vol_total)))
            elif delta > 20:
                st.warning("⚠️ **Alerte Surcharge :** Tu as augmenté ton volume de plus de 20% cette semaine.")
            elif delta < -20:
                st.info("ℹ️ **Récupération :** Semaine plus légère détectée.")
            else:
                st.success("✅ **Progression Saine :** Ton volume est stable.")

        with tab2:
            st.markdown("### Analyse de l'Intensité")
            col_graph, col_advice = st.columns([2, 1])
            
            with col_graph:
                if 'average_heartrate' in df.columns:
                    fig_scatter = px.scatter(df, x='start_date_local', y='pace_decimal',
                                             size='distance_km', color='average_heartrate',
                                             color_continuous_scale='RdYlGn_r',
                                             title="Distribution des séances",
                                             labels={'pace_decimal': 'Allure (min/km)', 'start_date_local': 'Date', 'average_heartrate': 'BPM'})
                    fig_scatter.update_layout(yaxis_autorange="reversed")
                    st.plotly_chart(fig_scatter, use_container_width=True)
                else:
                    st.info("Pas de données cardiaques suffisantes.")

            with col_advice:
                st.markdown("**Le regard du coach :**")
                st.info("💡 Cherche à polariser ton entraînement : beaucoup de vert (lent), un peu de rouge (vite), et évite le jaune (allure moyenne fatiguante).")

        with tab3:
            st.markdown("### Historique des sorties")
            display_df = df[['name', 'start_date_local', 'distance_km', 'moving_time', 'average_speed']].copy()
            display_df['Date'] = display_df['start_date_local'].dt.strftime('%d/%m/%Y')
            display_df['Distance'] = display_df['distance_km'].round(2).astype(str) + " km"
            display_df['Durée'] = display_df['moving_time'].apply(format_duration)
            display_df['Allure'] = display_df['average_speed'].apply(calculate_pace)
            
            st.dataframe(display_df[['Date', 'name', 'Distance', 'Durée', 'Allure']], use_container_width=True, hide_index=True)

    else:
        st.info("Connecte-toi ou active le Mode Démo pour voir l'analyse.")
