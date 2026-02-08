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
import math
import numpy as np

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Run Coach", page_icon="🏃‍♂️", layout="wide")

# --- STYLES CSS PERSONNALISÉS (BENTO) ---
st.markdown("""
<style>
    .bento-box {
        background-color: #f0f2f6;
        border-radius: 15px;
        padding: 20px;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .big-stat {
        font-size: 2rem;
        font-weight: bold;
        color: #1f77b4;
    }
    .sub-stat {
        font-size: 1rem;
        color: #666;
    }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTES & CONFIG ---
GOALS_FILE = "goals.json"
REDIRECT_URI = "http://localhost:8501" 

# Dictionnaire de traduction des activités
ACTIVITY_TRANSLATIONS = {
    "Run": "Course à pied",
    "Ride": "Vélo",
    "VirtualRide": "Vélo Intérieur (Zwift)",
    "WeightTraining": "Musculation",
    "Hike": "Randonnée",
    "Walk": "Marche",
    "Swim": "Natation",
    "AlpineSki": "Ski Alpin",
    "BackcountrySki": "Ski de Rando",
    "Workout": "Entraînement",
    "Yoga": "Yoga"
}

# --- FONCTIONS UTILITAIRES (LOGIQUE MÉTIER & CALCULS) ---

def load_goals():
    if os.path.exists(GOALS_FILE):
        try:
            with open(GOALS_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_goal(athlete_id, goal_data):
    goals = load_goals()
    goals[str(athlete_id)] = goal_data
    with open(GOALS_FILE, "w") as f:
        json.dump(goals, f)

def format_duration(seconds):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{int(hours)}h {int(minutes)}min"

def translate_activity(type_en):
    return ACTIVITY_TRANSLATIONS.get(type_en, type_en)

def calculate_pace(speed_ms):
    if speed_ms == 0 or pd.isna(speed_ms): return "0'00''/km"
    pace_min = 16.666666666667 / speed_ms
    minutes = int(pace_min)
    seconds = int((pace_min - minutes) * 60)
    return f"{minutes}'{seconds:02d}''/km"

def calculate_trimp(duration_min, avg_hr, max_hr=190, rest_hr=60):
    """Calcul du Training Impulse (Charge interne - Bannister)"""
    if not avg_hr or pd.isna(avg_hr) or avg_hr == 0: return 0
    hr_reserve = max_hr - rest_hr
    hr_fraction = (avg_hr - rest_hr) / hr_reserve
    # Formule simplifiée homme
    trimp = duration_min * hr_fraction * 0.64 * math.exp(1.92 * hr_fraction)
    return int(trimp)

def calculate_training_metrics(df):
    """
    Calcule les métriques avancées sur l'historique :
    - Charge journalière (Daily Load)
    - ATL (Fatigue 7j)
    - CTL (Forme 42j)
    - TSB (Fraîcheur)
    - ACWR (Ratio Charge Aiguë/Chronique)
    - Monotonie
    """
    if df.empty: return pd.DataFrame()
    
    # 1. Resampling par jour pour gérer les jours de repos (Load = 0)
    df_daily = df.set_index('start_date_local').resample('D').agg({
        'trimp': 'sum',
        'distance_km': 'sum',
        'duration_h': 'sum'
    }).fillna(0)
    
    # 2. Moyennes glissantes
    df_daily['ATL'] = df_daily['trimp'].rolling(window=7, min_periods=1).mean()  # Fatigue (Acute)
    df_daily['CTL'] = df_daily['trimp'].rolling(window=42, min_periods=1).mean() # Forme (Chronic)
    df_daily['TSB'] = df_daily['CTL'] - df_daily['ATL'] # Fraîcheur (Training Stress Balance)
    
    # 3. ACWR (Charge 7j / Moyenne Charge 28j)
    # Note : On utilise souvent des moyennes exponentielles, ici moyenne simple pour MVP
    load_7d = df_daily['trimp'].rolling(window=7, min_periods=1).sum()
    avg_load_28d = df_daily['trimp'].rolling(window=28, min_periods=1).mean() * 7 # Ramené à la semaine
    
    # Éviter la division par zéro
    df_daily['ACWR'] = load_7d / avg_load_28d.replace(0, 1)
    
    # 4. Monotonie (Moyenne Charge Hebdo / Écart Type Charge Hebdo)
    rolling_mean_7d = df_daily['trimp'].rolling(window=7, min_periods=1).mean()
    rolling_std_7d = df_daily['trimp'].rolling(window=7, min_periods=1).std()
    df_daily['Monotony'] = rolling_mean_7d / rolling_std_7d.replace(0, 1)
    
    return df_daily

def get_coach_verdict(tsb, acwr):
    """Génère le verdict du coach basé sur le TSB et l'ACWR"""
    verdict = ""
    color = "green"
    
    if acwr > 1.5:
        verdict = "🛑 **STOP DANGER :** Risque de blessure élevé (ACWR > 1.5). Surcharge brutale détectée. Repos complet conseillé."
        color = "red"
    elif tsb < -20:
        verdict = "⚠️ **Surcharge :** Tu es très fatigué (TSB < -20). Programme une séance de récupération active ou repos."
        color = "orange"
    elif tsb > 10:
        verdict = "🚀 **En Forme :** Fraîcheur positive ! C'est le moment de placer une séance clé (VMA ou Seuil)."
        color = "green"
    else:
        verdict = "✅ **Zone Optimale :** Bon équilibre charge/récupération. Continue le plan."
        color = "blue"
        
    return verdict, color

def get_activity_streams(activity_id, access_token):
    """
    Récupère les données détaillées (seconde par seconde) d'une activité.
    """
    # Cas Mode Démo
    if access_token == "demo_fake_token":
        return generate_mock_streams()
    
    # Cas Vrai Strava
    headers = {"Authorization": f"Bearer {access_token}"}
    # On demande : temps, distance, altitude, cardio, vitesse, cadence
    keys = "time,distance,altitude,heartrate,velocity_smooth,cadence"
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams?keys={keys}&key_by_type=true"
    
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()
        return None
    except:
        return None

def generate_mock_data():
    data = []
    today = datetime.now()
    activities = ["Run", "Ride", "WeightTraining", "Hike"]
    
    # Génération sur 60 jours pour avoir l'historique CTL (42j)
    for i in range(60):
        # On simule un jour sur deux environ, ou des blocs
        if random.random() > 0.3: 
            date_act = today - timedelta(days=i)
            act_type = random.choice(["Run", "Run", "Run", "Ride"]) # Plus de run
            
            if act_type == "Run":
                dist = random.randint(5000, 18000)
                speed = random.uniform(2.5, 3.8) 
            elif act_type == "Ride":
                dist = random.randint(20000, 60000)
                speed = random.uniform(6.0, 9.0)
            else:
                dist = 0
                speed = 0
                
            duration = random.randint(1800, 5400)
            hr = random.randint(120, 170)
            
            # Simulation d'une surcharge récente pour tester les jauges
            if i < 7: 
                duration *= 1.5 # On force un peu sur la dernière semaine
            
            data.append({
                "name": f"{act_type} - J-{i}",
                "distance": dist,
                "moving_time": duration,
                "total_elevation_gain": random.randint(50, 800),
                "start_date_local": date_act.isoformat(),
                "average_heartrate": hr,
                "average_speed": speed,
                "type": act_type,
                "id": i
            })
    
    data.sort(key=lambda x: x['start_date_local'], reverse=True)
    return data

def generate_mock_streams():
    """Génère des faux streams réalistes pour le mode démo"""
    points = 100
    x_axis = np.linspace(0, 10000, points) # 10km
    # Simulation d'une montée (altitude)
    alt_stream = 100 + 100 * np.sin(np.linspace(0, 3.14, points)) 
    # Simulation du cardio qui monte avec l'effort
    hr_stream = 130 + 30 * np.sin(np.linspace(0, 3.14, points)) + np.random.normal(0, 2, points)
    
    return {
        "distance": {"data": x_axis.tolist()},
        "altitude": {"data": alt_stream.tolist()},
        "heartrate": {"data": hr_stream.tolist()}
    }

# --- SETUP SECRETS ---
CLIENT_ID, CLIENT_SECRET = None, None
try:
    if "STRAVA_CLIENT_ID" in st.secrets:
        CLIENT_ID = st.secrets["STRAVA_CLIENT_ID"]
        CLIENT_SECRET = st.secrets["STRAVA_CLIENT_SECRET"]
    if "APP_URL" in st.secrets:
        REDIRECT_URI = st.secrets["APP_URL"]
except: pass

if not CLIENT_ID or not CLIENT_SECRET:
    st.sidebar.warning("⚠️ Configurer les clés API")
    CLIENT_ID = st.sidebar.text_input("Client ID")
    CLIENT_SECRET = st.sidebar.text_input("Client Secret", type="password")

# --- SESSION ---
if "access_token" not in st.session_state: st.session_state.access_token = None

# --- UI HEADER ---
st.title("🏃‍♂️ Smart Run Coach")
st.markdown("**Data Coach :** *Analyse scientifique de ta performance.*")

# =========================================================
# LOGIQUE PRINCIPALE
# =========================================================

if not st.session_state.access_token:
    # --- PAGE DE CONNEXION ---
    query_params = st.query_params
    auth_code = query_params.get("code")
    
    if auth_code:
        with st.spinner("Analyse du profil..."):
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
                st.info("👈 Config manquante")
        with col2:
            if st.button("🛠️ Mode Démo (Données 60j)"):
                demo_data = strava_auth.get_demo_token()
                st.session_state.access_token = demo_data["access_token"]
                st.session_state.athlete = demo_data["athlete"]
                st.rerun()
        
        if "localhost" in REDIRECT_URI:
            with st.expander("🆘 Dépannage Codespaces"):
                manual_code = st.text_input("Code Strava")
                if st.button("Valider"):
                    if CLIENT_ID and manual_code:
                        resp = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, manual_code)
                        if resp:
                            st.session_state.access_token = resp.get("access_token")
                            st.session_state.athlete = resp.get("athlete")
                            st.rerun()

else:
    # --- DASHBOARD CONNECTÉ ---
    athlete = st.session_state.athlete
    athlete_id = str(athlete.get('id', 'demo'))
    goals_db = load_goals()
    user_goal = goals_db.get(athlete_id, {})
    
    # --- CHARGEMENT DONNÉES ---
    if st.session_state.access_token == "demo_fake_token":
        activities = generate_mock_data()
    else:
        headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
        params = {"per_page": 200} # Besoin de beaucoup d'historique pour CTL (42j)
        try:
            r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
            activities = r.json() if r.status_code == 200 else []
        except: activities = []

    if activities:
        df = pd.json_normalize(activities)
        
        # Nettoyage & Conversion
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        if df['start_date_local'].dt.tz is not None:
             df['start_date_local'] = df['start_date_local'].dt.tz_localize(None)
        
        if 'distance' in df.columns: df['distance_km'] = df['distance'] / 1000
        else: df['distance_km'] = 0
        df['duration_h'] = df['moving_time'] / 3600
        df['pace_decimal'] = df['average_speed'].apply(lambda x: 16.666666666667 / x if x > 0 else None)
        
        # Traduction des types pour l'affichage
        df['type_fr'] = df['type'].apply(translate_activity)

        # Calcul du TRIMP pour chaque activité
        df['trimp'] = df.apply(lambda row: calculate_trimp(row['moving_time']/60, row.get('average_heartrate', 0)), axis=1)
        
        # --- SIDEBAR (FILTRES ET PROFIL) ---
        with st.sidebar:
            st.header(f"👤 {athlete.get('firstname', 'Athlète')}")
            
            # Filtre d'activités (Traduit)
            st.subheader("Filtre Activités")
            available_types = ["Tous"] + list(df['type_fr'].unique())
            selected_type_fr = st.selectbox("Sport", available_types)
            
            # Application du filtre
            if selected_type_fr != "Tous":
                df_filtered = df[df['type_fr'] == selected_type_fr].copy()
            else:
                df_filtered = df.copy()

            st.divider()
            
            with st.expander("🎯 Mon Objectif", expanded=not bool(user_goal)):
                with st.form("goal_form"):
                    goal_types = ["Entretien / Plaisir", "Prépa Marathon", "Prépa Semi", "Prépa 10km", "Perte de poids", "Ultra / Trail"]
                    def_ix = goal_types.index(user_goal.get("type")) if user_goal.get("type") in goal_types else 0
                    selected_type = st.selectbox("Type", goal_types, index=def_ix)
                    custom_note = st.text_input("Note", value=user_goal.get("note", ""))
                    if st.form_submit_button("Mettre à jour"):
                        save_goal(athlete_id, {"type": selected_type, "note": custom_note})
                        st.success("Enregistré")
                        st.rerun()
            st.divider()
            if st.button("Déconnexion"):
                st.session_state.clear()
                st.rerun()

        # Calcul des Métriques Avancées (sur données filtrées ou globales ? Globales mieux pour la fatigue)
        # Mais pour l'affichage, on utilisera df_filtered
        df_daily_metrics = calculate_training_metrics(df) # Calcul sur tout pour avoir la vraie fatigue
        last_metrics = df_daily_metrics.iloc[-1]
        
        # --- STRUCTURE ONGLET (4 Pages) ---
        tab_cockpit, tab_micro, tab_labo, tab_doc = st.tabs([
            "🚀 Cockpit (Aujourd'hui)", 
            "🔬 Microscope (Dernière Séance)", 
            "🧪 Laboratoire (Tendances)", 
            "🩺 Cabinet du Doc (Santé)"
        ])

        # =================================================
        # PAGE 1 : LE COCKPIT (BENTO GRID)
        # =================================================
        with tab_cockpit:
            st.markdown("### 🧭 Où j'en suis aujourd'hui ?")
            
            verdict, verdict_color = get_coach_verdict(last_metrics['TSB'], last_metrics['ACWR'])
            
            # Layout Bento : Ligne 1
            col1, col2 = st.columns([2, 1])
            
            with col1:
                with st.container(border=True):
                    st.markdown(f"#### 🤖 Le Verdict du Coach")
                    st.info(f"**{verdict}**")
                    st.markdown(f"""
                    * **Forme (CTL 42j) :** {int(last_metrics['CTL'])} (Ta caisse)
                    * **Fatigue (ATL 7j) :** {int(last_metrics['ATL'])} (Ta charge récente)
                    * **Indice de Fraîcheur (TSB) :** {int(last_metrics['TSB'])}
                    """)
            
            with col2:
                with st.container(border=True):
                    st.markdown("#### 🔋 Jauge de Fraîcheur")
                    fig_gauge = go.Figure(go.Indicator(
                        mode = "gauge+number",
                        value = int(last_metrics['TSB']),
                        title = {'text': "TSB"},
                        gauge = {
                            'axis': {'range': [-50, 50]},
                            'bar': {'color': "lightgray"},
                            'steps': [
                                {'range': [-50, -20], 'color': "red"}, 
                                {'range': [-20, 10], 'color': "lightgreen"}, 
                                {'range': [10, 50], 'color': "cyan"}],
                            'threshold': {
                                'line': {'color': "black", 'width': 4},
                                'thickness': 0.75,
                                'value': int(last_metrics['TSB'])}
                        }
                    ))
                    fig_gauge.update_layout(height=150, margin=dict(l=20, r=20, t=30, b=20))
                    st.plotly_chart(fig_gauge, use_container_width=True)

            # Layout Bento : Ligne 2
            col3, col4, col5 = st.columns(3)
            
            with col3:
                with st.container(border=True):
                    st.markdown("#### ⚖️ Monotonie")
                    monotony = last_metrics['Monotony']
                    mono_color = "red" if monotony > 2.0 else "green"
                    st.markdown(f"<h2 style='color:{mono_color}'>{monotony:.2f}</h2>", unsafe_allow_html=True)
                    st.caption("Plus c'est bas, mieux c'est (Variété).")
            
            with col4:
                with st.container(border=True):
                    st.markdown("#### 🗓️ Série en cours")
                    streak = 0
                    for i in range(len(df_daily_metrics)):
                        if df_daily_metrics.iloc[-(i+1)]['trimp'] > 0: streak += 1
                        else: break
                    st.markdown(f"<h2>🔥 {streak} Jours</h2>", unsafe_allow_html=True)
                    st.caption("Consistance d'entraînement.")

            with col5:
                with st.container(border=True):
                    st.markdown("#### 👟 Kilométrage Hebdo")
                    # Calcul basé sur le DF filtré pour être pertinent (ex: que Vélo)
                    # Note : Si le filtre est actif, on recalcule sommairement la dist hebdo filtrée
                    dist_7d = df_filtered[df_filtered['start_date_local'] > (datetime.now() - timedelta(days=7))]['distance_km'].sum()
                    st.markdown(f"<h2>{int(dist_7d)} km</h2>", unsafe_allow_html=True)
                    st.caption("Volume glissant sur 7 jours (Sélection).")

        # =================================================
        # PAGE 2 : LE MICROSCOPE (ACTIVITÉ SPÉCIFIQUE)
        # =================================================
        with tab_micro:
            st.markdown("### 🔬 Analyse détaillée d'une séance")
            
            # SÉLECTEUR D'ACTIVITÉ (Parmi les filtrées)
            # Création d'un dictionnaire {Label: ID}
            activity_options = {
                f"{row['start_date_local'].strftime('%d/%m')} - {row['name']} ({row['type_fr']})": row['id'] 
                for index, row in df_filtered.iterrows()
            }
            
            selected_act_label = st.selectbox("Choisis une séance à analyser :", list(activity_options.keys()))
            selected_act_id = activity_options[selected_act_label]
            
            # Récupération des données de base de l'activité sélectionnée
            selected_act = df[df['id'] == selected_act_id].iloc[0]
            
            # 1. RÉCUPÉRATION DES STREAMS (DONNÉES DÉTAILLÉES)
            with st.spinner("Téléchargement des données détaillées (Altitude, Cardio...)..."):
                streams = get_activity_streams(selected_act_id, st.session_state.access_token)

            # Calculs Spécifiques Séance
            has_hr = 'average_heartrate' in selected_act and selected_act['average_heartrate'] > 0
            cardiac_cost = 0
            efficiency_factor = 0
            
            if has_hr and selected_act['distance_km'] > 0:
                beats_total = selected_act['average_heartrate'] * (selected_act['moving_time'] / 60)
                cardiac_cost = beats_total / selected_act['distance_km']
                speed_m_min = (selected_act['distance_km'] * 1000) / (selected_act['moving_time'] / 60)
                efficiency_factor = speed_m_min / selected_act['average_heartrate']

            col_m1, col_m2 = st.columns([1, 2])
            
            with col_m1:
                with st.container(border=True):
                    st.subheader(f"{selected_act['name']}")
                    st.caption(f"{selected_act['start_date_local'].strftime('%d/%m/%Y')} - {selected_act['type_fr']}")
                    st.metric("Distance", f"{selected_act['distance_km']:.2f} km")
                    st.metric("D+", f"{selected_act.get('total_elevation_gain', 0)} m")
                    st.metric("TRIMP", f"{int(selected_act['trimp'])}")
            
            with col_m2:
                c1, c2 = st.columns(2)
                c1.metric("🫀 Coût Cardiaque", f"{int(cardiac_cost)} bpm/km", help="Battements dépensés par km.")
                c2.metric("🚀 Efficiency Factor", f"{efficiency_factor:.2f}", help="Vitesse (m/min) par battement.")
                
                # GRAPHIQUE DES STREAMS (VRAIES DONNÉES)
                st.markdown("#### ⛰️ Superposition Cardio / Altitude (Données Réelles)")
                
                if streams:
                    fig_stream = go.Figure()
                    
                    # On a besoin d'un axe X commun (Distance ou Temps)
                    # Strava renvoie des tableaux. Prenons la distance si dispo.
                    if 'distance' in streams:
                        x_data = streams['distance']['data']
                        x_title = "Distance (m)"
                    elif 'time' in streams:
                        x_data = streams['time']['data']
                        x_title = "Temps (s)"
                    else:
                        x_data = []
                    
                    if len(x_data) > 0:
                        # Altitude (Zone grise)
                        if 'altitude' in streams:
                            alt_data = streams['altitude']['data']
                            # On lisse un peu si besoin, ou brut
                            fig_stream.add_trace(go.Scatter(x=x_data, y=alt_data, fill='tozeroy', name='Altitude', 
                                                          line=dict(color='gray', width=0), opacity=0.3))
                        
                        # Cardio (Ligne rouge)
                        if 'heartrate' in streams:
                            hr_data = streams['heartrate']['data']
                            fig_stream.add_trace(go.Scatter(x=x_data, y=hr_data, name='Cardio', 
                                                          line=dict(color='red', width=2), yaxis='y2'))
                        
                        fig_stream.update_layout(
                            xaxis=dict(title=x_title),
                            yaxis=dict(title="Altitude (m)", showgrid=False),
                            yaxis2=dict(title="BPM", overlaying='y', side='right', showgrid=False),
                            margin=dict(l=0, r=0, t=0, b=0),
                            height=300,
                            showlegend=True
                        )
                        st.plotly_chart(fig_stream, use_container_width=True)
                    else:
                        st.warning("Données détaillées illisibles pour cette activité.")
                else:
                    st.info("Pas de données détaillées disponibles (Streams) pour cette activité.")

        # =================================================
        # PAGE 3 : LE LABORATOIRE (LONG TERM)
        # =================================================
        with tab_labo:
            st.markdown("### 🧪 Tendances Long Terme")
            
            # On utilise le DF filtré ici pour que les graphiques reflètent le choix (Run, Bike...)
            if not df_filtered.empty:
                col_l1, col_l2 = st.columns(2)
                
                with col_l1:
                    st.markdown("#### 📉 Nuage de Corrélation (Le Graal)")
                    st.caption("Objectif : Déplacement des points vers le bas à droite (Plus vite, Cardio plus bas)")
                    
                    if 'average_heartrate' in df_filtered.columns:
                        # Vitesse km/h
                        df_filtered['speed_kmh'] = df_filtered['average_speed'] * 3.6
                        
                        fig_corr = px.scatter(df_filtered, x="speed_kmh", y="average_heartrate", 
                                              color="start_date_local",
                                              title="Vitesse vs Cardio (Couleur = Date)",
                                              labels={"speed_kmh": "Vitesse (km/h)", "average_heartrate": "FC Moyenne"})
                        st.plotly_chart(fig_corr, use_container_width=True)
                    else:
                        st.info("Pas de données cardio.")

                with col_l2:
                    st.markdown("#### 🍩 Répartition du Volume (Zones simulées)")
                    
                    def categorize_zone(hr):
                        if hr < 145: return "Z1/Z2 (Endurance)"
                        elif hr < 160: return "Z3 (Tempo)"
                        else: return "Z4/Z5 (Intensité)"
                    
                    if 'average_heartrate' in df_filtered.columns:
                        df_filtered['zone'] = df_filtered['average_heartrate'].apply(categorize_zone)
                        fig_pie = px.pie(df_filtered, names='zone', values='distance_km', title="Volume par Zone d'Intensité",
                                         color_discrete_map={"Z1/Z2 (Endurance)": "green", "Z3 (Tempo)": "orange", "Z4/Z5 (Intensité)": "red"})
                        st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Pas d'activités pour ce filtre.")

        # =================================================
        # PAGE 4 : LE CABINET DU DOC (SANTÉ)
        # =================================================
        with tab_doc:
            st.markdown("### 🩺 Prévention & Santé")
            
            col_d1, col_d2 = st.columns(2)
            
            with col_d1:
                with st.container(border=True):
                    st.markdown("#### 🚑 Ratio ACWR (Acute:Chronic Workload)")
                    acwr_val = last_metrics['ACWR']
                    
                    fig_acwr = go.Figure(go.Indicator(
                        mode = "gauge+number",
                        value = acwr_val,
                        title = {'text': "ACWR"},
                        gauge = {
                            'axis': {'range': [0, 2.5]},
                            'bar': {'color': "black"},
                            'steps': [
                                {'range': [0, 0.8], 'color': "lightgray"}, # Sous-entrainement
                                {'range': [0.8, 1.3], 'color': "green"}, # Sweet Spot
                                {'range': [1.3, 1.5], 'color': "orange"}, # Risque
                                {'range': [1.5, 2.5], 'color': "red"}], # Danger
                            'threshold': {
                                'line': {'color': "red", 'width': 4},
                                'thickness': 0.75,
                                'value': acwr_val}
                        }
                    ))
                    fig_acwr.update_layout(height=200)
                    st.plotly_chart(fig_acwr, use_container_width=True)
                    st.caption("Si > 1.5 : DANGER. Tu augmentes la charge trop vite par rapport à ton habitude.")

            with col_d2:
                with st.container(border=True):
                    st.markdown("#### 👟 Suivi Usure Chaussures")
                    # On ne compte que les activités de type Course à pied pour les chaussures
                    total_km_run = df[df['type']=='Run']['distance_km'].sum()
                    max_km_shoe = 800
                    
                    percent_wear = min(total_km_run / max_km_shoe, 1.0)
                    st.progress(percent_wear)
                    st.write(f"**Kilométrage Running total :** {int(total_km_run)} km")
                    
                    if total_km_run > 800:
                        st.error("👟 Tes chaussures sont mortes (>800km). Risque de blessure élevé. Change-les !")
                    elif total_km_run > 500:
                        st.warning("👟 L'amorti commence à fatiguer.")
                    else:
                        st.success("👟 Chaussures OK.")

    else:
        st.info("Aucune activité trouvée pour ce filtre.")
