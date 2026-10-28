import streamlit as st
import pandas as pd
from datetime import datetime
import time

from nba_api.stats.endpoints import playergamelog, leaguedashteamstats
from nba_api.stats.static import teams

# Configuration de la page
st.set_page_config(
    page_title="NBA PropBet Analyzer",
    page_icon="🏀",
    layout="wide"
)

st.title("🏀 NBA PropBet Analyzer — Assistant IA & Data")
st.markdown("Analyse ciblée des joueurs par équipe avec mémoire de session.")

# ---------------------------------------------------------
# FONCTIONS DE CACHE & API
# ---------------------------------------------------------

@st.cache_data(ttl=86400)
def get_nba_teams():
    nba_teams = teams.get_teams()
    return pd.DataFrame(nba_teams).sort_values('full_name')

@st.cache_data(ttl=3600)
def get_team_defensive_ratings():
    try:
        stats = leaguedashteamstats.LeagueDashTeamStats(measure_type_detailed_defense='Advanced')
        df = stats.get_data_frames()[0]
        df = df[['TEAM_NAME', 'TEAM_ID', 'DEF_RATING']].sort_values(by='DEF_RATING', ascending=True)
        df['DEF_RANK'] = range(1, len(df) + 1)
        return df
    except Exception as e:
        return pd.DataFrame(columns=['TEAM_NAME', 'TEAM_ID', 'DEF_RATING', 'DEF_RANK'])

@st.cache_data(ttl=3600)
def get_team_roster_and_stats(team_id, season="2026-27"):
    from nba_api.stats.endpoints import leaguedashplayerstats
    try:
        stats = leaguedashplayerstats.LeagueDashPlayerStats(season=season, team_id_nullable=team_id)
        df = stats.get_data_frames()[0]
        return df
    except Exception as e:
        return pd.DataFrame()

@st.cache_data(ttl=1800)
def get_player_logs(player_id, season="2026-27"):
    try:
        gamelog = playergamelog.PlayerGameLog(player_id=player_id, season=season)
        df = gamelog.get_data_frames()[0]
        return df
    except Exception as e:
        return pd.DataFrame()

def calculate_probability(df_last_n, target_pts, def_rank=15):
    if len(df_last_n) == 0:
        return 0.0
    
    avg_pts = df_last_n['PTS'].mean()
    min_pts = df_last_n['PTS'].min()
    avg_min = df_last_n['MIN'].mean()
    
    base_score = (avg_pts / target_pts) * 50  
    consistency_bonus = 20 if min_pts >= target_pts else 0
    minutes_factor = 15 if avg_min >= 30 else (avg_min / 30) * 15
    defense_factor = ((def_rank - 15) / 15) * 12  
    
    prob = base_score + consistency_bonus + minutes_factor + defense_factor
    return round(min(max(prob, 5.0), 95.0), 1)

# ---------------------------------------------------------
# INITIALISATION DE LA MÉMOIRE DE SESSION (SESSION STATE)
# ---------------------------------------------------------
if "results" not in st.session_state:
    st.session_state.results = None
if "team_list_all" not in st.session_state:
    st.session_state.team_list_all = []
if "def_ratings" not in st.session_state:
    st.session_state.def_ratings = pd.DataFrame()

# ---------------------------------------------------------
# INTERFACE UTILISATEUR (BARRE LATÉRALE)
# ---------------------------------------------------------

st.sidebar.header("⚙️ Paramètres du Filtre")

teams_df = get_nba_teams()
team_names = teams_df['full_name'].tolist()

selected_team_name = st.sidebar.selectbox("🏀 Choisir une Équipe", team_names)
selected_team_row = teams_df[teams_df['full_name'] == selected_team_name].iloc[0]
selected_team_id = selected_team_row['id']
selected_team_abbrev = selected_team_row['abbreviation']

consecutive_games = st.sidebar.slider("Nombre de matchs consécutifs", min_value=3, max_value=10, value=3)
pts_threshold = st.sidebar.number_input("Seuil de Points (Cut)", min_value=10.0, max_value=40.0, value=20.0, step=0.5)
season_selected = st.sidebar.selectbox("Saison NBA", ["2026-27", "2025-26"])

btn_analyze = st.sidebar.button("🚀 Analyser l'Équipe", type="primary")

# ---------------------------------------------------------
#  OÙ  LA MAGIE OPÈRE : LANCEMENT DE L'ANALYSE
# ---------------------------------------------------------

if btn_analyze:
    with st.spinner(f"Chargement de l'effectif des **{selected_team_name}**..."):
        def_ratings = get_team_defensive_ratings()
        team_list_all = def_ratings['TEAM_NAME'].tolist() if not def_ratings.empty else ["Équipe Adverse"]
        
        # Sauvegarde dans la session
        st.session_state.def_ratings = def_ratings
        st.session_state.team_list_all = team_list_all
        
        roster_df = get_team_roster_and_stats(selected_team_id, season=season_selected)
        results = []
        
        if not roster_df.empty and 'PLAYER_ID' in roster_df.columns:
            roster_df = roster_df.sort_values(by='PTS', ascending=False)
            
            for _, player_row in roster_df.iterrows():
                p_id = player_row['PLAYER_ID']
                p_name = player_row['PLAYER_NAME']
                
                logs = get_player_logs(p_id, season=season_selected)
                
                if len(logs) >= consecutive_games:
                    last_n = logs.head(consecutive_games)
                    all_above_threshold = (last_n['PTS'] >= pts_threshold).all()
                    
                    if all_above_threshold:
                        avg_pts = round(last_n['PTS'].mean(), 1)
                        avg_reb = round(last_n['REB'].mean(), 1)
                        avg_ast = round(last_n['AST'].mean(), 1)
                        avg_min = round(last_n['MIN'].mean(), 1)
                        
                        fg3m_tot = last_n['FG3M'].sum()
                        fg3a_tot = last_n['FG3A'].sum()
                        fg3_ratio = f"{fg3m_tot}/{fg3a_tot} ({(fg3m_tot/fg3a_tot*100) if fg3a_tot > 0 else 0:.1f}%)"

                        match_details = []
                        for _, game in last_n.iterrows():
                            match_details.append({
                                "Date": game['GAME_DATE'],
                                "Matchup": game['MATCHUP'],
                                "MIN": game['MIN'],
                                "PTS": game['PTS'],
                                "REB": game['REB'],
                                "AST": game['AST'],
                                "3PM/3PA": f"{game['FG3M']}/{game['FG3A']}"
                            })
                        
                        results.append({
                            "Joueur": p_name,
                            "Équipe": selected_team_abbrev,
                            "Pts Moy.": avg_pts,
                            "Reb Moy.": avg_reb,
                            "Passes Moy.": avg_ast,
                            "Min Moy.": avg_min,
                            "3PT (Cumul)": fg3_ratio,
                            "Détails Matchs": match_details
                        })
        
        # On stocke les résultats en mémoire de session
        st.session_state.results = results
        st.session_state.searched_team = selected_team_name

# ---------------------------------------------------------
# AFFICHAGE DES RÉSULTATS (Depuis la mémoire de session)
# ---------------------------------------------------------

if st.session_state.results is not None:
    st.subheader(f"📊 Résultats pour les {st.session_state.get('searched_team', selected_team_name)}")
    results = st.session_state.results
    team_list_all = st.session_state.team_list_all
    def_ratings = st.session_state.def_ratings
    
    if results:
        st.success(f"✅ {len(results)} joueur(s) trouvé(s) avec plus de {pts_threshold} pts sur leurs {consecutive_games} derniers matchs.")
        
        df_base = pd.DataFrame(results)[["Joueur", "Équipe", "Pts Moy.", "Reb Moy.", "Passes Moy.", "Min Moy.", "3PT (Cumul)"]]
        st.dataframe(df_base, use_container_width=True)
        
        st.markdown("---")
        st.subheader("🎯 Simulateur de Pari & Prochain Adversaire")
        
        for p in results:
            with st.expander(f"👤 **{p['Joueur']}** ({p['Équipe']}) — Moyenne : **{p['Pts Moy.']} Pts**"):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.write("**Historique des derniers matchs :**")
                    st.table(pd.DataFrame(p["Détails Matchs"]))
                
                with col2:
                    st.write("**Simulation du Prochain Match :**")
                    
                    next_opp = st.selectbox(
                        f"Prochain adversaire de {p['Joueur']}",
                        options=team_list_all,
                        key=f"opp_{p['Joueur']}"
                    )
                    
                    def_rank = 15 
                    if not def_ratings.empty:
                        match_row = def_ratings[def_ratings['TEAM_NAME'] == next_opp]
                        if not match_row.empty:
                            def_rank = int(match_row.iloc[0]['DEF_RANK'])
                    
                    last_n_sim = pd.DataFrame(p["Détails Matchs"])
                    prob_dyn = calculate_probability(last_n_sim, pts_threshold, def_rank)
                    
                    st.metric(label="Rang Défensif Adverse", value=f"{def_rank} / 30", help="1 = Meilleure défense, 30 = Pire défense")
                    st.metric(label=f"Probabilité estimée (> {pts_threshold} Pts)", value=f"{prob_dyn}%")
                    
                    if prob_dyn >= 75:
                        st.success("🔥 **Excellent spot de pari !**")
                    elif prob_dyn >= 50:
                        st.warning("⚠️ **Matchup neutre / équilibré.**")
                    else:
                        st.error("❌ **Risqué !**")
        
        csv = pd.DataFrame(results).to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Télécharger le Rapport en CSV",
            data=csv,
            file_name=f"nba_props_{selected_team_abbrev}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
        
    else:
        st.info(f"Aucun joueur ne remplit la condition de >{pts_threshold} points sur les {consecutive_games} derniers matchs.")

else:
    st.info("👈 Sélectionnez une équipe dans la barre latérale et cliquez sur **Analyser l'Équipe**.")