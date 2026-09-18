"""Crash-safe JSON-in-.txt persistence for the tournament."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

def data_dir() -> Path:
    return Path(os.environ.get("TOURNAMENT_DATA_DIR", Path(__file__).resolve().parent / "data"))


LOCK = threading.RLock()


def _files() -> dict[str, Path]:
    root = data_dir()
    return {
        "groups": root / "groups.txt",
        "teams": root / "teams.txt",
        "players": root / "players.txt",
        "matches": root / "matches.txt",
        "games": root / "games.txt",
        "admin": root / "admin_code.txt",
    }

CATEGORIES = {
    "MS": {"label": "Men's Singles", "players_per_side": 1, "genders": ["M"]},
    "WS": {"label": "Women's Singles", "players_per_side": 1, "genders": ["F"]},
    "MD": {"label": "Men's Doubles", "players_per_side": 2, "genders": ["M", "M"]},
    "WD": {"label": "Women's Doubles", "players_per_side": 2, "genders": ["F", "F"]},
    "XD": {"label": "Mixed Doubles", "players_per_side": 2, "genders": ["M", "F"]},
}

GENDER_LABELS = {"M": "Male", "F": "Female"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _ensure_files() -> None:
    files = _files()
    files["groups"].parent.mkdir(parents=True, exist_ok=True)
    for key, path in files.items():
        if path.exists():
            continue
        if key == "admin":
            path.write_text("SMASH-ADMIN\n", encoding="utf-8")
        else:
            path.write_text("[]\n", encoding="utf-8")


def _read_list(key: str) -> list[dict[str, Any]]:
    _ensure_files()
    raw = _files()[key].read_text(encoding="utf-8").strip() or "[]"
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{_files()[key].name} must contain a JSON list")
    return data


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def _write_list(key: str, rows: list[dict[str, Any]]) -> None:
    _atomic_write(_files()[key], json.dumps(rows, indent=2, ensure_ascii=True) + "\n")


LIST_KEYS = ("groups", "teams", "players", "matches", "games")

def default_game_config() -> dict[str, int]:
    return {"MS": 1, "WS": 1, "MD": 1, "WD": 1, "XD": 1}


def snapshot() -> dict[str, list[dict[str, Any]]]:
    with LOCK:
        data = {key: _read_list(key) for key in LIST_KEYS}
        # Migrate existing groups to include game_config
        migrated = False
        for group in data["groups"]:
            if "game_config" not in group:
                group["game_config"] = default_game_config()
                migrated = True
        if migrated:
            _write_list("groups", data["groups"])
        return data


def admin_code() -> str:
    _ensure_files()
    return _files()["admin"].read_text(encoding="utf-8").strip()


def save_all(data: dict[str, list[dict[str, Any]]]) -> None:
    with LOCK:
        for key, rows in data.items():
            _write_list(key, rows)


def find(rows: list[dict[str, Any]], item_id: str) -> dict[str, Any] | None:
    return next((row for row in rows if row["id"] == item_id), None)


def replace_row(rows: list[dict[str, Any]], item: dict[str, Any]) -> None:
    for index, row in enumerate(rows):
        if row["id"] == item["id"]:
            rows[index] = item
            return
    rows.append(item)


def player_label(player: dict[str, Any]) -> str:
    return f"{player['name']} ({GENDER_LABELS.get(player['gender'], player['gender'])})"


def set_winner(set_row: dict[str, Any]) -> str | None:
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


def game_winner(game: dict[str, Any]) -> str | None:
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


def match_winner(games: list[dict[str, Any]], match_id: str) -> str | None:
    wins_a, wins_b = match_game_tally(games, match_id)
    if wins_a == wins_b:
        return None
    return "a" if wins_a > wins_b else "b"


def validate_lineup(category: str, players: list[dict[str, Any]]) -> str | None:
    spec = CATEGORIES[category]
    if len(players) != spec["players_per_side"]:
        return f"{CATEGORIES[category]['label']} needs {spec['players_per_side']} player(s) per side."
    
    # Check for duplicate players
    player_ids = [p["id"] for p in players if p]  # Filter out None values
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
    group_teams = [team for team in teams if team.get("group_id") == group_id]
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
        for team in group_teams
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
    games = []
    order = 1
    for category, count in game_config.items():
        for _ in range(count):
            games.append({
                "id": new_id("gm"),
                "match_id": match_id,
                "category": category,
                "order": order,
                "team_a_player_ids": [],
                "team_b_player_ids": [],
                "sets": [],
            })
            order += 1
    return games


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
