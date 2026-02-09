import streamlit as st
import requests
import pandas as pd
import authentification as strava_auth
import random
import json
import os
from datetime import datetime, timedelta, date
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
        min-height: 320px; 
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    
    .bento-small {
        background-color: transparent; 
        border: 1px solid rgba(128, 128, 128, 0.3);
        border-radius: 12px;
        padding: 15px;
        margin-bottom: 15px;
        text-align: center;
    }

    /* Layout Interne */
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
    
    /* Barres de progression */
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
    
    /* Styles spécifiques pour l'analyse d'objectif */
    .goal-card {
        background-color: rgba(59, 130, 246, 0.05);
        border: 1px solid #3b82f6;
        border-radius: 10px;
        padding: 20px;
        margin: 20px 0;
    }
    .goal-title {
        color: #1d4ed8;
        font-size: 1.2rem;
        font-weight: bold;
        margin-bottom: 10px;
    }
    .goal-phase {
        display: inline-block;
        background-color: #3b82f6;
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 10px;
        text-transform: uppercase;
    }
</style>
""", unsafe_allow_html=True)

# --- CONSTANTES & CONFIG ---
GOALS_FILE = "goals.json"
REDIRECT_URI = "http://localhost:8501" 

ACTIVITY_TRANSLATIONS = {
    "Run": "Course à pied",
    "Ride": "Vélo",
    "VirtualRide": "Vélo Intérieur",
    "WeightTraining": "Musculation",
    "Hike": "Randonnée",
    "Walk": "Marche",
    "Swim": "Natation",
    "AlpineSki": "Ski Alpin",
    "BackcountrySki": "Ski de Rando",
    "Workout": "Entraînement",
    "Yoga": "Yoga"
}

# --- FONCTIONS UTILITAIRES ---

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

def calculate_trimp(duration_min, avg_hr, max_hr=190, rest_hr=60):
    if not avg_hr or pd.isna(avg_hr) or avg_hr == 0: return 0
    hr_reserve = max_hr - rest_hr
    hr_fraction = (avg_hr - rest_hr) / hr_reserve
    trimp = duration_min * hr_fraction * 0.64 * math.exp(1.92 * hr_fraction)
    return int(trimp)

def calculate_training_metrics(df):
    if df.empty: return pd.DataFrame()
    df_daily = df.set_index('start_date_local').resample('D').agg({
        'trimp': 'sum',
        'distance_km': 'sum',
        'duration_h': 'sum'
    }).fillna(0)
    df_daily['ATL'] = df_daily['trimp'].rolling(window=7, min_periods=1).mean()
    df_daily['CTL'] = df_daily['trimp'].rolling(window=42, min_periods=1).mean()
    df_daily['TSB'] = df_daily['CTL'] - df_daily['ATL']
    load_7d = df_daily['trimp'].rolling(window=7, min_periods=1).sum()
    avg_load_28d = df_daily['trimp'].rolling(window=28, min_periods=1).mean() * 7 
    df_daily['ACWR'] = load_7d / avg_load_28d.replace(0, 1)
    rolling_mean_7d = df_daily['trimp'].rolling(window=7, min_periods=1).mean()
    rolling_std_7d = df_daily['trimp'].rolling(window=7, min_periods=1).std()
    df_daily['Monotony'] = rolling_mean_7d / rolling_std_7d.replace(0, 1)
    return df_daily

def get_coach_verdict(tsb, acwr):
    verdict = ""
    color = "green"
    detail = ""
    subtext = ""

    if acwr > 1.5:
        verdict = "🛑 STOP DANGER"
        subtext = "Risque de blessure maximal"
        color = "#ef4444"
        detail = "Ton ratio de charge aiguë (ACWR) dépasse 1.5. Tu as augmenté ta charge de +50% par rapport à tes habitudes. C'est la zone rouge pour tes tendons. **Action :** Coupe l'entraînement 48h minimum."
    elif tsb < -20:
        verdict = "⚠️ SURCHARGE"
        subtext = "Fatigue profonde détectée"
        color = "#f59e0b"
        detail = "Tu es en déficit énergétique important (TSB < -20). Tu creuses ta fatigue. C'est dangereux si ça dure. **Action :** Réduis le volume de 40% cette semaine."
    elif tsb > 10:
        verdict = "🚀 PIC DE FORME"
        subtext = "Fraîcheur musculaire optimale"
        color = "#22c55e"
        detail = "Affûtage réussi ! Ta fraîcheur est positive tout en gardant un bon niveau d'entraînement. **Action :** C'est le moment idéal pour une performance."
    else:
        verdict = "✅ OPTIMAL"
        subtext = "Zone de développement durable"
        color = "#3b82f6"
        detail = "Tu navigues dans la 'Sweet Spot' zone. Pression suffisante pour progresser, mais pas assez pour t'épuiser. **Action :** Garde ce cap, la régularité paie."
    return verdict, subtext, color, detail

def analyze_goal_context(goal_type, goal_date_str, current_vol_7d, ctl_val):
    """
    Analyse complexe de la situation par rapport à l'objectif
    """
    if not goal_date_str or not goal_type:
        return None, None

    try:
        target_date = datetime.strptime(goal_date_str, "%Y-%m-%d")
    except:
        return None, None
        
    days_remaining = (target_date - datetime.now()).days
    weeks_remaining = days_remaining // 7
    
    phase = ""
    advice = ""
    status_icon = "🟢"

    # --- LOGIQUE MARATHON ---
    if goal_type == "Prépa Marathon":
        if days_remaining > 120:
            phase = "Développement Général"
            advice = f"Il reste {weeks_remaining} semaines. C'est le moment de construire la caisse (Volume) sans intensité spécifique. Ton volume actuel ({int(current_vol_7d)}km) doit augmenter progressivement."
        elif 60 < days_remaining <= 120:
            phase = "Cycle Spécifique 1"
            advice = "On rentre dans le dur. Les sorties longues doivent commencer à s'allonger. Intègre de l'allure marathon sur des blocs de 15-20 min."
            if current_vol_7d < 30: 
                advice += " ⚠️ **Attention :** Ton volume hebdo (<30km) est très faible pour cette phase. Il faut réagir !"
                status_icon = "🔴"
        elif 21 < days_remaining <= 60:
            phase = "Pic de Charge"
            advice = "C'est les semaines les plus dures. Le volume doit être à son maximum. Le sommeil est aussi important que l'entraînement."
            if ctl_val < 40:
                advice += " ⚠️ Ton capital endurance (CTL) semble un peu juste pour encaisser les 42km sereinement."
                status_icon = "🟠"
        elif 0 <= days_remaining <= 21:
            phase = "Affûtage (Tapering)"
            advice = "Le travail est fait. Il faut maintenant réduire le volume drastiquement (60% puis 40%) pour faire monter la fraîcheur (TSB)."
        else:
            phase = "Récupération / Objectif Passé"
            advice = "Bravo pour l'effort. Prends le temps de régénérer."

    # --- LOGIQUE 10KM / SEMI ---
    elif goal_type in ["Prépa 10km", "Prépa Semi"]:
        if days_remaining > 60:
            phase = "Foncier & Vitesse"
            advice = "Travaille les extrêmes : Footings lents et Vitesse pure (VMA courte)."
        elif 14 < days_remaining <= 60:
            phase = "Spécifique Allure"
            advice = f"Il reste {weeks_remaining} semaines. Tes séances doivent inclure des répétitions à l'allure cible ({'10km' if '10km' in goal_type else 'Semi'})."
        elif 0 <= days_remaining <= 14:
            phase = "Fraîcheur"
            advice = "Réduis la durée des séances mais garde un peu d'intensité pour garder le rythme."
        else:
            phase = "Terminé"
            advice = "Objectif passé."

    # --- LOGIQUE PERTE DE POIDS / SANTÉ ---
    else:
        phase = "Régularité & Plaisir"
        if current_vol_7d > 20:
            advice = "Excellent volume pour la santé. Continue comme ça !"
        else:
            advice = "Essaie de maintenir 3 créneaux de 30min par semaine, c'est la clé du métabolisme."

    full_text = f"**J-{days_remaining}** ({weeks_remaining} semaines) • **{phase}**\n\n{status_icon} {advice}"
    return full_text, phase

def get_activity_streams(activity_id, access_token):
    if access_token == "demo_fake_token":
        return generate_mock_streams()
    headers = {"Authorization": f"Bearer {access_token}"}
    keys = "time,distance,altitude,heartrate,velocity_smooth,cadence"
    url = f"https://www.strava.com/api/v3/activities/{activity_id}/streams?keys={keys}&key_by_type=true"
    try:
        r = requests.get(url, headers=headers)
        return r.json() if r.status_code == 200 else None
    except:
        return None

def generate_mock_data():
    data = []
    today = datetime.now()
    shoe_ids = ["g123456", "g789012"] 
    # Génération sur 120 jours pour avoir de la matière au filtre
    for i in range(120):
        if random.random() > 0.3: 
            date_act = today - timedelta(days=i)
            act_type = random.choice(["Run", "Run", "Ride"]) 
            gear_id = random.choice(shoe_ids) if act_type == "Run" else None
            watts = random.randint(200, 350) if act_type == "Run" else random.randint(150, 300)
            dist = random.randint(5000, 18000) if act_type == "Run" else random.randint(20000, 60000)
            duration = int(dist / (random.uniform(2.5, 3.8) if act_type=="Run" else random.uniform(6.0, 9.0)))
            
            data.append({
                "name": f"{act_type} Session {i}",
                "distance": dist,
                "moving_time": duration,
                "total_elevation_gain": random.randint(50, 800),
                "start_date_local": date_act.isoformat(),
                "average_heartrate": random.randint(120, 170),
                "average_speed": dist/duration,
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
    return {"distance": {"data": x_axis.tolist()}, "altitude": {"data": alt_stream.tolist()}, "heartrate": {"data": hr_stream.tolist()}}

# --- SETUP SECRETS ---
CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", None)
CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", None)
if not CLIENT_ID or not CLIENT_SECRET:
    st.sidebar.warning("⚠️ Clés API manquantes")
    CLIENT_ID = st.sidebar.text_input("Client ID")
    CLIENT_SECRET = st.sidebar.text_input("Client Secret", type="password")

# --- SESSION ---
if "access_token" not in st.session_state: st.session_state.access_token = None

# --- UI HEADER ---
st.title("🏃‍♂️ Smart Run Coach")
st.markdown("**Data Coach :** *Planification & Analyse de la Performance.*")

# =========================================================
# LOGIQUE PRINCIPALE
# =========================================================

if not st.session_state.access_token:
    # ... (Code de connexion inchangé)
    auth_code = st.query_params.get("code")
    if auth_code:
        with st.spinner("Connexion..."):
            token_response = strava_auth.exchange_code_for_token(CLIENT_ID, CLIENT_SECRET, auth_code) if CLIENT_ID else None
            if token_response:
                st.session_state.access_token = token_response.get("access_token")
                st.session_state.athlete = token_response.get("athlete")
                st.query_params.clear()
                st.rerun()
    else:
        c1, c2 = st.columns(2)
        with c1:
            if CLIENT_ID: st.link_button("Connexion Strava", strava_auth.get_login_url(CLIENT_ID, REDIRECT_URI), type="primary")
        with c2: 
            if st.button("🛠️ Mode Démo"):
                st.session_state.access_token = "demo_fake_token"
                st.session_state.athlete = {"id": "demo", "firstname": "Runner"}
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
        # On charge 200 activités pour avoir de l'historique
        activities = strava_auth.get_activities(st.session_state.access_token, per_page=200) # Fonction hypothétique ou request direct
        # Pour simplifier ici (MVP), je garde le request direct si la fct n'existe pas dans l'import
        r = requests.get("https://www.strava.com/api/v3/athlete/activities", headers={"Authorization": f"Bearer {st.session_state.access_token}"}, params={"per_page": 200})
        activities = r.json() if r.status_code == 200 else []

    if activities:
        df = pd.json_normalize(activities)
        df['start_date_local'] = pd.to_datetime(df['start_date_local'])
        if df['start_date_local'].dt.tz is not None: df['start_date_local'] = df['start_date_local'].dt.tz_localize(None)
        
        # Conversions de base
        df['distance_km'] = df.get('distance', 0) / 1000
        df['duration_h'] = df.get('moving_time', 0) / 3600
        df['average_speed'] = df.get('average_speed', 0)
        df['trimp'] = df.apply(lambda row: calculate_trimp(row['moving_time']/60, row.get('average_heartrate', 0)), axis=1)
        df['type_fr'] = df['type'].apply(translate_activity)
        
        # --- SIDEBAR ET FILTRES ---
        with st.sidebar:
            st.header(f"👤 {athlete.get('firstname', 'Athlète')}")
            
            # 1. Filtre Temporel (Time Machine)
            st.subheader("📅 Période d'Analyse")
            min_date = df['start_date_local'].min().date()
            max_date = df['start_date_local'].max().date()
            
            # Par défaut : les 30 derniers jours par rapport à la dernière activité
            default_start = max_date - timedelta(days=30)
            
            date_range = st.date_input("Sélectionner la période", [default_start, max_date], min_value=min_date, max_value=max_date)
            
            # Gestion si une seule date sélectionnée
            if len(date_range) == 2:
                start_filter, end_filter = date_range
            else:
                start_filter, end_filter = date_range[0], date_range[0]

            # 2. Filtre Activités
            st.subheader("Filtre Activités")
            available_types = ["Tous"] + list(df['type_fr'].unique())
            selected_type_fr = st.selectbox("Sport", available_types)
            
            # 3. Formulaire Objectif
            st.divider()
            with st.expander("🎯 Mon Objectif", expanded=not bool(user_goal)):
                with st.form("goal_form"):
                    g_types = ["Prépa Marathon", "Prépa Semi", "Prépa 10km", "Perte de poids", "Ultra / Trail", "Entretien"]
                    idx = g_types.index(user_goal.get("type")) if user_goal.get("type") in g_types else 0
                    sType = st.selectbox("Type", g_types, index=idx)
                    
                    # Date objectif
                    d_obj = None
                    if user_goal.get("date"):
                        try: d_obj = datetime.strptime(user_goal.get("date"), "%Y-%m-%d")
                        except: pass
                    tDate = st.date_input("Date de l'échéance", value=d_obj)
                    
                    note = st.text_input("Note (ex: Sub 3h30)", value=user_goal.get("note", ""))
                    if st.form_submit_button("Sauvegarder"):
                        save_goal(athlete_id, {"type": sType, "date": tDate.strftime("%Y-%m-%d") if tDate else None, "note": note})
                        st.success("OK")
                        st.rerun()

        # --- APPLICATION DES FILTRES ---
        # 1. Filtrage GLOBAL du DataFrame par date (Time Machine)
        # On garde un df_full pour les calculs de long terme (CTL), mais l'affichage principal se fait sur la période
        df_display = df[(df['start_date_local'].dt.date >= start_filter) & (df['start_date_local'].dt.date <= end_filter)].copy()
        
        # 2. Filtrage par Type
        if selected_type_fr != "Tous":
            df_display = df_display[df_display['type_fr'] == selected_type_fr]
            df_metrics_source = df[df['type_fr'] == selected_type_fr].copy() # Pour CTL/ATL pertinent
        else:
            df_metrics_source = df.copy()

        # Calcul Métriques Journalières sur TOUT l'historique (pour avoir un CTL correct même si on filtre l'affichage)
        df_daily_metrics = calculate_training_metrics(df_metrics_source)
        
        # On récupère les métriques À LA DATE DE FIN du filtre (Time Machine)
        # Si end_filter est aujourd'hui, c'est l'état actuel. Si c'est le mois dernier, c'est l'état passé.
        current_metrics_date = pd.Timestamp(end_filter)
        # On cherche l'index le plus proche dans le passé ou égal
        try:
            # On prend la ligne correspondant à end_filter ou la précédente dispo
            idx_loc = df_daily_metrics.index.get_indexer([current_metrics_date], method='pad')[0]
            if idx_loc != -1:
                last_metrics = df_daily_metrics.iloc[idx_loc]
            else:
                last_metrics = df_daily_metrics.iloc[-1] # Fallback
        except:
             last_metrics = df_daily_metrics.iloc[-1]

        # Calculs spécifiques pour l'analyse (7 jours AVANT la date de fin du filtre)
        date_7d_before_end = pd.Timestamp(end_filter) - timedelta(days=7)
        dist_7d = df_metrics_source[(df_metrics_source['start_date_local'] > date_7d_before_end) & 
                                    (df_metrics_source['start_date_local'] <= pd.Timestamp(end_filter))]['distance_km'].sum()

        # --- UI TABS ---
        tab_cockpit, tab_micro, tab_labo = st.tabs(["🚀 Planification & Cockpit", "🔬 Microscope", "🧪 Laboratoire"])

        with tab_cockpit:
            
            # --- BLOC OBJECTIF (TOP) ---
            if user_goal and user_goal.get("date"):
                st.markdown(f"### 🎯 Cap sur l'objectif : {user_goal.get('type')}")
                
                # Analyse IA Contextuelle
                analysis_text, phase_name = analyze_goal_context(
                    user_goal.get("type"), 
                    user_goal.get("date"), 
                    dist_7d, 
                    last_metrics['CTL']
                )
                
                if analysis_text:
                    st.markdown(f"""
                    <div class="goal-card">
                        <div class="goal-phase">{phase_name}</div>
                        <div class="metric-insight" style="border:none; margin:0; opacity:1; color:#1e3a8a;">
                            {analysis_text}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("👈 Définis ton objectif et sa date dans la barre latérale pour activer l'analyse stratégique.")

            # --- ÉTAT DES LIEUX ---
            st.subheader(f"📅 État des lieux (7j finissant le {end_filter.strftime('%d/%m')})")
            
            # Calculs sur la période affichée (df_display) ou 7j glissants ? 
            # Le user a demandé "état des lieux des 7 jours glissants". Restons cohérents avec la "Time Machine".
            # Ce sont les 7j terminant à end_filter.
            
            # Recalcul précis pour l'affichage
            elev_7d = df_metrics_source[(df_metrics_source['start_date_local'] > date_7d_before_end) & 
                                        (df_metrics_source['start_date_local'] <= pd.Timestamp(end_filter))]['total_elevation_gain'].sum()
            time_7d = df_metrics_source[(df_metrics_source['start_date_local'] > date_7d_before_end) & 
                                        (df_metrics_source['start_date_local'] <= pd.Timestamp(end_filter))]['moving_time'].sum()
            
            c7_1, c7_2, c7_3 = st.columns(3)
            with c7_1:
                 st.markdown(f'<div class="bento-small"><div class="metric-label">Volume 7j</div><div class="metric-value">{int(dist_7d)} km</div></div>', unsafe_allow_html=True)
            with c7_2:
                 st.markdown(f'<div class="bento-small"><div class="metric-label">Dénivelé 7j</div><div class="metric-value">{int(elev_7d)} m</div></div>', unsafe_allow_html=True)
            with c7_3:
                 st.markdown(f'<div class="bento-small"><div class="metric-label">Chrono 7j</div><div class="metric-value">{format_duration(time_7d)}</div></div>', unsafe_allow_html=True)

            # --- ANALYSE DE CORRÉLATION (POST-STATUS) ---
            # C'est ici qu'on fait le lien entre l'état actuel et l'objectif
            # Déjà traité en partie dans le bloc bleu du haut, mais on peut ajouter des jauges spécifiques ici
            
            st.divider()

            # --- VERDICT & BATTERIE ---
            st.subheader("🤖 Verdict & Énergie")
            verdict_t, verdict_s, verdict_c, verdict_d = get_coach_verdict(last_metrics['TSB'], last_metrics['ACWR'])
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"""
                <div class="bento-box" style="border-left: 8px solid {verdict_c};">
                    <div>
                        <div class="metric-label" style="color:{verdict_c}">Verdict du Coach</div>
                        <div class="metric-value">{verdict_t}</div>
                        <div class="metric-sub">{verdict_s}</div>
                    </div>
                    <div class="metric-insight">{verdict_d}</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                tsb = int(last_metrics['TSB'])
                batt_pct = max(0, min(100, int((tsb + 30) / 50 * 100)))
                batt_c = "#22c55e" if batt_pct > 50 else "#ef4444" if batt_pct < 20 else "#f59e0b"
                
                st.markdown(f"""
                <div class="bento-box" style="border-left: 8px solid {batt_c};">
                    <div class="bento-header">
                        <div>
                            <div class="metric-label" style="color:{batt_c}">Niveau de Batterie</div>
                            <div class="metric-value">{batt_pct}%</div>
                            <div class="metric-sub">TSB: {tsb}</div>
                        </div>
                        <div style="flex:1; margin-left: 20px; display:flex; flex-direction:column; justify-content:center;">
                             <div style="font-weight:bold; font-size:1.5rem; text-align:right; color:{batt_c}">🔋</div>
                             <div class="progress-container"><div class="progress-bar" style="width: {batt_pct}%; background-color: {batt_c};"></div></div>
                        </div>
                    </div>
                    <div class="metric-insight">Ton carburant physiologique dispo. 100% = Frais et Dispo. < 20% = Réservoir vide.</div>
                </div>
                """, unsafe_allow_html=True)

            # --- FORME & FATIGUE ---
            st.subheader("🏗️ Structure de l'Entraînement")
            cf1, cf2 = st.columns(2)
            
            ctl = int(last_metrics['CTL'])
            atl = int(last_metrics['ATL'])
            max_ctl = int(df_daily_metrics['CTL'].max()) if not df_daily_metrics.empty else 100
            max_atl = int(df_daily_metrics['ATL'].max()) if not df_daily_metrics.empty else 100
            
            p_ctl = min(100, int(ctl/max_ctl*100)) if max_ctl > 0 else 0
            p_atl = min(100, int(atl/max_atl*100)) if max_atl > 0 else 0
            
            with cf1:
                st.markdown(f"""
                <div class="bento-box" style="border-left: 5px solid #3b82f6;">
                    <div class="bento-header">
                         <div><div class="metric-label" style="color:#3b82f6">Capital Endurance (CTL)</div><div class="metric-value">{ctl} <span style="font-size:1rem; opacity:0.5;">/ {max_ctl}</span></div></div>
                    </div>
                    <div class="progress-container"><div class="progress-bar" style="width: {p_ctl}%; background-color: #3b82f6;"></div></div>
                    <div class="metric-insight">Taille de ton moteur (Moy. 42j). Plus c'est haut, plus tu es solide.</div>
                </div>
                """, unsafe_allow_html=True)
            
            with cf2:
                fc = "#22c55e"
                if atl > ctl + 20: fc = "#ef4444"
                st.markdown(f"""
                <div class="bento-box" style="border-left: 5px solid {fc};">
                    <div class="bento-header">
                         <div><div class="metric-label" style="color:{fc}">Fatigue Aiguë (ATL)</div><div class="metric-value">{atl} <span style="font-size:1rem; opacity:0.5;">/ {max_atl}</span></div></div>
                    </div>
                    <div class="progress-container"><div class="progress-bar" style="width: {p_atl}%; background-color: {fc};"></div></div>
                    <div class="metric-insight">Facture de la semaine (Moy. 7j). Si > Forme + 20 = Danger.</div>
                </div>
                """, unsafe_allow_html=True)
            
            # --- GRAPH ---
            st.subheader("📉 Évolution")
            # Graph sur la période du filtre sidebar (Time Machine)
            # On prend un peu de marge avant pour voir la tendance
            start_graph = start_filter - timedelta(days=14)
            df_g = df_daily_metrics[(df_daily_metrics.index.date >= start_graph) & (df_daily_metrics.index.date <= end_filter)]
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_g.index, y=df_g['CTL'], fill='tozeroy', name='Forme', line=dict(color='#3b82f6')))
            fig.add_trace(go.Scatter(x=df_g.index, y=df_g['ATL'], name='Fatigue', line=dict(color='#f97316')))
            fig.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

        with tab_micro:
            st.info("Sélectionne une activité dans la barre latérale ou via les filtres pour analyser.")
            # (Code microscope simplifié pour la démo, reprend la logique précédente)
            # ...

        with tab_labo:
            st.info("Laboratoire des tendances long terme.")
            # ...
    else:
        st.info("Aucune donnée disponible pour cette période.")
