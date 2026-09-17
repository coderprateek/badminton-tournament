# GOALS Badminton League 2026 — team badminton tournament site

Python (Flask) site for a team badminton event. Visitors can view groups, standings, and scores. Organizers sign in with an admin code to edit data. Everything is stored in `data/*.txt` so a server crash does not wipe the tournament.

## Run it

```bash
cd IdeaProjects/badminton-tournament
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5050](http://127.0.0.1:5050).

Default admin code (change it in `data/admin_code.txt`):

```
SMASH-ADMIN
```

## How to use it

1. **View-only** — anyone can open the site and follow groups, teams, and matches.
2. **Admin** — log in with the code. Only admins can create or edit data.
3. Add a **group**, then add **teams** (or create a team on the home page and later place it in a group).
4. Add **players** to each team (name + gender).
5. Click **Generate missing matches** to build a **round-robin** (every team plays every other team in the group).
6. Open a match, add games in any of the five categories:
   - Men's Singles
   - Women's Singles
   - Men's Doubles
   - Women's Doubles
   - Mixed Doubles
7. Pick the players for each game, then enter **set scores**. The higher score wins the set; the team that wins more sets wins the game; the team that wins more games wins the match.

## Persistence

JSON lists live in:

- `data/groups.txt`
- `data/teams.txt`
- `data/players.txt`
- `data/matches.txt`
- `data/games.txt`
- `data/admin_code.txt`

Writes use a temp file + replace so a crash mid-write does not leave a half-saved file.
