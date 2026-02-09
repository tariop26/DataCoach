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

# --- STYLES CSS PERSONNALISÉS (BENTO PRO + DUAL + COACH) ---
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
    
    /* Bento Dual (7j vs 30j) */
    .bento-dual {
        background-color: transparent; 
        border: 1px solid rgba(128, 128, 128, 0.3);
        border-radius: 12px;
        padding: 15px 20px;
        margin-bottom: 15px;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    
    .dual-left {
        text-align: left;
        flex: 1;
    }
    
    .dual-sep {
        width: 1px;
        height: 50px;
        background-color: rgba(128,128,128,0.2);
        margin: 0 20px;
    }
    
    .dual-right {
        text-align: right;
        flex: 1;
        opacity: 0.9;
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
    .metric-value-small {
        font-size: 1.4rem;
        font-weight: 700;
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
    .metric-label-small {
        font-size: 0.75rem;
        font-weight: 600;
        opacity: 0.6;
        text-transform: uppercase;
        margin-bottom: 3px;
    }
    .metric-sub {
        font-size: 0.85rem;
        opacity: 0.8;
        font-weight: 500;
        margin-top: 2px;
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
    
    /* NOUVEAU : Espace Commentaire Data Coach */
    .coach-comment-box {
        background-color: #f8fafc; /* Gris très clair/Bleuté */
        border-left: 6px solid #2563eb; /* Bleu Roi */
        border-radius: 8px;
        padding: 25px;
        margin: 25px 0;
        position: relative;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
    }
    .coach-avatar {
        font-size: 2rem;
        position: absolute;
        top: -15px;
        left: -15px;
        background: white;
        border-radius: 50%;
        padding: 5px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .coach-title {
        font-weight: 800;
        color: #1e40af;
        text-transform: uppercase;
        font-size: 0.9rem;
        margin-bottom: 10px;
        letter-spacing: 0.05em;
    }
    .coach-text {
        color: #334155;
        font-size: 1.05rem;
        line-height: 1.7;
    }
    /* Mode sombre compatible */
    @media (prefers-color-scheme: dark) {
        .coach-comment-box {
            background-color: rgba(30, 41, 59, 0.5);
            color: #e2e8f0;
        }
        .coach-text {
            color: #cbd5e1;
        }
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

    if goal_type == "Prépa Marathon":
        if days_remaining > 120:
            phase = "Développement Général"
            advice = f"Il reste {weeks_remaining} semaines. C'est le moment de construire la caisse (Volume) sans intensité spécifique."
        elif 60 < days_remaining <= 120:
            phase = "Cycle Spécifique 1"
            advice = "On rentre dans le dur. Les sorties longues doivent commencer à s'allonger."
        elif 21 < days_remaining <= 60:
            phase = "Pic de Charge"
            advice = "C'est les semaines les plus dures. Le volume doit être à son maximum."
        elif 0 <= days_remaining <= 21:
            phase = "Affûtage (Tapering)"
            advice = "Le travail est fait. Il faut maintenant réduire le volume pour faire monter la fraîcheur."
        else:
            phase = "Récupération"
            advice = "Bravo pour l'effort."
    elif goal_type in ["Prépa 10km", "Prépa Semi"]:
        if days_remaining > 60:
            phase = "Foncier & Vitesse"
            advice = "Travaille les extrêmes : Footings lents et Vitesse pure."
        elif 14 < days_remaining <= 60:
            phase = "Spécifique Allure"
            advice = f"Il reste {weeks_remaining} semaines. Tes séances doivent inclure des répétitions à l'allure cible."
        elif 0 <= days_remaining <= 14:
            phase = "Fraîcheur"
            advice = "Réduis la durée des séances mais garde un peu d'intensité."
        else:
            phase = "Terminé"
            advice = "Objectif passé."
    else:
        phase = "Régularité & Plaisir"
        advice = "L'important c'est la consistance."

    full_text = f"**J-{days_remaining}** ({weeks_remaining} semaines) • **{phase}**\n\n{advice}"
    return full_text, phase

def generate_expert_advice(goal_type, goal_date_str, vol_7d, vol_30d, user_note):
    """
    Moteur de règles expert pour générer le commentaire du Data Coach.
    Prend en compte :
    - Le type d'objectif
    - Le temps restant (deadline)
    - Le volume actuel (7j) et la tendance (30j)
    - Les notes utilisateur (ex: chrono visé)
    """
    if not goal_date_str or not goal_type:
        return "👋 **Bienvenue !**\n\nPour que je puisse t'aider efficacement, commence par définir ton **Objectif** et sa **Date** dans la barre latérale gauche. C'est la base de toute stratégie !"

    try:
        target_date = datetime.strptime(goal_date_str, "%Y-%m-%d")
    except:
        return "Erreur de date."

    days_remaining = (target_date - datetime.now()).days
    weeks_remaining = max(0, days_remaining // 7)
    
    # Estimation de la tendance
    avg_week_vol_30d = vol_30d / 4
    trend_arrow = "stable"
    if vol_7d > avg_week_vol_30d * 1.1: trend_arrow = "en hausse"
    elif vol_7d < avg_week_vol_30d * 0.9: trend_arrow = "en baisse"
    
    # Détection d'objectif de performance (chrono)
    has_time_goal = False
    if user_note and any(char.isdigit() for char in user_note):
        has_time_goal = True # Simplifié, détecte s'il y a des chiffres dans la note
    
    intro = f"Analyse pour ton objectif **{goal_type}** dans **{weeks_remaining} semaines** :"
    advice = ""
    alert = ""

    # --- LOGIQUE MARATHON ---
    if goal_type == "Prépa Marathon":
        min_vol_marathon = 40 # Volume mini tolérable pour finir
        target_vol_marathon = 60 # Volume cible standard

        if has_time_goal: target_vol_marathon = 70 # Plus exigeant si chrono visé

        if days_remaining > 90: # > 3 mois
            if vol_7d < 20:
                advice = f"On est encore loin (J-{days_remaining}), mais attention : ton volume actuel ({int(vol_7d)}km) est très faible pour envisager un marathon. Il faut construire la machine dès maintenant. L'objectif est d'atteindre progressivement 30-40km/semaine d'ici le mois prochain."
            else:
                advice = f"Tu es dans la phase de construction. Ton volume de {int(vol_7d)}km est cohérent pour le moment. Profite de cette période loin de l'échéance pour travailler ta VMA courte et ton renforcement musculaire, avant d'attaquer les sorties très longues."
        
        elif 30 < days_remaining <= 90: # 1 à 3 mois (Cœur de prépa)
            if vol_7d < min_vol_marathon:
                alert = "🚨 **ALERTE VOLUME**"
                advice = f"Tu entres dans le dur de la prépa et tu n'as couru que {int(vol_7d)}km cette semaine. C'est insuffisant pour préparer ton corps aux chocs du 42km. Pour éviter le 'mur' au 30ème km, tu dois impérativement augmenter la durée de tes sorties longues. Vise au moins {min_vol_marathon}-{target_vol_marathon}km par semaine dès maintenant."
            elif vol_7d > target_vol_marathon:
                advice = f"Excellent travail ! Avec {int(vol_7d)}km, tu es en pleine charge. Attention toutefois à ne pas te griller : si tu sens une fatigue persistante, n'hésite pas à faire une semaine d'assimilation (baisse de 30% du volume) avant de repartir."
            else:
                advice = f"Tu es sur la bonne voie ({int(vol_7d)}km). Assure-toi que ta sortie longue hebdomadaire commence à dépasser 1h45. C'est le pilier de ta réussite."
        
        elif 14 < days_remaining <= 30: # Le pic et début affûtage
            if vol_7d < min_vol_marathon:
                advice = f"C'est la dernière ligne droite. Ton volume est un peu léger ({int(vol_7d)}km). Ne cherche pas à rattraper le retard perdu maintenant, tu risquerais la blessure. Concentre-toi sur la qualité : maintiens une sortie longue mais réduis le reste."
            else:
                advice = "Tu as fait le job. Le plus gros volume est derrière toi. Commence à penser à la fraîcheur. Dors, hydrate-toi, et ne tente plus de séances héroïques."
                
        elif 0 <= days_remaining <= 14: # Affûtage
            if trend_arrow == "en hausse":
                alert = "🛑 **STOP !**"
                advice = f"Tu en fais trop ! À J-{days_remaining}, tu devrais réduire ton volume, pas l'augmenter ! Tu es à {int(vol_7d)}km alors que tu devrais être en mode économie d'énergie. Fais du jus, pas des kilomètres."
            else:
                advice = "Mode 'Affûtage' activé. Tu réduis le volume, c'est parfait. Garde juste quelques rappels d'allure marathon (ex: 2x10min) pour garder le rythme, mais le reste doit être du footing facile. La confiance est là."

    # --- LOGIQUE 10KM / SEMI ---
    elif goal_type in ["Prépa 10km", "Prépa Semi"]:
        is_semi = "Semi" in goal_type
        target_vol = 40 if is_semi else 30
        
        if days_remaining > 45:
            advice = f"Tu as le temps. Travaille ta vitesse de base. Ton volume de {int(vol_7d)}km est une base de travail. Essaie d'intégrer une séance de fractionné court (type 30/30) pour débrider le moteur."
        elif 14 < days_remaining <= 45:
            if vol_7d < (target_vol * 0.7):
                advice = f"Il faut passer la seconde. {int(vol_7d)}km/semaine, c'est un peu juste pour performer sur {goal_type}. Essaie d'ajouter un footing de 30min ou d'allonger ta sortie du week-end."
            else:
                advice = f"Bonne dynamique ({int(vol_7d)}km). C'est le moment de travailler l'allure spécifique : tes séances doivent inclure des blocs à la vitesse que tu vises le jour J."
        else: # < 14j
             advice = "Fais du jus. Réduis la durée des séances de 30 à 50% mais garde de l'intensité. Tes jambes doivent fourmiller d'envie de courir."

    # --- AUTRES ---
    else:
        if vol_7d < 10:
            advice = "La régularité est la clé de tout progrès. Essaie de courir au moins 2 fois par semaine, même 20 minutes. C'est mieux qu'une grosse sortie tous les 15 jours."
        elif vol_7d > 40 and goal_type == "Entretien / Plaisir":
            advice = f"Tu cours beaucoup ({int(vol_7d)}km) pour un objectif 'Plaisir' ! C'est top. Si tu ne prépares rien de spécial, écoute juste tes envies et varie les terrains pour ne pas t'ennuyer."
        else:
            advice = f"Tu maintiens un bon cap ({int(vol_7d)}km cette semaine). Continue comme ça."

    # Assemblage
    final_html = f"""
    <div class="coach-comment-box">
        <div class="coach-avatar">🤖</div>
        <div class="coach-title">L'Œil du Data Coach</div>
        <div class="coach-text">
            {alert + ' ' if alert else ''}{advice}
        </div>
    </div>
    """
    return final_html

# Helper variation
def calc_delta(curr, prev):
    if prev == 0: return 0 if curr == 0 else 100
    return int(((curr - prev) / prev) * 100)

def format_delta(val):
    sign = "+" if val > 0 else ""
    color = "#22c55e" if val >= 0 else "#f97316" 
    return f'<span style="color:{color}; font-weight:bold; font-size:0.85rem;">{sign}{val}%</span>'

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
        # activities = strava_auth.get_activities(st.session_state.access_token, per_page=200) # Fonction hypothétique
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
            default_start = max_date - timedelta(days=30)
            date_range = st.date_input("Sélectionner la période", [default_start, max_date], min_value=min_date, max_value=max_date)
            
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
        df_display = df[(df['start_date_local'].dt.date >= start_filter) & (df['start_date_local'].dt.date <= end_filter)].copy()
        
        if selected_type_fr != "Tous":
            df_display = df_display[df_display['type_fr'] == selected_type_fr]
            df_metrics_source = df[df['type_fr'] == selected_type_fr].copy() 
        else:
            df_metrics_source = df.copy()

        df_daily_metrics = calculate_training_metrics(df_metrics_source)
        
        # Time Machine Metrics for Verdict/Gauges
        current_metrics_date = pd.Timestamp(end_filter)
        try:
            idx_loc = df_daily_metrics.index.get_indexer([current_metrics_date], method='pad')[0]
            if idx_loc != -1: last_metrics = df_daily_metrics.iloc[idx_loc]
            else: last_metrics = df_daily_metrics.iloc[-1]
        except: last_metrics = df_daily_metrics.iloc[-1]

        # --- CALCUL DES PÉRIODES (7j / 30j / Comparatifs) ---
        # Dates clés
        date_end = pd.Timestamp(end_filter)
        date_7d = date_end - timedelta(days=7)
        date_14d = date_end - timedelta(days=14)
        date_30d = date_end - timedelta(days=30)
        date_60d = date_end - timedelta(days=60)
        
        # Sous-ensembles de données pour les calculs
        # 7 Jours Courant vs Précédent
        sub_7_curr = df_metrics_source[(df_metrics_source['start_date_local'] > date_7d) & (df_metrics_source['start_date_local'] <= date_end)]
        sub_7_prev = df_metrics_source[(df_metrics_source['start_date_local'] > date_14d) & (df_metrics_source['start_date_local'] <= date_7d)]
        
        # 30 Jours Courant vs Précédent
        sub_30_curr = df_metrics_source[(df_metrics_source['start_date_local'] > date_30d) & (df_metrics_source['start_date_local'] <= date_end)]
        sub_30_prev = df_metrics_source[(df_metrics_source['start_date_local'] > date_60d) & (df_metrics_source['start_date_local'] <= date_30d)]
        
        # Métriques Distance
        d7_c = sub_7_curr['distance_km'].sum()
        d7_p = sub_7_prev['distance_km'].sum()
        d7_delta = calc_delta(d7_c, d7_p)
        
        d30_c = sub_30_curr['distance_km'].sum()
        d30_p = sub_30_prev['distance_km'].sum()
        d30_delta = calc_delta(d30_c, d30_p)
        
        # Métriques D+
        e7_c = sub_7_curr['total_elevation_gain'].sum()
        e7_p = sub_7_prev['total_elevation_gain'].sum()
        e7_delta = calc_delta(e7_c, e7_p)
        
        e30_c = sub_30_curr['total_elevation_gain'].sum()
        e30_p = sub_30_prev['total_elevation_gain'].sum()
        e30_delta = calc_delta(e30_c, e30_p)
        
        # Métriques Temps
        t7_c = sub_7_curr['moving_time'].sum()
        t7_p = sub_7_prev['moving_time'].sum()
        t7_delta = calc_delta(t7_c, t7_p)
        
        t30_c = sub_30_curr['moving_time'].sum()
        t30_p = sub_30_prev['moving_time'].sum()
        t30_delta = calc_delta(t30_c, t30_p)


        # --- UI TABS ---
        tab_cockpit, tab_micro, tab_labo = st.tabs(["🚀 Planification & Cockpit", "🔬 Microscope", "🧪 Laboratoire"])

        with tab_cockpit:
            
            # --- BLOC OBJECTIF (TOP) ---
            if user_goal and user_goal.get("date"):
                st.markdown(f"### 🎯 Cap sur l'objectif : {user_goal.get('type')}")
                analysis_text, phase_name = analyze_goal_context(user_goal.get("type"), user_goal.get("date"), d7_c, last_metrics['CTL'])
                if analysis_text:
                    st.markdown(f"""<div class="goal-card"><div class="goal-phase">{phase_name}</div><div class="metric-insight" style="border:none; margin:0; opacity:1; color:#1e3a8a;">{analysis_text}</div></div>""", unsafe_allow_html=True)
            else:
                st.info("👈 Définis ton objectif et sa date dans la barre latérale pour activer l'analyse stratégique.")

            # --- ÉTAT DES LIEUX (BENTO DUAL) ---
            st.subheader(f"📅 État des lieux (Finissant le {end_filter.strftime('%d/%m')})")
            
            col_d_1, col_d_2, col_d_3 = st.columns(3)
            
            # BENTO DISTANCE
            with col_d_1:
                st.markdown(f"""
                <div class="bento-dual">
                    <div class="dual-left">
                        <div class="metric-label">Volume 7j</div>
                        <div class="metric-value">{int(d7_c)} km</div>
                        <div class="metric-sub">vs prev: {format_delta(d7_delta)}</div>
                    </div>
                    <div class="dual-sep"></div>
                    <div class="dual-right">
                        <div class="metric-label-small">30 Jours</div>
                        <div class="metric-value-small">{int(d30_c)} km</div>
                        <div class="metric-sub" style="font-size:0.75rem;">{format_delta(d30_delta)}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # BENTO D+
            with col_d_2:
                st.markdown(f"""
                <div class="bento-dual">
                    <div class="dual-left">
                        <div class="metric-label">Dénivelé 7j</div>
                        <div class="metric-value">{int(e7_c)} m</div>
                        <div class="metric-sub">vs prev: {format_delta(e7_delta)}</div>
                    </div>
                    <div class="dual-sep"></div>
                    <div class="dual-right">
                        <div class="metric-label-small">30 Jours</div>
                        <div class="metric-value-small">{int(e30_c)} m</div>
                        <div class="metric-sub" style="font-size:0.75rem;">{format_delta(e30_delta)}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
            # BENTO TEMPS
            with col_d_3:
                st.markdown(f"""
                <div class="bento-dual">
                    <div class="dual-left">
                        <div class="metric-label">Chrono 7j</div>
                        <div class="metric-value" style="font-size:1.8rem;">{format_duration(t7_c)}</div>
                        <div class="metric-sub">vs prev: {format_delta(t7_delta)}</div>
                    </div>
                    <div class="dual-sep"></div>
                    <div class="dual-right">
                        <div class="metric-label-small">30 Jours</div>
                        <div class="metric-value-small" style="font-size:1.2rem;">{format_duration(t30_c)}</div>
                        <div class="metric-sub" style="font-size:0.75rem;">{format_delta(t30_delta)}</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # --- ANALYSE DE CORRÉLATION (EXPERT ADVICE) ---
            # C'est ici que l'on insère le bloc "Locace"
            if user_goal and user_goal.get("date"):
                coach_html = generate_expert_advice(
                    user_goal.get("type"), 
                    user_goal.get("date"), 
                    d7_c, 
                    d30_c, 
                    user_goal.get("note")
                )
                st.markdown(coach_html, unsafe_allow_html=True)

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
            start_graph = start_filter - timedelta(days=14)
            df_g = df_daily_metrics[(df_daily_metrics.index.date >= start_graph) & (df_daily_metrics.index.date <= end_filter)]
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_g.index, y=df_g['CTL'], fill='tozeroy', name='Forme', line=dict(color='#3b82f6')))
            fig.add_trace(go.Scatter(x=df_g.index, y=df_g['ATL'], name='Fatigue', line=dict(color='#f97316')))
            fig.update_layout(height=300, margin=dict(l=0,r=0,t=10,b=0), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

        with tab_micro:
            st.info("Sélectionne une activité dans la barre latérale ou via les filtres pour analyser.")

        with tab_labo:
            st.info("Laboratoire des tendances long terme.")

    else:
        st.info("Aucune donnée disponible pour cette période.")
