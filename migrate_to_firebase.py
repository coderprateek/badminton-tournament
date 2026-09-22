"""Migrate local data to Firebase."""
import json
import os
from pathlib import Path

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

# Initialize Firebase
if not firebase_admin._apps:
    service_account_path = os.path.join(os.path.dirname(__file__), "firebase-service-account.json")
    if os.path.exists(service_account_path):
        cred = credentials.Certificate(service_account_path)
        firebase_admin.initialize_app(cred, options=FIREBASE_CONFIG)
        print("Firebase initialized with service account credentials")
    else:
        firebase_admin.initialize_app(options=FIREBASE_CONFIG)
        print("Firebase initialized with config (test mode)")

def migrate_data():
    """Migrate local data to Firebase."""
    data_dir = Path(__file__).resolve().parent / "data"
    
    # Read local data
    data = {}
    for key in ["groups", "teams", "players", "matches", "games"]:
        file_path = data_dir / f"{key}.txt"
        if file_path.exists():
            with open(file_path, 'r') as f:
                data[key] = json.loads(f.read().strip() or "[]")
        else:
            data[key] = []
    
    # Ensure admin code exists
    admin_file = data_dir / "admin_code.txt"
    if admin_file.exists():
        admin_code = admin_file.read_text().strip()
    else:
        admin_code = "SMASH-ADMIN"
    
    # Add game_config to groups that don't have it
    for group in data["groups"]:
        if isinstance(group, dict) and "game_config" not in group:
            group["game_config"] = {"MS": 1, "WS": 1, "MD": 1, "WD": 1, "XD": 1}
    
    # Save to Firebase
    for key, rows in data.items():
        db.reference(key).set(rows)
    
    # Save admin code
    db.reference("admin_code").set(admin_code)
    
    print("Data migration to Firebase completed!")
    print(f"Groups: {len(data['groups'])}")
    print(f"Teams: {len(data['teams'])}")
    print(f"Players: {len(data['players'])}")
    print(f"Matches: {len(data['matches'])}")
    print(f"Games: {len(data['games'])}")

if __name__ == "__main__":
    migrate_data()