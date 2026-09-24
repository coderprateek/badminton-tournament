from __future__ import annotations

from functools import wraps
import os

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

# Choose storage backend based on environment
USE_FIREBASE = os.environ.get("USE_FIREBASE", "false").lower() == "true"

if USE_FIREBASE:
    import firebase_storage as storage
else:
    import storage

app = Flask(__name__)
app.secret_key = "badminton-tournament-dev-key"

CATEGORIES = storage.CATEGORIES


def is_admin() -> bool:
    return bool(session.get("is_admin"))


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not is_admin():
            flash("Admin login is required to edit tournament data.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals():
    return {
        "is_admin": is_admin(),
        "categories": CATEGORIES,
        "gender_labels": storage.GENDER_LABELS,
    }


@app.get("/")
def home():
    data = storage.snapshot()
    groups = sorted(data["groups"], key=lambda g: g["name"].lower())
    cards = []
    for group in groups:
        teams = [t for t in data["teams"] if t.get("group_id") == group["id"]]
        matches = sorted([m for m in data["matches"] if m["group_id"] == group["id"]], key=lambda m: m.get("order", 0))
        cards.append(
            {
                "group": group,
                "teams": sorted(teams, key=lambda t: t["name"].lower()),
                "match_count": len(matches),
                "standings": storage.group_standings(group["id"], data["teams"], data["matches"], data["games"]),
            }
        )
    unassigned = sorted(
        [t for t in data["teams"] if not t.get("group_id")],
        key=lambda t: t["name"].lower(),
    )
    return render_template("home.html", cards=cards, unassigned=unassigned)


@app.get("/login")
def login():
    if is_admin():
        return redirect(url_for("home"))
    return render_template("login.html")


@app.post("/login")
def login_post():
    code = (request.form.get("code") or "").strip()
    if code and code == storage.admin_code():
        session["is_admin"] = True
        flash("Welcome, admin. You can now add groups, teams, players, and scores.", "ok")
        return redirect(request.args.get("next") or url_for("home"))
    flash("That admin code is not valid.", "error")
    return render_template("login.html"), 401


@app.post("/logout")
def logout():
    session.clear()
    flash("Signed out. The site is view-only again.", "ok")
    return redirect(url_for("home"))


@app.post("/groups")
@admin_required
def add_group():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Group name is required.", "error")
        return redirect(url_for("home"))
    data = storage.snapshot()
    data["groups"].append({
        "id": storage.new_id("grp"), 
        "name": name,
        "game_config": storage.default_game_config()
    })
    storage.save_all(data)
    flash(f"Group “{name}” added.", "ok")
    return redirect(url_for("home"))


@app.get("/groups/<group_id>")
def group_detail(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    teams = sorted(
        [t for t in data["teams"] if t.get("group_id") == group_id],
        key=lambda t: t["name"].lower(),
    )
    players_by_team = {
        team["id"]: sorted(
            [p for p in data["players"] if p["team_id"] == team["id"]],
            key=lambda p: p["name"].lower(),
        )
        for team in teams
    }
    matches = [m for m in data["matches"] if m["group_id"] == group_id]
    match_views = [_match_view(m, data) for m in matches]
    # Separate regular matches and final match
    regular_matches = sorted([m for m in match_views if not m.get("is_final")], key=lambda m: m.get("order", 0))
    final_match = next((m for m in match_views if m.get("is_final")), None)
    unassigned = sorted(
        [t for t in data["teams"] if not t.get("group_id")],
        key=lambda t: t["name"].lower(),
    )
    return render_template(
        "group.html",
        group=group,
        teams=teams,
        players_by_team=players_by_team,
        matches=match_views,
        regular_matches=regular_matches,
        final_match=final_match,
        standings=storage.group_standings(group_id, data["teams"], data["matches"], data["games"]),
        player_standings=storage.player_standings(group_id, data["teams"], data["matches"], data["games"], data["players"]),
        unassigned=unassigned,
    )


@app.post("/groups/<group_id>/config")
@admin_required
def update_group_config(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    
    game_config = {}
    for category in storage.CATEGORIES.keys():
        count = request.form.get(f"games_{category}", "0")
        try:
            game_config[category] = max(0, int(count))
        except ValueError:
            game_config[category] = 0
    
    group["game_config"] = game_config
    storage.replace_row(data["groups"], group)
    storage.save_all(data)
    flash("Group game configuration updated.", "ok")
    return redirect(url_for("group_detail", group_id=group_id))


@app.post("/groups/<group_id>/teams")
@admin_required
def add_team_to_group(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    existing_id = (request.form.get("existing_team_id") or "").strip()
    name = (request.form.get("name") or "").strip()
    if existing_id:
        team = storage.find(data["teams"], existing_id)
        if not team:
            flash("That team was not found.", "error")
            return redirect(url_for("group_detail", group_id=group_id))
        team["group_id"] = group_id
        storage.replace_row(data["teams"], team)
        storage.save_all(data)
        flash(f"{team['name']} moved into {group['name']}.", "ok")
        return redirect(url_for("group_detail", group_id=group_id))
    if not name:
        flash("Enter a team name, or pick an existing unassigned team.", "error")
        return redirect(url_for("group_detail", group_id=group_id))
    data["teams"].append({"id": storage.new_id("team"), "name": name, "group_id": group_id})
    storage.save_all(data)
    flash(f"Team “{name}” added to {group['name']}.", "ok")
    return redirect(url_for("group_detail", group_id=group_id))


@app.post("/teams")
@admin_required
def add_team():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Team name is required.", "error")
        return redirect(url_for("home"))
    data = storage.snapshot()
    data["teams"].append({"id": storage.new_id("team"), "name": name, "group_id": None})
    storage.save_all(data)
    flash(f"Team “{name}” created. Assign it to a group when ready.", "ok")
    return redirect(url_for("home"))


@app.post("/teams/<team_id>/players")
@admin_required
def add_player(team_id: str):
    data = storage.snapshot()
    team = storage.find(data["teams"], team_id)
    if not team:
        abort(404)
    name = (request.form.get("name") or "").strip()
    gender = (request.form.get("gender") or "").strip()
    if not name or gender not in storage.GENDER_LABELS:
        flash("Player name and gender are required.", "error")
        return redirect(_team_return(team))
    data["players"].append(
        {"id": storage.new_id("pl"), "team_id": team_id, "name": name, "gender": gender}
    )
    storage.save_all(data)
    flash(f"{name} added to {team['name']}.", "ok")
    return redirect(_team_return(team))


@app.post("/teams/<team_id>/players/bulk")
@admin_required
def add_players_bulk(team_id: str):
    data = storage.snapshot()
    team = storage.find(data["teams"], team_id)
    if not team:
        abort(404)
    
    names = request.form.getlist("player_names")
    genders = request.form.getlist("player_genders")
    
    added_count = 0
    for name, gender in zip(names, genders):
        name = name.strip()
        gender = gender.strip()
        if name and gender in storage.GENDER_LABELS:
            data["players"].append(
                {"id": storage.new_id("pl"), "team_id": team_id, "name": name, "gender": gender}
            )
            added_count += 1
    
    storage.save_all(data)
    flash(f"{added_count} player(s) added to {team['name']}.", "ok")
    return redirect(_team_return(team))


@app.post("/players/<player_id>/delete")
@admin_required
def delete_player(player_id: str):
    data = storage.snapshot()
    player = storage.find(data["players"], player_id)
    if not player:
        abort(404)
    
    team = storage.find(data["teams"], player["team_id"])
    if not team:
        abort(404)
    
    # Remove player from all games
    for game in data["games"]:
        if player_id in game.get("team_a_player_ids", []):
            game["team_a_player_ids"].remove(player_id)
        if player_id in game.get("team_b_player_ids", []):
            game["team_b_player_ids"].remove(player_id)
    
    # Remove player from data
    data["players"] = [p for p in data["players"] if p["id"] != player_id]
    
    storage.save_all(data)
    flash(f"{player['name']} deleted from {team['name']}.", "ok")
    return redirect(_team_return(team))


@app.post("/groups/<group_id>/round-robin")
@admin_required
def generate_round_robin(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    teams = [t for t in data["teams"] if t.get("group_id") == group_id]
    if len(teams) < 2:
        flash("Need at least two teams in this group to build a round-robin.", "error")
        return redirect(url_for("group_detail", group_id=group_id))
    existing = {
        tuple(sorted((m["team_a_id"], m["team_b_id"])))
        for m in data["matches"]
        if m["group_id"] == group_id and not m.get("is_final")
    }
    created = 0
    # Get current max order for regular matches
    max_order = max([m.get("order", 0) for m in data["matches"] if m["group_id"] == group_id and not m.get("is_final")], default=0)
    
    for i, team_a in enumerate(teams):
        for team_b in teams[i + 1 :]:
            pair = tuple(sorted((team_a["id"], team_b["id"])))
            if pair in existing:
                continue
            max_order += 1
            match_id = storage.new_id("mt")
            data["matches"].append(
                {
                    "id": match_id,
                    "group_id": group_id,
                    "team_a_id": team_a["id"],
                    "team_b_id": team_b["id"],
                    "status": "scheduled",
                    "is_final": False,
                    "order": max_order,
                }
            )
            # Auto-generate games based on group configuration
            games = storage.generate_games_for_match(match_id, group.get("game_config", storage.default_game_config()))
            data["games"].extend(games)
            created += 1
    storage.save_all(data)
    if created:
        flash(f"Created {created} round-robin match(es) with auto-generated games in {group['name']}.", "ok")
    else:
        flash("Every pair in this group already has a match.", "ok")
    return redirect(url_for("group_detail", group_id=group_id))


@app.post("/groups/<group_id>/final")
@admin_required
def generate_final(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    
    # Check if final already exists
    existing_final = [m for m in data["matches"] if m["group_id"] == group_id and m.get("is_final")]
    if existing_final:
        flash("A final match already exists for this group.", "error")
        return redirect(url_for("group_detail", group_id=group_id))
    
    # Get top 2 teams
    top_teams = storage.get_top_teams(group_id, data["teams"], data["matches"], data["games"])
    if len(top_teams) < 2:
        flash("Need at least two teams with completed matches to generate a final.", "error")
        return redirect(url_for("group_detail", group_id=group_id))
    
    # Create final match
    match_id = storage.new_id("mt")
    data["matches"].append(
        {
            "id": match_id,
            "group_id": group_id,
            "team_a_id": top_teams[0]["id"],
            "team_b_id": top_teams[1]["id"],
            "status": "scheduled",
            "is_final": True,
            "order": 999,  # Final always last
        }
    )
    
    # Auto-generate games based on group configuration
    games = storage.generate_games_for_match(match_id, group.get("game_config", storage.default_game_config()))
    data["games"].extend(games)
    
    storage.save_all(data)
    flash(f"Final match created between {top_teams[0]['name']} and {top_teams[1]['name']}.", "ok")
    return redirect(url_for("group_detail", group_id=group_id))


@app.post("/groups/<group_id>/matches/reorder")
@admin_required
def reorder_matches(group_id: str):
    data = storage.snapshot()
    group = storage.find(data["groups"], group_id)
    if not group:
        abort(404)
    
    # Get match order from form
    match_orders = {}
    for key in request.form.keys():
        if key.startswith("match_order_"):
            match_id = key.replace("match_order_", "")
            try:
                order = int(request.form[key])
                match_orders[match_id] = order
            except ValueError:
                continue
    
    # Update match orders
    for match in data["matches"]:
        if match["group_id"] == group_id and match["id"] in match_orders:
            match["order"] = match_orders[match["id"]]
    
    storage.save_all(data)
    flash("Match order updated.", "ok")
    return redirect(url_for("group_detail", group_id=group_id))


@app.get("/matches/<match_id>")
def match_detail(match_id: str):
    data = storage.snapshot()
    match = storage.find(data["matches"], match_id)
    if not match:
        abort(404)
    view = _match_view(match, data)
    return render_template("match.html", match=view, categories=CATEGORIES)


@app.post("/matches/<match_id>/games")
@admin_required
def add_game(match_id: str):
    data = storage.snapshot()
    match = storage.find(data["matches"], match_id)
    if not match:
        abort(404)
    category = (request.form.get("category") or "").strip()
    if category not in CATEGORIES:
        flash("Choose a game category.", "error")
        return redirect(url_for("match_detail", match_id=match_id))
    existing = [g for g in data["games"] if g["match_id"] == match_id]
    data["games"].append(
        {
            "id": storage.new_id("gm"),
            "match_id": match_id,
            "category": category,
            "order": len(existing) + 1,
            "team_a_player_ids": [],
            "team_b_player_ids": [],
            "sets": [],
        }
    )
    if match["status"] == "scheduled":
        match["status"] = "in_progress"
        storage.replace_row(data["matches"], match)
    storage.save_all(data)
    flash(f"{CATEGORIES[category]['label']} added to this match.", "ok")
    return redirect(url_for("match_detail", match_id=match_id))


@app.post("/games/<game_id>/lineup")
@admin_required
def set_lineup(game_id: str):
    data = storage.snapshot()
    game = storage.find(data["games"], game_id)
    if not game:
        abort(404)
    match = storage.find(data["matches"], game["match_id"])
    if not match:
        abort(404)
    side_a = request.form.getlist("team_a_player_ids")
    side_b = request.form.getlist("team_b_player_ids")
    # Filter out empty values from dropdowns
    side_a = [pid for pid in side_a if pid and pid.strip()]
    side_b = [pid for pid in side_b if pid and pid.strip()]
    players_a = [storage.find(data["players"], pid) for pid in side_a]
    players_b = [storage.find(data["players"], pid) for pid in side_b]
    if any(p is None for p in players_a + players_b):
        flash("One of the selected players was not found.", "error")
        return redirect(url_for("match_detail", match_id=match["id"]))
    for player in players_a:
        if player["team_id"] != match["team_a_id"]:
            flash("Players on the left must belong to that team.", "error")
            return redirect(url_for("match_detail", match_id=match["id"]))
    for player in players_b:
        if player["team_id"] != match["team_b_id"]:
            flash("Players on the right must belong to that team.", "error")
            return redirect(url_for("match_detail", match_id=match["id"]))
    # Filter out None values before validation
    players_a_filtered = [p for p in players_a if p is not None]
    players_b_filtered = [p for p in players_b if p is not None]
    err_a = storage.validate_lineup(game["category"], players_a_filtered)
    err_b = storage.validate_lineup(game["category"], players_b_filtered)
    if err_a or err_b:
        flash(err_a or err_b, "error")
        return redirect(url_for("match_detail", match_id=match["id"]))
    game["team_a_player_ids"] = side_a
    game["team_b_player_ids"] = side_b
    storage.replace_row(data["games"], game)
    storage.save_all(data)
    flash("Lineup saved.", "ok")
    return redirect(url_for("match_detail", match_id=match["id"]))


@app.post("/games/<game_id>/sets")
@admin_required
def add_set(game_id: str):
    data = storage.snapshot()
    game = storage.find(data["games"], game_id)
    if not game:
        abort(404)
    if game.get("sets"):
        flash("This game already has a set score. Use the edit option to modify it.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    try:
        score_a = int(request.form.get("score_a", ""))
        score_b = int(request.form.get("score_b", ""))
    except ValueError:
        flash("Both set scores must be whole numbers.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    if score_a < 0 or score_b < 0:
        flash("Scores cannot be negative.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    if score_a == score_b:
        flash("A set cannot be a draw — one side must score more points.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    game["sets"] = [{"a": score_a, "b": score_b}]
    match = storage.find(data["matches"], game["match_id"])
    if match and match["status"] != "finished":
        match["status"] = "in_progress"
        storage.replace_row(data["matches"], match)
    storage.replace_row(data["games"], game)
    storage.save_all(data)
    flash(f"Set recorded: {score_a}–{score_b}.", "ok")
    return redirect(url_for("match_detail", match_id=game["match_id"]))


@app.post("/games/<game_id>/edit")
@admin_required
def edit_set(game_id: str):
    data = storage.snapshot()
    game = storage.find(data["games"], game_id)
    if not game:
        abort(404)
    if not game.get("sets"):
        flash("This game has no set score to edit.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    try:
        score_a = int(request.form.get("score_a", ""))
        score_b = int(request.form.get("score_b", ""))
    except ValueError:
        flash("Both set scores must be whole numbers.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    if score_a < 0 or score_b < 0:
        flash("Scores cannot be negative.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    if score_a == score_b:
        flash("A set cannot be a draw — one side must score more points.", "error")
        return redirect(url_for("match_detail", match_id=game["match_id"]))
    game["sets"] = [{"a": score_a, "b": score_b}]
    storage.replace_row(data["games"], game)
    storage.save_all(data)
    flash(f"Set score updated: {score_a}–{score_b}.", "ok")
    return redirect(url_for("match_detail", match_id=game["match_id"]))


@app.post("/matches/<match_id>/finish")
@admin_required
def finish_match(match_id: str):
    data = storage.snapshot()
    match = storage.find(data["matches"], match_id)
    if not match:
        abort(404)
    winner = storage.match_winner(data["games"], match_id)
    if not winner:
        flash("Record game scores first so one team has won more games.", "error")
        return redirect(url_for("match_detail", match_id=match_id))
    match["status"] = "finished"
    storage.replace_row(data["matches"], match)
    storage.save_all(data)
    flash("Match marked as finished.", "ok")
    return redirect(url_for("match_detail", match_id=match_id))


@app.post("/matches/<match_id>/reopen")
@admin_required
def reopen_match(match_id: str):
    data = storage.snapshot()
    match = storage.find(data["matches"], match_id)
    if not match:
        abort(404)
    match["status"] = "in_progress"
    storage.replace_row(data["matches"], match)
    storage.save_all(data)
    flash("Match reopened for editing.", "ok")
    return redirect(url_for("match_detail", match_id=match_id))


def _team_return(team: dict) -> str:
    if team.get("group_id"):
        return url_for("group_detail", group_id=team["group_id"])
    return url_for("home")


def _match_view(match: dict, data: dict) -> dict:
    team_a = storage.find(data["teams"], match["team_a_id"])
    team_b = storage.find(data["teams"], match["team_b_id"])
    group = storage.find(data["groups"], match["group_id"])
    games = sorted(
        [g for g in data["games"] if g["match_id"] == match["id"]],
        key=lambda g: g.get("order", 0),
    )
    players = {p["id"]: p for p in data["players"]}
    game_views = []
    for game in games:
        wins_a, wins_b = storage.game_score(game)
        game_views.append(
            {
                **game,
                "label": CATEGORIES[game["category"]]["label"],
                "spec": CATEGORIES[game["category"]],
                "team_a_players": [players[pid] for pid in game.get("team_a_player_ids", []) if pid in players],
                "team_b_players": [players[pid] for pid in game.get("team_b_player_ids", []) if pid in players],
                "wins_a": wins_a,
                "wins_b": wins_b,
                "winner": storage.game_winner(game),
            }
        )
    games_a, games_b = storage.match_game_tally(data["games"], match["id"])
    return {
        **match,
        "team_a": team_a,
        "team_b": team_b,
        "group": group,
        "games": game_views,
        "games_a": games_a,
        "games_b": games_b,
        "winner": storage.match_winner(data["games"], match["id"]),
        "roster_a": sorted(
            [p for p in data["players"] if p["team_id"] == match["team_a_id"]],
            key=lambda p: p["name"].lower(),
        ),
        "roster_b": sorted(
            [p for p in data["players"] if p["team_id"] == match["team_b_id"]],
            key=lambda p: p["name"].lower(),
        ),
    }


if __name__ == "__main__":
    storage.snapshot()
    port = int(os.environ.get("PORT", 5050))
    # Production deployment (Render, etc.)
    if os.environ.get("FLASK_ENV") == "production":
        from waitress import serve
        serve(app, host="0.0.0.0", port=port)
    else:
        # Local development
        app.run(debug=True, port=port)
