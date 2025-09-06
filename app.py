import time, math, os
import streamlit as st
import pandas as pd
import pydeck as pdk

st.set_page_config(page_title="Nearest Safe Shelter — Vyshhorod", layout="wide")

# ----------------------------
# Defaults (Vyshhorod center)
# ----------------------------
HOME_LAT, HOME_LON = 50.583, 30.486   # Vyshhorod
TICK_SECONDS = 1.0                     # refresh cadence

# ALERT/SAFE pattern in seconds (loops forever)
PATTERN = [("ALERT", 120), ("SAFE", 60), ("ALERT", 45), ("SAFE", 90)]

# If this CSV exists next to app.py, it will be loaded automatically
SHELTER_CSV = "shelters_vyshhorod.csv"  # columns: name,lat,lon[,type,capacity]

# ----------------------------
# Helpers
# ----------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2*R*math.asin(math.sqrt(a))

def pattern_length():
    return sum(d for _, d in PATTERN)

def state_at(t):
    """Return (state, elapsed_in_state, remaining_in_state) for t seconds into the loop."""
    t_mod = t % pattern_length()
    cum = 0
    for state, dur in PATTERN:
        if t_mod < cum + dur:
            elapsed = t_mod - cum
            remain = dur - elapsed
            return state, int(elapsed), int(remain)
        cum += dur
    return "SAFE", 0, PATTERN[1][1]

def load_shelters_from_csv(file_or_path) -> pd.DataFrame:
    df = pd.read_csv(file_or_path)
    if not {"name","lat","lon"}.issubset(df.columns):
        raise ValueError("CSV must have columns: name, lat, lon (optionally: type, capacity)")
    cols = ["name","lat","lon"] + [c for c in ["type","capacity"] if c in df.columns]
    return df[cols].copy()

def load_default_shelters() -> pd.DataFrame:
    data = [
        {"name":"Community Shelter Alpha","lat":50.593,"lon":30.501,"type":"Public","capacity":280},
        {"name":"School Shelter Beta","lat":50.590,"lon":30.472,"type":"Public","capacity":220},
        {"name":"Clinic Shelter Gamma","lat":50.576,"lon":30.498,"type":"Public","capacity":150},
        {"name":"Cultural Center Basement","lat":50.569,"lon":30.480,"type":"Public","capacity":180},
        {"name":"Industrial Shelter East","lat":50.589,"lon":30.515,"type":"Staff","capacity":120},
        {"name":"Parking Level -2 (Public)","lat":50.585,"lon":30.463,"type":"Public","capacity":200},
        {"name":"Library Basement","lat":50.592,"lon":30.472,"type":"Public","capacity":140},
        {"name":"Sports Complex Shelter","lat":50.572,"lon":30.450,"type":"Public","capacity":300},
        {"name":"Municipal Office Basement","lat":50.5805,"lon":30.489,"type":"Public","capacity":160},
        {"name":"Warehouse Underground","lat":50.600,"lon":30.490,"type":"Staff","capacity":110},
    ]
    return pd.DataFrame(data)

# ----------------------------
# Session state
# ----------------------------
ss = st.session_state
if "running"   not in ss: ss.running = True
if "tick"      not in ss: ss.tick = 0
if "home_lat"  not in ss: ss.home_lat = HOME_LAT
if "home_lon"  not in ss: ss.home_lon = HOME_LON
if "shelters"  not in ss:
    if os.path.exists(SHELTER_CSV):
        ss.shelters = load_shelters_from_csv(SHELTER_CSV)
    else:
        ss.shelters = load_default_shelters()

# ----------------------------
# Sidebar
# ----------------------------
st.sidebar.title("Vyshhorod Shelter Controls")

with st.sidebar.expander("Your location (Vyshhorod by default)", expanded=True):
    col_l1, col_l2 = st.columns(2)
    ss.home_lat = col_l1.number_input("Latitude", value=float(ss.home_lat), step=0.0005, format="%.6f")
    ss.home_lon = col_l2.number_input("Longitude", value=float(ss.home_lon), step=0.0005, format="%.6f")
    if st.button("Reset to Vyshhorod"):
        ss.home_lat, ss.home_lon = HOME_LAT, HOME_LON

with st.sidebar.expander("Shelters data", expanded=True):
    st.write("Using **shelters_vyshhorod.csv** if present; otherwise built-in list.")
    if os.path.exists(SHELTER_CSV):
        st.success(f"{SHELTER_CSV} found ✓")
    else:
        st.warning(f"{SHELTER_CSV} not found—using built-in demo list.")
    up = st.file_uploader("Upload shelters.csv (name,lat,lon[,type,capacity])", type=["csv"])
    if up is not None:
        try:
            ss.shelters = load_shelters_from_csv(up)
            st.success(f"Loaded {len(ss.shelters)} shelters from uploaded CSV.")
        except Exception as e:
            st.error(f"CSV error: {e}")

radius_km = st.sidebar.slider("Focus radius (km)", 1, 10, 3, step=1)

c1, c2, c3, c4 = st.sidebar.columns(4)
if c1.button("▶ Start"): ss.running = True
if c2.button("⏸ Stop"):  ss.running = False
if c3.button("↺ Reset"):
    ss.running = False
    ss.tick = 0
if c4.button("🔥 Inject Alert"):
    pass  # pattern already starts with ALERT

ff1, ff2, ff3 = st.sidebar.columns(3)
if ff1.button("+30s"): ss.tick += 30
if ff2.button("+2m"):  ss.tick += 120
if ff3.button("+5m"):  ss.tick += 300

# ----------------------------
# Compute state & nearest shelters
# ----------------------------
state, elapsed, remain = state_at(ss.tick)
is_alert = (state == "ALERT")

home_lat, home_lon = ss.home_lat, ss.home_lon
df_s = ss.shelters.copy()
df_s["dist_km"] = df_s.apply(lambda r: haversine_km(home_lat, home_lon, r["lat"], r["lon"]), axis=1)
df_s["eta_min"] = (df_s["dist_km"] * 12).clip(lower=1).round().astype(int)  # walk ~5 km/h

# Filter to focus radius
df_focus = df_s[df_s["dist_km"] <= radius_km].sort_values("dist_km")
top2 = df_focus.head(2) if not df_focus.empty else df_s.nsmallest(2, "dist_km")

# ----------------------------
# Layout
# ----------------------------
colA, colB = st.columns([1,3])

# ---- Status & guidance
with colA:
    st.markdown("### Status (Vyshhorod)")
    if is_alert:
        st.markdown(
            f"<div style='padding:12px;border-radius:12px;background:#ffeded;color:#b00020;font-weight:700;'>"
            f"🚨 ALERT — Go to shelter now<br/>Time remaining: {remain}s</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            f"<div style='padding:12px;border-radius:12px;background:#e7f7ee;color:#0b7a3b;font-weight:700;'>"
            f"✅ SAFE — Stay ready<br/>Next change in ~{remain}s</div>",
            unsafe_allow_html=True)

    st.write(f"Tick: {ss.tick}s • State elapsed: {elapsed}s")
    st.write(f"Focus radius: **{radius_km} km** • Your location: ({home_lat:.5f}, {home_lon:.5f})")

    st.markdown("#### Nearest shelters")
    if top2.empty:
        st.warning("No shelters within radius. Increase the radius or upload a CSV.")
    else:
        for _, srow in top2.iterrows():
            extra = []
            if "type" in srow and not pd.isna(srow["type"]):      extra.append(str(srow["type"]))
            if "capacity" in srow and not pd.isna(srow["capacity"]): extra.append(f"cap {int(srow['capacity'])}")
            extra_txt = f" • {' • '.join(extra)}" if extra else ""
            st.write(f"**{srow['name']}** — {srow['dist_km']:.2f} km • ~{srow['eta_min']} min walk{extra_txt}")

    # Download "My Plan"
    if not top2.empty:
        plan_lines = [
            "Nearest Shelter Plan — Vyshhorod",
            f"My location: {home_lat:.5f}, {home_lon:.5f}",
            f"Status: {'ALERT' if is_alert else 'SAFE'} (remain {remain}s)",
            "",
        ]
        for i, (_, r) in enumerate(top2.iterrows(), start=1):
            plan_lines.append(f"{i}. {r['name']} — {r['dist_km']:.2f} km (~{r['eta_min']} min)")
        txt = "\n".join(plan_lines)
        st.download_button("📄 Download My Plan (TXT)", data=txt.encode("utf-8"),
                           file_name="vyshhorod_shelter_plan.txt", mime="text/plain")

        csv_bytes = top2[["name","lat","lon","dist_km","eta_min"] + [c for c in ["type","capacity"] if c in top2.columns]] \
                        .to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download My Plan (CSV)", data=csv_bytes,
                           file_name="vyshhorod_shelter_plan.csv", mime="text/csv")

# ---- Map (fixed)
with colB:
    # Layers: home, shelters, highlights, paths, focus ring
    home_layer = pdk.Layer(
        "ScatterplotLayer",
        data=[{"name":"You","lat":home_lat,"lon":home_lon}],
        get_position='[lon, lat]',
        get_radius=60,
        get_fill_color='[200, 30, 30]' if is_alert else '[30, 160, 60]',
        pickable=True,
    )

    shelter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_s[["name","lat","lon"]].to_dict("records"),
        get_position='[lon, lat]',
        get_radius=50,
        get_fill_color='[30, 120, 200]',
        pickable=True,
    )

    highlight_layer = pdk.Layer(
        "ScatterplotLayer",
        data=top2[["name","lat","lon"]].to_dict("records"),
        get_position='[lon, lat]',
        get_radius=85,
        get_fill_color='[240, 180, 0]',
        pickable=True,
    )

    paths = [{"path":[[home_lon, home_lat],[r["lon"], r["lat"]]], "name":f"→ {r['name']}"}
             for _, r in top2.iterrows()]
    path_layer = pdk.Layer(
        "PathLayer",
        data=paths,
        get_path="path",
        width_scale=2,
        get_width=5,
        get_color=[255, 140, 0] if is_alert else [120,120,120],
        pickable=True,
    )

    focus_ring = pdk.Layer(
        "ScatterplotLayer",
        data=[{"lat": HOME_LAT, "lon": HOME_LON, "name":"Vyshhorod"}],
        get_position='[lon, lat]',
        get_radius=int(radius_km*320),  # rough visual radius
        get_fill_color='[30,160,60,30]',
        pickable=False,
    )

    deck = pdk.Deck(
        map_provider="carto",      # <= free tiles, no token needed
        map_style="dark",
        initial_view_state=pdk.ViewState(latitude=HOME_LAT, longitude=HOME_LON, zoom=12.2),
        layers=[focus_ring, shelter_layer, highlight_layer, path_layer, home_layer],
        tooltip={"text": "{name}"},
    )

    st.pydeck_chart(deck, use_container_width=True, height=520)

# ----------------------------
# Auto-tick & rerun
# ----------------------------
if ss.running:
    time.sleep(TICK_SECONDS)
    ss.tick += 1
    st.rerun()
