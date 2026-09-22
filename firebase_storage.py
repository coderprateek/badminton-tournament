"""Firebase Realtime Database storage for the tournament."""

import os
import json
from typing import Any, Optional
import firebase_admin
from firebase_admin import credentials, db

# Firebase configuration
FIREBASE_CONFIG = {
    "apiKey": "AIzaSyC6c4s-D-mUDaBgNRr3gCRHvHhqo0p8gZQ",
    "authDomain": "goals-badminton-league-2026.firebaseapp.com",
    "databaseURL": "https://goals-badminton-league-2026-default-rtdb.asia-southeast1.firebasedatabase.app",
    "projectId": "goals-badminton-league-2026",
    "storageBucket": "goals-badminton-league-2026.firebasestorage.app",
    "messagingSenderId": "974972320393",
    "appId": "1:974972320393:web:cc9b9338ead8b149892458"
}

CATEGORIES = {
    "MS": {"label": "Men's Singles", "players_per_side": 1, "genders": ["M"]},
    "WS": {"label": "Women's Singles", "players_per_side": 1, "genders": ["F"]},
    "MD": {"label": "Men's Doubles", "players_per_side": 2, "genders": ["M", "M"]},
    "WD": {"label": "Women's Doubles", "players_per_side": 2, "genders": ["F", "F"]},
    "XD": {"label": "Mixed Doubles", "players_per_side": 2, "genders": ["M", "F"]},
}

GENDER_LABELS = {"M": "Male", "F": "Female"}

# Initialize Firebase
def initialize_firebase():
    """Initialize Firebase Admin SDK."""
    try:
        if not firebase_admin._apps:
            # Try to use service account credentials
            service_account_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", 
                                              os.path.join(os.path.dirname(__file__), "firebase-service-account.json"))
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                firebase_admin.initialize_app(cred, options=FIREBASE_CONFIG)
                print("Firebase initialized with service account credentials")
            else:
                # Fallback to config only (requires test mode)
                firebase_admin.initialize_app(options=FIREBASE_CONFIG)
                print("Firebase initialized with config (test mode)")
        return True
    except Exception as e:
        print(f"Firebase initialization error: {e}")
        return False

# Initialize Firebase on module load
initialize_firebase()

def default_game_config() -> dict[str, int]:
    return {"MS": 1, "WS": 1, "MD": 1, "WD": 1, "XD": 1}

def _get_ref(path: str):
    """Get a Firebase database reference."""
    return db.reference(path)

def _get_ref(path: str):
    """Get a Firebase database reference."""
    return db.reference(path)

def snapshot() -> dict[str, list[dict[str, Any]]]:
    """Get a snapshot of all data from Firebase."""
    try:
        data = {
            "groups": _get_ref("groups").get() or [],
            "teams": _get_ref("teams").get() or [],
            "players": _get_ref("players").get() or [],
            "matches": _get_ref("matches").get() or [],
            "games": _get_ref("games").get() or [],
        }
        
        # Migrate existing groups to include game_config
        migrated = False
        for group in data["groups"]:
            if isinstance(group, dict) and "game_config" not in group:
                group["game_config"] = default_game_config()
                migrated = True
        if migrated:
            _write_list("groups", data["groups"])
        
        return data
    except Exception as e:
        print(f"Error getting snapshot: {e}")
        return {
            "groups": [],
            "teams": [],
            "players": [],
            "matches": [],
            "games": [],
        }

def admin_code() -> str:
    """Get the admin code from Firebase."""
    try:
        code = _get_ref("admin_code").get()
        return code if code else "SMASH-ADMIN"
    except Exception as e:
        print(f"Error getting admin code: {e}")
        return "SMASH-ADMIN"

def save_all(data: dict[str, list[dict[str, Any]]]) -> None:
    """Save all data to Firebase."""
    try:
        for key, rows in data.items():
            _write_list(key, rows)
    except Exception as e:
        print(f"Error saving data: {e}")

def _write_list(key: str, rows: list[dict[str, Any]]) -> None:
    """Write a list to Firebase."""
    try:
        _get_ref(key).set(rows)
    except Exception as e:
        print(f"Error writing {key}: {e}")

def find(rows: list[dict[str, Any]], item_id: str) -> Optional[dict[str, Any]]:
    """Find an item by ID in a list."""
    return next((row for row in rows if row["id"] == item_id), None)

def replace_row(rows: list[dict[str, Any]], item: dict[str, Any]) -> None:
    """Replace a row in a list or append if not found."""
    for index, row in enumerate(rows):
        if row["id"] == item["id"]:
            rows[index] = item
            return
    rows.append(item)

def player_label(player: dict[str, Any]) -> str:
    return f"{player['name']} ({GENDER_LABELS.get(player['gender'], player['gender'])})"

def set_winner(set_row: dict[str, Any]) -> Optional[str]:
    a, b = int(set_row["a"]), int(set_row["b"])
    if a == b:
        return None
    return "a" if a > b else "b"

def game_score(game: dict[str, Any]) -> tuple[int, int]:
    wins_a = wins_b = 0
    for set_row in game.get("sets", []):
        winner = set_winner(set_row)
        if winner == "a":
            wins_a += 1
        elif winner == "b":
            wins_b += 1
    return wins_a, wins_b

def game_winner(game: dict[str, Any]) -> Optional[str]:
    wins_a, wins_b = game_score(game)
    if wins_a == wins_b:
        return None
    return "a" if wins_a > wins_b else "b"

def match_game_tally(games: list[dict[str, Any]], match_id: str) -> tuple[int, int]:
    wins_a = wins_b = 0
    for game in games:
        if game["match_id"] != match_id:
            continue
        winner = game_winner(game)
        if winner == "a":
            wins_a += 1
        elif winner == "b":
            wins_b += 1
    return wins_a, wins_b

def match_winner(games: list[dict[str, Any]], match_id: str) -> Optional[str]:
    wins_a, wins_b = match_game_tally(games, match_id)
    if wins_a == wins_b:
        return None
    return "a" if wins_a > wins_b else "b"

def validate_lineup(category: str, players: list[dict[str, Any]]) -> Optional[str]:
    spec = CATEGORIES[category]
    if len(players) != spec["players_per_side"]:
        return f"{CATEGORIES[category]['label']} needs {spec['players_per_side']} player(s) per side."
    
    # Check for duplicate players
    player_ids = [p["id"] for p in players if p]
    if len(player_ids) != len(set(player_ids)):
        return "Cannot select the same player multiple times in one game."
    
    genders = sorted(p["gender"] for p in players if p)
    expected = sorted(spec["genders"])
    if genders != expected:
        if category == "XD":
            return "Mixed Doubles needs one male and one female on each side."
        needed = "male" if spec["genders"][0] == "M" else "female"
        return f"{spec['label']} needs {spec['players_per_side']} {needed} player(s) per side."
    return None

def group_standings(
    group_id: str,
    teams: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    games: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    group_teams = {t["id"]: t for t in teams if t.get("group_id") == group_id}
    table = {
        team["id"]: {
            "team": team,
            "played": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "points": 0,
            "games_for": 0,
            "games_against": 0,
            "sets_for": 0,
            "sets_against": 0,
        }
        for team in group_teams.values()
    }
    for match in matches:
        if match["group_id"] != group_id:
            continue
        if match["team_a_id"] not in table or match["team_b_id"] not in table:
            continue
        games_a, games_b = match_game_tally(games, match["id"])
        if games_a == 0 and games_b == 0:
            continue
        table[match["team_a_id"]]["played"] += 1
        table[match["team_b_id"]]["played"] += 1
        table[match["team_a_id"]]["games_for"] += games_a
        table[match["team_a_id"]]["games_against"] += games_b
        table[match["team_b_id"]]["games_for"] += games_b
        table[match["team_b_id"]]["games_against"] += games_a
        
        # Calculate set points
        sets_a, sets_b = 0, 0
        for game in games:
            if game["match_id"] != match["id"]:
                continue
            for set_row in game.get("sets", []):
                sets_a += int(set_row["a"])
                sets_b += int(set_row["b"])
        table[match["team_a_id"]]["sets_for"] += sets_a
        table[match["team_a_id"]]["sets_against"] += sets_b
        table[match["team_b_id"]]["sets_for"] += sets_b
        table[match["team_b_id"]]["sets_against"] += sets_a
        
        winner = match_winner(games, match["id"])
        if winner == "a":
            table[match["team_a_id"]]["wins"] += 1
            table[match["team_a_id"]]["points"] += 2
            table[match["team_b_id"]]["losses"] += 1
        elif winner == "b":
            table[match["team_b_id"]]["wins"] += 1
            table[match["team_b_id"]]["points"] += 2
            table[match["team_a_id"]]["losses"] += 1
        else:
            table[match["team_a_id"]]["draws"] += 1
            table[match["team_a_id"]]["points"] += 1
            table[match["team_b_id"]]["draws"] += 1
            table[match["team_b_id"]]["points"] += 1
    rows = list(table.values())
    rows.sort(
        key=lambda row: (
            -row["points"],  # Primary: points
            -(row["games_for"] - row["games_against"]),  # Secondary: game differential
            -(row["sets_for"] - row["sets_against"]),  # Tertiary: set differential
            row["team"]["name"].lower(),  # Final: alphabetical
        )
    )
    return rows

def generate_games_for_match(match_id: str, game_config: dict[str, int]) -> list[dict[str, Any]]:
    """Generate games for a match based on group configuration."""
    import uuid
    games = []
    order = 1
    for category, count in game_config.items():
        for _ in range(count):
            games.append({
                "id": f"gm_{uuid.uuid4().hex[:8]}",
                "match_id": match_id,
                "category": category,
                "order": order,
                "team_a_player_ids": [],
                "team_b_player_ids": [],
                "sets": [],
            })
            order += 1
    return games


def new_id(prefix: str) -> str:
    """Generate a new unique ID."""
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"

def get_top_teams(group_id: str, teams: list[dict[str, Any]], matches: list[dict[str, Any]], games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Get top 2 teams from a group based on standings."""
    standings = group_standings(group_id, teams, matches, games)
    return [row["team"] for row in standings[:2]]

def player_standings(group_id: str, teams: list[dict[str, Any]], matches: list[dict[str, Any]], games: list[dict[str, Any]], players: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Calculate player standings by gender for a group."""
    group_teams = {t["id"]: t for t in teams if t.get("group_id") == group_id}
    group_players = {p["id"]: p for p in players if p["team_id"] in group_teams}
    
    # Initialize player stats
    male_stats = {pid: {"player": p, "team": group_teams[p["team_id"]], "played": 0, "wins": 0, "losses": 0, "sets_for": 0, "sets_against": 0} for pid, p in group_players.items() if p["gender"] == "M"}
    female_stats = {pid: {"player": p, "team": group_teams[p["team_id"]], "played": 0, "wins": 0, "losses": 0, "sets_for": 0, "sets_against": 0} for pid, p in group_players.items() if p["gender"] == "F"}
    
    # Process games to calculate player stats
    for game in games:
        match = next((m for m in matches if m["id"] == game["match_id"]), None)
        if not match or match["group_id"] != group_id:
            continue
        
        # Skip games without completed sets
        if not game.get("sets"):
            continue
        
        game_winner_res = game_winner(game)
        
        # Process team A players
        for player_id in game.get("team_a_player_ids", []):
            if player_id in male_stats:
                stats = male_stats[player_id]
                stats["played"] += 1
                for set_row in game["sets"]:
                    stats["sets_for"] += int(set_row["a"])
                    stats["sets_against"] += int(set_row["b"])
                if game_winner_res == "a":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
            elif player_id in female_stats:
                stats = female_stats[player_id]
                stats["played"] += 1
                for set_row in game["sets"]:
                    stats["sets_for"] += int(set_row["a"])
                    stats["sets_against"] += int(set_row["b"])
                if game_winner_res == "a":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
        
        # Process team B players
        for player_id in game.get("team_b_player_ids", []):
            if player_id in male_stats:
                stats = male_stats[player_id]
                stats["played"] += 1
                for set_row in game["sets"]:
                    stats["sets_for"] += int(set_row["b"])
                    stats["sets_against"] += int(set_row["a"])
                if game_winner_res == "b":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
            elif player_id in female_stats:
                stats = female_stats[player_id]
                stats["played"] += 1
                for set_row in game["sets"]:
                    stats["sets_for"] += int(set_row["b"])
                    stats["sets_against"] += int(set_row["a"])
                if game_winner_res == "b":
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1
    
    # Sort by wins, then set differential
    def sort_stats(stats_dict):
        return sorted(stats_dict.values(), key=lambda x: (-x["wins"], -(x["sets_for"] - x["sets_against"]), x["player"]["name"].lower()))
    
    return {
        "male": sort_stats(male_stats)[:15],  # Limit to top 15
        "female": sort_stats(female_stats)[:15]  # Limit to top 15
    }