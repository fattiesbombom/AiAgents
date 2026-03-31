# AiAgents

Security AI System scaffold.

## Input DB perception (discrete events)

Operational alarms, MOP reports, access anomalies, and optional `motion_events` / `c2_alerts` rows in **Postgres** (`INPUT_DB_URL`, same DB as the input-db MCP) can drive incidents without video or wearable polling. A long-running poller (`backend/perception/input_db_watcher.py`) advances per-table cursors, applies filters from `.env`, and `POST`s JSON to the FastAPI `/trigger` endpoint (`TRIGGER_API_BASE_URL`). Enable with `INPUT_DB_WATCHER_ENABLED=true` and run:

`python -m backend.perception.start_input_db_watcher`

For local demos, optional dev seeding: `python -m backend.scripts.demo_seed_input_db` (see script docstring).

## DEMO SETUP
1. Install the IP Webcam app on your Android phone (free on Google Play)
2. Open the app, scroll to the bottom, tap Start Server
3. Note the URL shown on the phone screen e.g. http://192.168.1.42:8080
4. Set PHONE_IP=192.168.1.42 in your .env file
5. Make sure your phone and laptop are on the same WiFi network
6. Run: python scripts/run_demo.py
7. Point your phone at something — press spacebar to manually fire an incident trigger
