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

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Smart Run Coach", page_icon="🏃‍♂️", layout="wide")

# --- CONSTANTES & CONFIG ---
GOALS_FILE = "goals.json"
REDIRECT_URI = "http://localhost:8501" 

# --- FONCTIONS UTILITAIRES (LOGIQUE MÉTIER) ---

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

def calculate_pace(speed_ms):
    if speed_ms == 0 or pd.isna(speed_ms): return "0'00''/km"
    pace_min = 16.666666666667 / speed_ms
    minutes = int(pace_min)
    seconds = int((pace_min - minutes) * 60)
    return f"{minutes}'{seconds:02d}''/km"

def calculate_trimp(duration_min, avg_hr, max_hr=190, rest_hr=60):
    """Calcul approximatif du Training Impulse (Charge interne)"""
    if not avg_hr or pd.isna(avg_hr): return 0
    hr_reserve = max_hr - rest_hr
    hr_fraction = (avg_hr - rest_hr) / hr_reserve
    # Formule de Banister simplifiée pour homme
    return int(duration_min * hr_fraction * 0.64 * math.exp(1.92 * hr_fraction))

def analyze_goal_adherence(goal_type, df_recent, vol_total):
    """
    Le Cerveau du Coach : Compare la data réelle aux standards de l'objectif.
    Retourne une liste de conseils.
    """
    advice = []
    status = "green" # green, orange, red
    
    # KPIs récents
    nb_sorties = len(df_recent)
    avg_hr = df_recent['average_heartrate'].mean() if 'average_heartrate' in df_recent else 0
    long_run = df_recent['distance_km'].max() if not df_recent.empty else 0
    
    # 1. LOGIQUE MARATHON
    if goal_type == "Prépa Marathon":
        if vol_total < 80: # Moins de 20km/semaine en moy
            advice.append("⚠️ **Volume critique :** Pour un marathon, ton volume mensuel est trop faible. Vise au moins 30-40km/semaine pour finir.")
            status = "red"
        elif vol_total < 160:
            advice.append("ℹ️ **Volume :** Tu es sur une base correcte, mais n'hésite pas à augmenter progressivement.")
        
        if long_run < 15:
            advice.append("⚠️ **Sortie Longue :** Aucune sortie > 15km détectée ce mois-ci. La sortie longue est la clé du marathon !")
            status = "orange"
        else:
            advice.append("✅ **Sortie Longue :** Bravo, tu as validé une sortie de {:.1f}km.".format(long_run))

    # 2. LOGIQUE PERTE DE POIDS
    elif goal_type == "Perte de poids":
        if nb_sorties < 8: # Moins de 2x par semaine
            advice.append("💡 **Fréquence :** Pour la perte de poids, la régularité prime sur l'intensité. Essaie de courir 3x/semaine, même 30min.")
            status = "orange"
        if avg_hr > 155:
            advice.append("🔥 **Intensité :** Ton cardio moyen est haut. Pour brûler des graisses (lipolyse), ralentis pour rester en aisance respiratoire (Zone 2).")
        else:
            advice.append("✅ **Intensité :** Parfait, tu cours à une allure modérée idéale pour le métabolisme.")

    # 3. LOGIQUE PERFORMANCE (10km / Semi)
    elif "Prépa" in goal_type: # 10km ou Semi
        if nb_sorties > 12:
            advice.append("✅ **Volume :** Belle régularité !")
        else:
            advice.append("💡 **Volume :** Essaie d'ajouter une petite sortie 'footing' de 30min pour augmenter ta caisse.")

    # Conseil générique si vide
    if not advice:
        advice.append("📊 **Analyse :** Continue d'accumuler de la donnée pour que je puisse affiner mes conseils.")
    
    return advice, status

def generate_mock_data():
    data = []
    today = datetime.now()
    activities = ["Run", "Ride", "WeightTraining", "Hike"]
    
    for i in range(40):
        date_act = today - timedelta(days=random.randint(0, 60))
        act_type = random.choice(activities)
        
        # Logique spécifique par sport pour réalisme
        if act_type == "Run":
            dist = random.randint(5000, 22000)
            speed = random.uniform(2.5, 3.5) if dist > 15000 else random.uniform(3.0, 4.2)
        elif act_type == "Ride":
            dist = random.randint(20000, 80000)
            speed = random.uniform(5.5, 9.0) # Vitesse vélo plus élevée
        else:
            dist = 0
            speed = 0
            
        duration = random.randint(1800, 7200)
        hr = random.randint(110, 175)
        
        data.append({
            "name": f"{act_type} - Session #{40-i}",
            "distance": dist,
            "moving_time": duration,
            "total_elevation_gain": random.randint(50, 1200),
            "start_date_local": date_act.isoformat(),
            "average_heartrate": hr,
            "average_speed": speed,
            "type": act_type,
            "id": i # Fake ID
        })
    data.sort(key=lambda x: x['start_date_local'], reverse=True)
    return data

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
st.markdown("**Data Coach :** *L'intelligence artificielle au service de ta sueur.*")

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
            if st.button("🛠️ Mode Démo (Multi-sports)"):
                demo_data = strava_auth.get_demo_token()
                st.session_state.access_token = demo_data["access_token"]
                st.session_state.athlete = demo_data["athlete"]
                st.rerun()
        
        # Dépannage localhost
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
    
    # --- SIDEBAR : PROFIL & FILTRES ---
    with st.sidebar:
        st.header(f"👤 {athlete.get('firstname', 'Athlète')}")
        
        # Sélecteur d'objectif
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
        st.subheader("Filtres")
        # Le filtre sera rempli après chargement des données
        filter_container = st.container()
        
        if st.button("Déconnexion"):
            st.session_state.clear()
            st.rerun()

    # --- 1. CHARGEMENT DONNÉES ---
    if st.session_state.access_token == "demo_fake_token":
        activities = generate_mock_data()
    else:
        headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
        params = {"per_page": 100} # On prend plus d'historique
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
        df['week_start'] = df['start_date_local'].dt.to_period('W').apply(lambda r: r.start_time)
        
        # Calculs unitaires
        if 'distance' in df.columns: df['distance_km'] = df['distance'] / 1000
        else: df['distance_km'] = 0
        df['duration_h'] = df['moving_time'] / 3600
        df['pace_decimal'] = df['average_speed'].apply(lambda x: 16.666666666667 / x if x > 0 else None)
        
        # --- FILTRE TYPE D'ACTIVITÉ (SIDEBAR) ---
        all_types = list(df['type'].unique())
        with filter_container:
            # Par défaut "Run" si dispo, sinon "Tous"
            def_idx = all_types.index("Run") if "Run" in all_types else 0
            selected_activity_type = st.selectbox("Sport analysé", ["Tous"] + all_types, index=def_idx+1 if "Run" in all_types else 0)
        
        # Application du filtre
        if selected_activity_type != "Tous":
            df_filtered = df[df['type'] == selected_activity_type].copy()
        else:
            df_filtered = df.copy()

        # --- 2. ANALYSE MACRO (Derniers 30 jours) ---
        st.subheader(f"📊 Bilan {selected_activity_type} & Coaching")
        
        # Période
        now = datetime.now()
        df_30d = df_filtered[df_filtered['start_date_local'] > (now - timedelta(days=30))]
        
        # KPIs
        c1, c2, c3, c4 = st.columns(4)
        vol_30 = df_30d['distance_km'].sum()
        time_30 = df_30d['duration_h'].sum()
        count_30 = len(df_30d)
        trimp_30 = df_30d.apply(lambda row: calculate_trimp(row['moving_time']/60, row.get('average_heartrate', 0)), axis=1).sum()
        
        c1.metric("Volume (30j)", f"{int(vol_30)} km")
        c2.metric("Temps (30j)", f"{int(time_30)}h")
        c3.metric("Sorties", f"{count_30}")
        c4.metric("Charge (TRIMP)", f"{int(trimp_30)}")
        
        # --- 3. LE CERVEAU DU COACH (Analyse liée à l'objectif) ---
        if user_goal:
            current_goal = user_goal.get("type", "Plaisir")
            advice_list, status_color = analyze_goal_adherence(current_goal, df_30d, vol_30)
            
            with st.container(border=True):
                st.markdown(f"### 🧠 Analyse Coach : Objectif {current_goal}")
                for msg in advice_list:
                    st.write(msg)
        else:
            st.info("👈 Définis ton objectif dans la barre latérale pour avoir des conseils personnalisés.")

        # --- 4. ONGLETS DÉTAILLÉS ---
        tab1, tab2 = st.tabs(["📈 Progression & Volume", "🔎 Analyse d'une Séance"])
        
        with tab1:
            # Graphique Volume Hebdo
            weekly_vol = df_filtered.groupby('week_start')['distance_km'].sum().reset_index().sort_values('week_start')
            fig = px.bar(weekly_vol, x='week_start', y='distance_km', title="Volume Hebdomadaire", color='distance_km', color_continuous_scale='Blues')
            st.plotly_chart(fig, use_container_width=True)
            
            # Scatter Plot Intensité
            if 'average_heartrate' in df_filtered.columns and not df_filtered['average_heartrate'].isnull().all():
                fig2 = px.scatter(df_filtered, x='start_date_local', y='pace_decimal', 
                                  size='distance_km', color='average_heartrate',
                                  color_continuous_scale='RdYlGn_r', title="Intensité des séances (Taille=Dist, Coul=FC)")
                fig2.update_layout(yaxis_autorange="reversed", yaxis_title="Allure (min/km)")
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.info("Pas assez de données cardiaques pour le graphique d'intensité.")

        with tab2:
            st.markdown("### Deep Dive : Analyse d'une sortie spécifique")
            
            # Sélecteur d'activité avec affichage propre (Date - Nom - Dist)
            activity_options = df_filtered.sort_values('start_date_local', ascending=False).to_dict('records')
            
            # On crée une liste de labels pour le selectbox
            options_labels = [f"{act['start_date_local'].strftime('%d/%m')} - {act['name']} ({act['distance_km']:.1f}km)" for act in activity_options]
            
            selected_label = st.selectbox("Choisis une séance :", options_labels)
            
            # Retrouver l'activité sélectionnée
            selected_index = options_labels.index(selected_label)
            act_data = activity_options[selected_index]
            
            # Affichage Détails
            col_a, col_b, col_c = st.columns(3)
            
            # Calculs spécifiques
            pace = calculate_pace(act_data.get('average_speed'))
            hr = int(act_data.get('average_heartrate', 0)) if not pd.isna(act_data.get('average_heartrate')) else 0
            elev = int(act_data.get('total_elevation_gain', 0))
            
            # Calcul Efficiency Factor (Vitesse / FC)
            # Plus c'est haut, plus on est efficace (Vitesse élevée pour FC basse)
            efficiency = 0
            if hr > 0:
                speed_kmh = act_data.get('average_speed', 0) * 3.6
                efficiency = round(speed_kmh / hr, 2)
            
            # Calcul GAP approximatif (Grade Adjusted Pace)
            # Règle pouce : +100m D+ = +1km plat (très grossier mais utile pour MVP)
            gap_dist = act_data['distance_km'] + (elev / 1000)
            gap_speed = (gap_dist * 1000) / act_data['moving_time']
            gap_pace = calculate_pace(gap_speed)

            with col_a:
                st.metric("Distance & D+", f"{act_data['distance_km']:.2f} km", f"{elev}m d+")
                st.metric("Allure Moyenne", pace)
            
            with col_b:
                st.metric("Cardio Moyen", f"{hr} bpm" if hr > 0 else "--")
                st.metric("Allure Ajustée (GAP)", gap_pace, help="Allure théorique sur le plat compte tenu du dénivelé")

            with col_c:
                st.metric("Training Load", calculate_trimp(act_data['moving_time']/60, hr), help="Score de charge basé sur la durée et le cardio")
                st.metric("Efficacité Cardiaque", efficiency, help="Ratio Vitesse (km/h) / FC. À suivre sur les footings.")

            st.caption(f"ID Activité : {act_data.get('id')} | Type : {act_data.get('type')}")
            
            # Petit commentaire auto sur la séance
            if hr > 165:
                st.warning("🥵 **Séance intense :** Grosse sollicitation cardiaque. Pense à bien récupérer (hydratation + sommeil).")
            elif hr > 0 and hr < 140:
                st.success("😎 **Endurance :** Excellente séance pour le foncier. Faible coût physiologique.")

    else:
        st.info("Aucune activité trouvée pour ce filtre.")
