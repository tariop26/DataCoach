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

# --- STYLES CSS PERSONNALISÉS (BENTO PRO) ---
st.markdown("""
<style>
    /* Style global des boîtes Bento */
    .bento-box {
        background-color: transparent; 
        border: 1px solid rgba(128, 128, 128, 0.3);
        border-radius: 12px;
        padding: 24px;
        margin-bottom: 20px;
        height: 100%;
        min-height: 320px; /* Force la même taille pour les blocs alignés */
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    
    /* Layout Interne (Flexbox pour aligner Texte et Jauges) */
    .bento-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 15px;
    }
    
    /* Titres et chiffres */
    .metric-value {
        font-size: 2.2rem;
        font-weight: 800;
        margin: 0;
        line-height: 1.1;
    }
    .metric-label {
        font-size: 0.9rem;
        font-weight: 700;
        opacity: 0.6;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 5px;
    }
    .metric-sub {
        font-size: 0.85rem;
        opacity: 0.5;
        font-weight: 500;
    }
    
    /* Textes explicatifs */
    .metric-insight {
        font-size: 0.95rem;
        opacity: 0.85;
        margin-top: 15px;
        line-height: 1.6;
        border-top: 1px solid rgba(128, 128, 128, 0.1);
        padding-top: 15px;
    }
    
    /* Barres de progression Custom HTML */
    .progress-container {
        width: 100%;
        background-color: rgba(128,128,128,0.1);
        border-radius: 8px;
        height: 12px;
        margin-top: 5px;
        overflow: hidden;
    }
    .progress-bar {
        height: 100%;
        border-radius: 8px;
        transition: width 0.5s ease-in-out;
    }
    
    /* Bulles de conseil */
    .coach-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 10px;
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
    Calcule les métriques avancées sur l'historique.
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
    load_7d = df_daily['trimp'].rolling(window=7, min_periods=1).sum()
    avg_load_28d = df_daily['trimp'].rolling(window=28, min_periods=1).mean() * 7 
    df_daily['ACWR'] = load_7d / avg_load_28d.replace(0, 1)
    
    # 4. Monotonie
    rolling_mean_7d = df_daily['trimp'].rolling(window=7, min_periods=1).mean()
    rolling_std_7d = df_daily['trimp'].rolling(window=7, min_periods=1).std()
    df_daily['Monotony'] = rolling_mean_7d / rolling_std_7d.replace(0, 1)
    
    return df_daily

def get_coach_verdict(tsb, acwr):
    """Génère le verdict du coach détaillé basé sur le TSB et l'ACWR"""
    verdict = ""
    color = "green"
    detail = ""
    subtext = ""

    if acwr > 1.5:
        verdict = "🛑 STOP DANGER"
        subtext = "Risque de blessure maximal"
        color = "#ef4444" # Rouge
        detail = (
            "Ton ratio de charge aiguë (ACWR) dépasse 1.5. Tu as augmenté ta charge de +50% "
            "par rapport à tes habitudes du mois dernier. C'est la zone rouge pour tes tendons et ligaments. "
            "**Action :** Coupe l'entraînement 48h minimum, puis reprends par du footing fondamental uniquement."
        )
    elif tsb < -20:
        verdict = "⚠️ SURCHARGE"
        subtext = "Fatigue profonde détectée"
        color = "#f59e0b" # Orange
        detail = (
            "Tu es en déficit énergétique important (TSB < -20). Tu creuses ta fatigue plus vite que tu ne récupères. "
            "C'est une phase de 'Overreaching' qui peut être utile AVANT une semaine de repos, mais dangereuse si elle dure. "
            "**Action :** Réduis le volume de 40% cette semaine pour assimiler le travail."
        )
    elif tsb > 10:
        verdict = "🚀 PIC DE FORME"
        subtext = "Fraîcheur musculaire optimale"
        color = "#22c55e" # Vert
        detail = (
            "Affûtage réussi ! Ta fraîcheur est positive (>10) tout en gardant un bon niveau d'entraînement. "
            "Ton système nerveux est régénéré et tes jambes sont pleines de 'jus'. "
            "**Action :** C'est le moment idéal pour une compétition, un test VMA ou une séance clé à haute intensité."
        )
    else: # TSB entre -20 et 10
        verdict = "✅ ENTRAÎNEMENT OPTIMAL"
        subtext = "Zone de développement durable"
        color = "#3b82f6" # Bleu
        detail = (
            "Tu navigues dans la 'Sweet Spot' zone. Tu maintiens une pression d'entraînement suffisante pour forcer ton corps à s'adapter, "
            "sans toutefois l'épuiser. C'est l'équilibre parfait pour construire un moteur solide sur le long terme. "
            "**Action :** Garde ce cap, la régularité paie."
        )
        
    return verdict, subtext, color, detail

def get_activity_streams(activity_id, access_token):
    """Récupère les données détaillées (seconde par seconde) d'une activité."""
    if access_token == "demo_fake_token":
        return generate_mock_streams()
    
    headers = {"Authorization": f"Bearer {access_token}"}
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
    """Générateur de données enrichi avec Gear ID et Watts"""
    data = []
    today = datetime.now()
    activities = ["Run", "Ride", "WeightTraining", "Hike"]
    
    shoe_ids = ["g123456", "g789012"] 
    
    for i in range(60):
        if random.random() > 0.3: 
            date_act = today - timedelta(days=i)
            act_type = random.choice(["Run", "Run", "Run", "Ride"]) 
            
            gear_id = None
            watts = None

            if act_type == "Run":
                dist = random.randint(5000, 18000)
                speed = random.uniform(2.5, 3.8)
                gear_id = random.choice(shoe_ids) 
                watts = random.randint(200, 350) 
            elif act_type == "Ride":
                dist = random.randint(20000, 60000)
                speed = random.uniform(6.0, 9.0)
                watts = random.randint(150, 300) 
            else:
                dist = 0
                speed = 0
                
            duration = random.randint(1800, 5400)
            hr = random.randint(120, 170)
            
            if i < 7: duration *= 1.5 
            
            data.append({
                "name": f"{act_type} - J-{i}",
                "distance": dist,
                "moving_time": duration,
                "total_elevation_gain": random.randint(50, 800),
                "start_date_local": date_act.isoformat(),
                "average_heartrate": hr,
                "average_speed": speed,
                "average_watts": watts, 
                "gear_id": gear_id,     
                "type": act_type,
                "id": i
            })
    
    data.sort(key=lambda x: x['start_date_local'], reverse=True)
    return data

def generate_mock_streams():
    points = 100
    x_axis = np.linspace(0, 10000, points) 
    alt_stream = 100 + 100 * np.sin(np.linspace(0, 3.14, points)) 
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
    athlete = st.session_state.athlete
    athlete_id = str(athlete.get('id', 'demo'))
    goals_db = load_goals()
    user_goal = goals_db.get(athlete_id, {})
    
    # --- CHARGEMENT DONNÉES ---
    if st.session_state.access_token == "demo_fake_token":
        activities = generate_mock_data()
    else:
        headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
        params = {"per_page": 200}
        try:
            r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers=headers, params=params)
            activities = r.json() if r.status_code == 200 else []
        except: activities = []

    if activities:
        df = pd.json_normalize(activities)
        
        # Nettoyage
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        if df['start_date_local'].dt.tz is not None:
             df['start_date_local'] = df['start_date_local'].dt.tz_localize(None)
        
        if 'distance' in df.columns: df['distance_km'] = df['distance'] / 1000
        else: df['distance_km'] = 0
        df['duration_h'] = df['moving_time'] / 3600
        df['pace_decimal'] = df['average_speed'].apply(lambda x: 16.666666666667 / x if x > 0 else None)
        df['type_fr'] = df['type'].apply(translate_activity)
        df['trimp'] = df.apply(lambda row: calculate_trimp(row['moving_time']/60, row.get('average_heartrate', 0)), axis=1)
        
        # --- FILTRE & SIDEBAR ---
        with st.sidebar:
            st.header(f"👤 {athlete.get('firstname', 'Athlète')}")
            
            st.subheader("Filtre Activités")
            available_types = ["Tous"] + list(df['type_fr'].unique())
            selected_type_fr = st.selectbox("Sport", available_types)
            
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

        # Calcul Métriques
        df_daily_metrics = calculate_training_metrics(df)
        last_metrics = df_daily_metrics.iloc[-1]
        
        # Calcul des Max de la Saison (pour jauges)
        max_ctl_season = int(df_daily_metrics['CTL'].max()) if not df_daily_metrics.empty else 100
        max_atl_season = int(df_daily_metrics['ATL'].max()) if not df_daily_metrics.empty else 100
        if max_ctl_season == 0: max_ctl_season = 100
        if max_atl_season == 0: max_atl_season = 100
        
        # --- CALCULS KPI "TOP OF THE POP" ---
        now = datetime.now()
        df_30d = df_filtered[df_filtered['start_date_local'] > (now - timedelta(days=30))].copy()
        
        cot_val = 0
        if not df_30d.empty and 'average_heartrate' in df_30d.columns:
            mask = (df_30d['distance_km'] > 0) & (df_30d['average_heartrate'] > 0)
            if mask.any():
                df_30d.loc[mask, 'cot'] = (df_30d['average_heartrate'] * (df_30d['moving_time'] / 60)) / df_30d['distance_km']
                cot_val = df_30d.loc[mask, 'cot'].mean()

        pwr_val = 0
        if 'average_watts' in df_30d.columns and 'average_heartrate' in df_30d.columns:
            mask = (df_30d['average_heartrate'] > 0) & (df_30d['average_watts'] > 0)
            if mask.any():
                df_30d.loc[mask, 'pwr_ratio'] = df_30d['average_watts'] / df_30d['average_heartrate']
                pwr_val = df_30d.loc[mask, 'pwr_ratio'].mean()

        punch_val = 0
        mask_punch = (df_30d['moving_time'] > 0)
        if mask_punch.any():
            df_30d.loc[mask_punch, 'punch'] = df_30d['total_elevation_gain'] / (df_30d['moving_time'] / 3600)
            punch_val = df_30d.loc[mask_punch, 'punch'].mean()

        primary_shoe_dist = 0
        primary_shoe_name = "Aucune"
        max_shoe_dist = 800
        if 'gear_id' in df.columns:
            df_gear = df[df['type'] == 'Run'] if not df[df['type'] == 'Run'].empty else df
            if not df_gear.empty and 'gear_id' in df_gear.columns:
                 gear_stats = df_gear.groupby('gear_id')['distance_km'].sum().sort_values(ascending=False)
                 if not gear_stats.empty:
                     primary_shoe_id = gear_stats.index[0]
                     primary_shoe_dist = gear_stats.iloc[0]
                     primary_shoe_name = f"ID: {primary_shoe_id}" if primary_shoe_id else "Inconnu"

        consistency_streak = 0
        if not df.empty:
            active_weeks = df['start_date_local'].dt.to_period('W').sort_values(ascending=False).unique()
            if len(active_weeks) > 0:
                current_w = pd.Timestamp.now().to_period('W')
                if (current_w - active_weeks[0]).n <= 1:
                    consistency_streak = 1
                    for i in range(1, len(active_weeks)):
                        if (active_weeks[i-1] - active_weeks[i]).n == 1:
                            consistency_streak += 1
                        else:
                            break
        
        # --- UI ONGLET ---
        tab_cockpit, tab_micro, tab_labo, tab_doc = st.tabs([
            "🚀 Cockpit", "🔬 Microscope", "🧪 Laboratoire", "🩺 Santé"
        ])

        with tab_cockpit:
            st.markdown("### 🧭 Vue d'ensemble")

            # --- 1. ÉTAT DES LIEUX (7j glissants) ---
            st.subheader("📅 État des lieux (7 derniers jours)")
            
            # Calculs 7j sur les données filtrées
            seven_days_ago = datetime.now() - timedelta(days=7)
            recent_df = df_filtered[df_filtered['start_date_local'] > seven_days_ago]
            
            dist_7d = recent_df['distance_km'].sum()
            elev_7d = recent_df['total_elevation_gain'].sum() if 'total_elevation_gain' in recent_df else 0
            time_7d_sec = recent_df['moving_time'].sum()
            time_7d_str = format_duration(time_7d_sec)

            col_7d_1, col_7d_2, col_7d_3 = st.columns(3)
            with col_7d_1:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Distance</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{dist_7d:.1f} km</div>', unsafe_allow_html=True)
            with col_7d_2:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Dénivelé (D+)</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(elev_7d)} m</div>', unsafe_allow_html=True)
            with col_7d_3:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Temps passé dehors</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{time_7d_str}</div>', unsafe_allow_html=True)

            st.divider()
            
            # --- 2. VERDICT & BATTERIE ---
            st.subheader("🤖 Verdict & Énergie")
            verdict_title, verdict_sub, verdict_col_hex, verdict_detail = get_coach_verdict(last_metrics['TSB'], last_metrics['ACWR'])
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Bloc Verdict
                st.markdown(f"""
                <div class="bento-box" style="border-left: 8px solid {verdict_col_hex};">
                    <div>
                        <div class="metric-label" style="color:{verdict_col_hex}">Verdict du Coach</div>
                        <div class="metric-value">{verdict_title}</div>
                        <div class="metric-sub">{verdict_sub}</div>
                    </div>
                    <div class="metric-insight">
                        {verdict_detail}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col2:
                # Calcul de la batterie
                tsb_val = int(last_metrics['TSB'])
                battery_pct = max(0, min(100, int((tsb_val + 30) / 50 * 100)))
                
                batt_color = "#22c55e" # Vert
                if battery_pct < 20: batt_color = "#ef4444" # Rouge
                elif battery_pct < 50: batt_color = "#f59e0b" # Orange

                # Bloc Batterie avec Jauge Intégrée
                st.markdown(f"""
                <div class="bento-box" style="border-left: 8px solid {batt_color};">
                    <div class="bento-header">
                        <div>
                            <div class="metric-label" style="color:{batt_color}">Niveau de Batterie</div>
                            <div class="metric-value">{battery_pct}%</div>
                            <div class="metric-sub">Score TSB : {tsb_val}</div>
                        </div>
                        <div style="flex:1; margin-left: 20px; display:flex; flex-direction:column; justify-content:center;">
                            <div style="font-weight:bold; font-size:1.5rem; text-align:right; color:{batt_color}">🔋</div>
                            <div class="progress-container">
                                <div class="progress-bar" style="width: {battery_pct}%; background-color: {batt_color};"></div>
                            </div>
                        </div>
                    </div>
                    <div class="metric-insight">
                        C'est ton <strong>carburant physiologique</strong> disponible aujourd'hui.
                        Une batterie à 100% signifie que tu es parfaitement reposé et prêt pour une performance maximale.
                        Sous les 30%, ton réservoir est vide : risque de panne sèche (blessure/maladie).
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # --- 3. FORME & FATIGUE (DÉTAIL) ---
            st.subheader("🏗️ Analyse Structurelle : Forme vs Fatigue")
            col_f1, col_f2 = st.columns(2)
            
            ctl_val = int(last_metrics['CTL'])
            atl_val = int(last_metrics['ATL'])
            
            # Calcul % par rapport au max saison
            pct_ctl = min(100, int(ctl_val / max_ctl_season * 100))
            pct_atl = min(100, int(atl_val / max_atl_season * 100))
            
            with col_f1:
                st.markdown(f"""
                <div class="bento-box" style="border-left: 5px solid #3b82f6;">
                    <div class="bento-header">
                         <div>
                            <div class="metric-label" style="color:#3b82f6">🏃 Capital Endurance (CTL)</div>
                            <div class="metric-value">{ctl_val} <span style="font-size:1rem; opacity:0.5; font-weight:400;">/ {max_ctl_season} (Max)</span></div>
                        </div>
                    </div>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: {pct_ctl}%; background-color: #3b82f6;"></div>
                    </div>
                    <div class="metric-insight">
                        C'est la taille de ton <strong>moteur aérobie</strong>. Il représente ta capacité à encaisser des charges de travail élevées sans t'effondrer. 
                        Ce capital se construit lentement (sur 42 jours). Plus il est haut, plus tu es un athlète "solide".
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col_f2:
                # Couleur de fatigue dynamique
                color_fatigue = "#22c55e"
                if atl_val > ctl_val + 20: color_fatigue = "#ef4444"
                
                st.markdown(f"""
                <div class="bento-box" style="border-left: 5px solid {color_fatigue};">
                    <div class="bento-header">
                         <div>
                            <div class="metric-label" style="color:{color_fatigue}">💤 Fatigue Aiguë (ATL)</div>
                            <div class="metric-value">{atl_val} <span style="font-size:1rem; opacity:0.5; font-weight:400;">/ {max_atl_season} (Max)</span></div>
                        </div>
                    </div>
                    <div class="progress-container">
                        <div class="progress-bar" style="width: {pct_atl}%; background-color: {color_fatigue};"></div>
                    </div>
                    <div class="metric-insight">
                        C'est le <strong>stress physiologique</strong> immédiat (7 jours). C'est nécessaire pour progresser (phénomène de surcompensation), 
                        mais il doit être cyclique. Si cette jauge reste bloquée dans le rouge trop longtemps sans redescendre, tu ne progresses plus, tu t'épuises.
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # --- 4. GRAPHIQUE ÉVOLUTION ---
            st.subheader("📉 Évolution de la Saison (60 jours)")
            date_60d_ago = datetime.now() - timedelta(days=60)
            df_chart = df_daily_metrics[df_daily_metrics.index > date_60d_ago].copy()
            
            if not df_chart.empty:
                fig_ff = go.Figure()
                fig_ff.add_trace(go.Scatter(x=df_chart.index, y=df_chart['CTL'], fill='tozeroy', 
                                            name='Capital Forme (CTL)', line=dict(color='#3b82f6')))
                fig_ff.add_trace(go.Scatter(x=df_chart.index, y=df_chart['ATL'], 
                                            name='Dette de Fatigue (ATL)', line=dict(color='#f97316', width=2)))
                fig_ff.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0), 
                                     legend=dict(orientation="h", y=1.1), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                st.plotly_chart(fig_ff, use_container_width=True)
            else:
                st.info("Pas assez de données pour afficher l'historique.")

            st.divider()

            # --- 5. INDICATEURS CLÉS (KPIs) ---
            st.subheader("⚡ Indicateurs de Performance")
            
            # LIGNE A : KPI MÉTIER
            col3, col4, col5 = st.columns(3)
            with col3:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Consistance</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">🔥 {consistency_streak} Sem.</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">Série active. Ne brise pas la chaîne !</div>', unsafe_allow_html=True)
            with col4:
                with st.container(border=True):
                    # Volume sur données filtrées
                    st.markdown('<div class="metric-label">Volume Sport (7j)</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(dist_7d)} km</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">Kilomètres parcourus (Filtre actif)</div>', unsafe_allow_html=True)
            with col5:
                with st.container(border=True):
                    mono = last_metrics['Monotony']
                    col_mono = "#ef4444" if mono > 2.0 else "#22c55e"
                    st.markdown('<div class="metric-label">Monotonie</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value" style="color:{col_mono}">{mono:.2f}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">Variété de l\'entrainement (Cible < 2.0)</div>', unsafe_allow_html=True)

            # LIGNE B : METRIQUES AVANCÉES
            col6, col7, col8 = st.columns(3)
            with col6:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Coût Cardio</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(cot_val) if cot_val else "--"}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">bpm / km (Économie)</div>', unsafe_allow_html=True)
            with col7:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Puissance</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{pwr_val:.1f}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">Watts / bpm (Rendement)</div>', unsafe_allow_html=True)
            with col8:
                with st.container(border=True):
                    st.markdown('<div class="metric-label">Punch</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="metric-value">{int(punch_val) if punch_val else "--"}</div>', unsafe_allow_html=True)
                    st.markdown('<div class="metric-insight">D+ mètres / heure (Vitesse Verticale)</div>', unsafe_allow_html=True)

            # SHOES
            with st.container(border=True):
                 st.markdown("#### 👟 Matériel (Chaussure principale)")
                 pct = min(primary_shoe_dist / max_shoe_dist, 1.0)
                 st.progress(pct)
                 st.caption(f"{int(primary_shoe_dist)} km parcourus avec {primary_shoe_name}. Pense à changer à 800km.")

        # =================================================
        # PAGE 2 : MICROSCOPE
        # =================================================
        with tab_micro:
            st.markdown("### 🔬 Analyse détaillée d'une séance")
            
            activity_options = {
                f"{row['start_date_local'].strftime('%d/%m')} - {row['name']} ({row['type_fr']})": row['id'] 
                for index, row in df_filtered.iterrows()
            }
            
            if activity_options:
                selected_act_label = st.selectbox("Choisis une séance à analyser :", list(activity_options.keys()))
                selected_act_id = activity_options[selected_act_label]
                selected_act = df[df['id'] == selected_act_id].iloc[0]
                
                with st.spinner("Téléchargement des données détaillées..."):
                    streams = get_activity_streams(selected_act_id, st.session_state.access_token)

                # Calculs Micro
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
                    
                    st.markdown("#### ⛰️ Superposition Cardio / Altitude")
                    if streams:
                        fig_stream = go.Figure()
                        if 'distance' in streams:
                            x_data = streams['distance']['data']
                            x_title = "Distance (m)"
                        elif 'time' in streams:
                            x_data = streams['time']['data']
                            x_title = "Temps (s)"
                        else:
                            x_data = []
                        
                        if len(x_data) > 0:
                            if 'altitude' in streams:
                                fig_stream.add_trace(go.Scatter(x=x_data, y=streams['altitude']['data'], fill='tozeroy', name='Altitude', line=dict(color='gray', width=0), opacity=0.3))
                            if 'heartrate' in streams:
                                fig_stream.add_trace(go.Scatter(x=x_data, y=streams['heartrate']['data'], name='Cardio', line=dict(color='red', width=2), yaxis='y2'))
                            
                            fig_stream.update_layout(
                                xaxis=dict(title=x_title),
                                yaxis=dict(title="Altitude (m)", showgrid=False),
                                yaxis2=dict(title="BPM", overlaying='y', side='right', showgrid=False),
                                margin=dict(l=0, r=0, t=0, b=0), height=300, showlegend=True
                            )
                            st.plotly_chart(fig_stream, use_container_width=True)
                        else:
                            st.warning("Données détaillées illisibles.")
                    else:
                        st.info("Pas de streams disponibles.")
            else:
                st.info("Aucune activité.")

        # =================================================
        # PAGE 3 : LE LABORATOIRE
        # =================================================
        with tab_labo:
            st.markdown("### 🧪 Tendances Long Terme")
            if not df_filtered.empty:
                col_l1, col_l2 = st.columns(2)
                with col_l1:
                    st.markdown("#### 📉 Nuage de Corrélation")
                    if 'average_heartrate' in df_filtered.columns:
                        df_filtered['speed_kmh'] = df_filtered['average_speed'] * 3.6
                        fig_corr = px.scatter(df_filtered, x="speed_kmh", y="average_heartrate", 
                                              color="start_date_local",
                                              labels={"speed_kmh": "Vitesse (km/h)", "average_heartrate": "FC Moyenne"})
                        st.plotly_chart(fig_corr, use_container_width=True)
                    else:
                        st.info("Pas de données cardio.")
                with col_l2:
                    st.markdown("#### 🍩 Volume par Zone")
                    def categorize_zone(hr):
                        if hr < 145: return "Z1/Z2 (Endurance)"
                        elif hr < 160: return "Z3 (Tempo)"
                        else: return "Z4/Z5 (Intensité)"
                    
                    if 'average_heartrate' in df_filtered.columns:
                        df_filtered['zone'] = df_filtered['average_heartrate'].apply(categorize_zone)
                        fig_pie = px.pie(df_filtered, names='zone', values='distance_km', 
                                         color_discrete_map={"Z1/Z2 (Endurance)": "green", "Z3 (Tempo)": "orange", "Z4/Z5 (Intensité)": "red"})
                        st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Pas d'activités.")

        # =================================================
        # PAGE 4 : LE CABINET DU DOC
        # =================================================
        with tab_doc:
            st.markdown("### 🩺 Prévention & Santé")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                with st.container(border=True):
                    st.markdown("#### 🚑 Ratio ACWR")
                    acwr_val = last_metrics['ACWR']
                    fig_acwr = go.Figure(go.Indicator(
                        mode = "gauge+number", value = acwr_val,
                        gauge = {'axis': {'range': [0, 2.5]},
                                 'steps': [{'range': [0, 0.8], 'color': "lightgray"}, 
                                           {'range': [0.8, 1.3], 'color': "green"},
                                           {'range': [1.3, 1.5], 'color': "orange"}, 
                                           {'range': [1.5, 2.5], 'color': "red"}],
                                 'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': acwr_val}}
                    ))
                    fig_acwr.update_layout(height=200)
                    st.plotly_chart(fig_acwr, use_container_width=True)
            with col_d2:
                with st.container(border=True):
                    st.markdown("#### 👟 Suivi Usure Chaussures Global")
                    total_km_run = df[df['type']=='Run']['distance_km'].sum()
                    max_km_shoe = 800
                    percent_wear = min(total_km_run / max_km_shoe, 1.0)
                    st.progress(percent_wear)
                    st.write(f"**Kilométrage Running total :** {int(total_km_run)} km")

    else:
        st.info("Aucune activité trouvée pour ce filtre.")
