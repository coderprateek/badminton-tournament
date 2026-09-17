import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ["TOURNAMENT_DATA_DIR"] = tempfile.mkdtemp(prefix="smashcup-")

from app import app  # noqa: E402
import storage  # noqa: E402


class TournamentFlowTest(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        self.data_dir = Path(os.environ["TOURNAMENT_DATA_DIR"])
        for name in ("groups", "teams", "players", "matches", "games"):
            (self.data_dir / f"{name}.txt").write_text("[]\n")
        (self.data_dir / "admin_code.txt").write_text("SMASH-ADMIN\n")
        storage.snapshot()

    def test_viewer_cannot_create_group(self):
        response = self.client.post("/groups", data={"name": "Group A"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin login is required", response.data)
        data_dir = Path(os.environ["TOURNAMENT_DATA_DIR"])
        groups = json.loads((data_dir / "groups.txt").read_text())
        self.assertEqual(groups, [])

    def test_admin_round_robin_and_scores(self):
        login = self.client.post("/login", data={"code": "SMASH-ADMIN"}, follow_redirects=True)
        self.assertIn(b"Welcome, admin", login.data)

        self.client.post("/groups", data={"name": "Group A"})
        groups = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "groups.txt").read_text())
        group_id = groups[0]["id"]

        self.client.post(f"/groups/{group_id}/teams", data={"name": "Smashers"})
        self.client.post(f"/groups/{group_id}/teams", data={"name": "Netters"})
        teams = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "teams.txt").read_text())
        smashers = next(t for t in teams if t["name"] == "Smashers")
        netters = next(t for t in teams if t["name"] == "Netters")

        self.client.post(f"/teams/{smashers['id']}/players", data={"name": "Amit", "gender": "M"})
        self.client.post(f"/teams/{netters['id']}/players", data={"name": "Rahul", "gender": "M"})

        self.client.post(f"/groups/{group_id}/round-robin")
        matches = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "matches.txt").read_text())
        self.assertEqual(len(matches), 1)
        match_id = matches[0]["id"]

        self.client.post(f"/matches/{match_id}/games", data={"category": "MS"})
        games = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "games.txt").read_text())
        game_id = games[0]["id"]
        players = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "players.txt").read_text())
        amit = next(p for p in players if p["name"] == "Amit")
        rahul = next(p for p in players if p["name"] == "Rahul")

        self.client.post(
            f"/games/{game_id}/lineup",
            data={"team_a_player_ids": amit["id"], "team_b_player_ids": rahul["id"]},
        )
        self.client.post(f"/games/{game_id}/sets", data={"score_a": "21", "score_b": "15"})
        self.client.post(f"/matches/{match_id}/finish")

        page = self.client.get(f"/matches/{match_id}")
        self.assertIn(b"21", page.data)
        self.assertIn(b"finished", page.data)
        persisted = json.loads((Path(os.environ["TOURNAMENT_DATA_DIR"]) / "games.txt").read_text())
        self.assertEqual(persisted[0]["sets"][0], {"a": 21, "b": 15})


if __name__ == "__main__":
    unittest.main()
