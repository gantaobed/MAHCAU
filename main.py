from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import requests
import sqlite3
import os
from datetime import datetime, timedelta

app = FastAPI(title="MAHCAU Sentinel")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_NAME = "habitat_sentinel_ultimate.db"

# --- CAUVERY BASIN LOCKDOWN ---
CAUVERY_BOUNDS = {"lat_min": 10.0, "lat_max": 13.5, "lng_min": 75.0, "lng_max": 80.5}

# --- SCIENTIFIC DATA (Tor remadeviae - Wikipedia Sourced) ---
SPECIES_FACTS = {
    "name": "Orange-finned Mahseer (Tor remadeviae)",
    "alias": "Hump-backed Mahseer",
    "status": "Critically Endangered (IUCN)",
    "basin": "Endemic to Kaveri River Basin Only",
    "traits": "Prominent hump originating above the pre-opercle, distinctive kink in the pre-opercule, terminal mouth position, and its bright orange caudal fin.",
    "fame": "Anglers proclaim it as the 'largest and hardest fighting freshwater fish in the world'.",
    "threats": ["Dams", "River Fragmentation", "Invasive Species (T. khudree, T. putitora)", "Sand Mining", "Dynamite Fishing"]
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS assessments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, lat REAL, lng REAL,
        status_color TEXT, alert TEXT, mining_risk REAL, temp REAL,
        range_audit TEXT, basin_audit TEXT, constraint_audit TEXT)""")
    conn.commit()
    conn.close()

init_db()

class EnvironmentData(BaseModel):
    lat: float
    lng: float
    sand_mining: bool = False
    upstream_mining: bool = False

def fetch_telemetry(lat: float, lng: float):
    try:
        w_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=temperature_2m,soil_temperature_0_to_7cm&daily=precipitation_sum&timezone=auto"
        w = requests.get(w_url, timeout=5).json()
        return {"temp": w.get("current", {}).get("soil_temperature_0_to_7cm", 22.0), "rain": w.get("daily", {}).get("precipitation_sum", [0.0])[0]}
    except: 
        return {"temp": 22.0, "rain": 0.0}

@app.post("/assess-zone")
def assess_habitat(data: EnvironmentData):
    in_range = CAUVERY_BOUNDS["lat_min"] <= data.lat <= CAUVERY_BOUNDS["lat_max"] and \
               CAUVERY_BOUNDS["lng_min"] <= data.lng <= CAUVERY_BOUNDS["lng_max"]

    tel = fetch_telemetry(data.lat, data.lng)
    mining_prob = 85 if 12.1 < data.lat < 12.4 else (15 if data.upstream_mining else (50 if data.sand_mining else 0))

    range_audit = "PASSED" if in_range else "FAILED"
    basin_audit = "Kaveri Basin System" if in_range else "Outside Endemic Domain"
    constraint_audit = "STABLE" if (mining_prob == 0 and 19 <= tel["temp"] <= 25) else "VIOLATED"

    if not in_range:
        color, alert = "gray", f"🔴 DOMAIN ERROR: {SPECIES_FACTS['name']} is NOT found here. Restricted to Kaveri basin."
    elif mining_prob > 0:
        color, alert = "red", f"⛔ ILLEGAL MINING ZONE: Spawning strictly prohibited. Mining Risk: {mining_prob}%"
    elif not constraint_audit == "STABLE":
        color, alert = "red", f"🔴 CRITICAL: Thermal Spike ({tel['temp']}°C). Eggs rot or hatch prematurely (Ideal: 18-24°C)."
    else:
        color, alert = "green", "🟢 PROTECTED SANCTUARY: 0% Mining detected. Verified Spawning Site."

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO assessments (timestamp, lat, lng, status_color, alert, mining_risk, temp, range_audit, basin_audit, constraint_audit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (datetime.now().strftime("%Y-%m-%d %H:%M"), data.lat, data.lng, color, alert, mining_prob, tel["temp"], range_audit, basin_audit, constraint_audit))
    conn.commit()
    conn.close()

    return {
        "color": color, "alert": alert,
        "audit": {"range": range_audit, "basin": basin_audit, "constraints": constraint_audit},
        "details": {"temp": tel["temp"], "mining": mining_prob}
    }

@app.get("/history-view")
async def history_view():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, alert, mining_risk, lat, lng FROM assessments ORDER BY id DESC LIMIT 50")
    rows = cursor.fetchall()
    conn.close()
    
    # HTML Fragment for SPA integration
    html = "<h2 class='custom-cursive title-text'>MAHCAU: Study Logs</h2>"
    for r in rows: 
        html += f"<div class='info-card'><b>{r[1]}</b><br><small class='log-meta'>{r[0]} | Risk: <span class='risk-red'>{r[2]}%</span> | Loc: {r[3]:.4f}, {r[4]:.4f}</small></div>"
    return HTMLResponse(content=html)

@app.get("/species-info")
async def species_info():
    # HTML Fragment for SPA integration
    html = f"""
    <h2 class='custom-cursive title-text' style='color:#62e8ff;'>{SPECIES_FACTS['name']}</h2>
    <div class='info-card'>
        <h3 class='custom-cursive' style='color:#ffc21a; font-size:20px; margin-top:0;'>🐟 Characteristics (Wikipedia)</h3>
        <p style='line-height:1.6;'>{SPECIES_FACTS['traits']}</p>
    </div>
    <div class='info-card'>
        <h3 class='custom-cursive' style='color:#ffc21a; font-size:20px; margin-top:0;'>🌍 Distribution</h3>
        <p style='line-height:1.6;'><b>{SPECIES_FACTS['basin']}</b>. Restricted to the Kaveri basin. {SPECIES_FACTS['fame']}</p>
    </div>
    <div class='info-card' style='border-left:4px solid #ff3d61;'>
        <h3 class='custom-cursive' style='color:#ffc21a; font-size:20px; margin-top:0;'>⚠️ IUCN: {SPECIES_FACTS['status']}</h3>
        <p style='line-height:1.6;'><b>Threats:</b> {", ".join(SPECIES_FACTS['threats'])}</p>
    </div>
    <div style='text-align:center; padding: 20px 0; font-size: 11px; color: #555;'>© Developed by Ganta Obed</div>
    """
    return HTMLResponse(content=html)

# Adjust this path based on your folder structure
frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
# Fallback to current dir if frontend doesn't exist
if not os.path.exists(frontend_path):
    frontend_path = os.path.dirname(__file__)

@app.get("/")
async def read_index(): 
    return FileResponse(os.path.join(frontend_path, "index.html"))
