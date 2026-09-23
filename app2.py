import io
import json
import math
from pathlib import Path
import re
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

# ==================================================
# CONFIG & PADEN
# ==================================================

HISTORIE_FILE = Path("historie_database.parquet")
COLORS_FILE = Path("colors.json")

DEFAULT_COLORS = [
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

st.set_page_config(
    page_title="Temperatuur & Vocht Dashboard Wilderhof", layout="wide"
)

st.title("🌡️💧 Temperatuur & Vocht Dashboard Wilderhof (Cloud)")

# ==================================================
# FUNCTIES VOOR KLEURBEHEER & ZONSTIJDEN
# ==================================================


def load_saved_colors():
    if COLORS_FILE.exists():
        try:
            with open(COLORS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_colors(colors_dict):
    try:
        with open(COLORS_FILE, "w") as f:
            json.dump(colors_dict, f, indent=4)
    except Exception as e:
        st.error(f"Konden kleuren niet opslaan: {e}")


@st.cache_data
def get_sun_times(date_obj, lat=50.85, lon=5.35):
    """Berekent automatisch zonsopgang en zonsondergang voor Wilderhof (gecachet)."""
    day_of_year = date_obj.timetuple().tm_yday
    lng_hour = lon / 15.0
    results = {}

    for is_sunrise in [True, False]:
        t_approx = (
            day_of_year + ((6.0 if is_sunrise else 18.0) - lng_hour) / 24.0
        )
        M = (0.9856002 * t_approx) - 3.289
        M_rad = math.radians(M)

        L = (
            M
            + (1.916 * math.sin(M_rad))
            + (0.020 * math.sin(2 * M_rad))
            + 282.634
        ) % 360
        L_rad = math.radians(L)

        RA = math.degrees(math.atan(0.91764 * math.tan(L_rad))) % 360
        L_quad = math.floor(L / 90.0) * 90.0
        RA_quad = math.floor(RA / 90.0) * 90.0
        RA = (RA + (L_quad - RA_quad)) / 15.0

        sin_dec = 0.39782 * math.sin(L_rad)
        cos_dec = math.cos(math.asin(sin_dec))

        lat_rad = math.radians(lat)
        zenith_rad = math.radians(90.833)

        cos_H = (math.cos(zenith_rad) - (sin_dec * math.sin(lat_rad))) / (
            cos_dec * math.cos(lat_rad)
        )

        if cos_H > 1 or cos_H < -1:
            continue

        H = (
            360.0 - math.degrees(math.acos(cos_H))
            if is_sunrise
            else math.degrees(math.acos(cos_H))
        )
        H = H / 15.0

        T = H + RA - (0.06571 * t_approx) - 6.622
        UT = (T - lng_hour) % 24.0

        hours = int(UT)
        minutes = int((UT - hours) * 60)
        seconds = int((((UT - hours) * 60) - minutes) * 60)

        dt_utc = pd.Timestamp(
            year=date_obj.year,
            month=date_obj.month,
            day=date_obj.day,
            hour=hours,
            minute=minutes,
            second=seconds,
            tz="UTC",
        )
        dt_local = dt_utc.tz_convert("Europe/Brussels").tz_localize(None)

        if is_sunrise:
            results["sunrise"] = dt_local
        else:
            results["sunset"] = dt_local

    return results.get("sunrise"), results.get("sunset")


# ==================================================
# BEREKENING GROEITIJD ANALYSE (MET CACHING)
# ==================================================


@st.cache_data(show_spinner=False)
def bereken_groeitijd(df_input, min_temp, max_temp):
    df_temp_only = df_input[df_input["Type"] == "Temperatuur"].copy()
    if df_temp_only.empty:
        return pd.DataFrame()

    ongewenste_termen = ["biomeiler", "buiten"]
    df_temp_only = df_temp_only[
        ~df_temp_only["Locatie"]
        .str.lower()
        .str.contains("|".join(ongewenste_termen))
    ]

    if df_temp_only.empty:
        return pd.DataFrame()

    df_temp_only["DatumTijd"] = pd.to_datetime(df_temp_only["DatumTijd"])
    if df_temp_only["DatumTijd"].dt.tz is not None:
        df_temp_only["DatumTijd"] = df_temp_only["DatumTijd"].dt.tz_localize(
            None
        )

    results = []
    unieke_datums = sorted(df_temp_only["Datum"].unique())

    for d in unieke_datums:
        sunrise_dt, sunset_dt = get_sun_times(d)
        if not sunrise_dt or not sunset_dt:
            continue

        df_dag = df_temp_only[
            (df_temp_only["DatumTijd"] >= sunrise_dt)
            & (df_temp_only["DatumTijd"] <= sunset_dt)
        ]

        if df_dag.empty:
            continue

        dag_groeiminuten = {}

        for loc in df_dag["Locatie"].unique():
            sub_df = df_dag[df_dag["Locatie"] == loc].sort_values("DatumTijd")
            if len(sub_df) < 2:
                continue

            sub_df = sub_df.drop_duplicates(subset=["DatumTijd"]).set_index(
                "DatumTijd"
            )
            resampled = (
                sub_df["Waarde"].resample("1min").interpolate(method="time")
            )

            is_optimal = (resampled >= min_temp) & (resampled <= max_temp)
            dag_groeiminuten[loc] = is_optimal.sum()

        if not dag_groeiminuten:
            continue

        niet_verwarmde_locs = [
            loc
            for loc in dag_groeiminuten.keys()
            if str(loc).upper().startswith("NIET VERWARMD")
        ]

        if niet_verwarmde_locs:
            baseline_minuten = sum(
                dag_groeiminuten[loc] for loc in niet_verwarmde_locs
            ) / len(niet_verwarmde_locs)
        else:
            baseline_minuten = 0.0

        for loc, v_minuten in dag_groeiminuten.items():
            is_onverwarmd = str(loc).upper().startswith("NIET VERWARMD")
            verwarmd_status = "Niet Verwarmd" if is_onverwarmd else "Verwarmd"

            if verwarmd_status == "Verwarmd" and baseline_minuten > 0:
                winst_minuten = max(0.0, v_minuten - baseline_minuten)
            else:
                winst_minuten = 0.0

            results.append({
                "Datum": d.strftime("%d/%m/%Y"),
                "Locatie": loc,
                "Type Locatie": verwarmd_status,
                "Groeitijd Locatie (min)": round(v_minuten, 1),
                "Groeitijd Locatie (uur)": round(v_minuten / 60.0, 2),
                "Baseline Niet-Verwarmd Gem. (min)": round(
                    baseline_minuten, 1
                ),
                "Extra Groeitijd (minuten)": round(winst_minuten, 1),
                "Extra Groeitijd (uren)": round(winst_minuten / 60.0, 2),
            })

    return pd.DataFrame(results)


# ==================================================
# FUNCTIE VOOR INLEZEN GEÜPLOADDE BESTANDEN
# ==================================================


def verwerk_geuploade_bestanden(uploaded_files):
    historie_df = pd.DataFrame()
    if HISTORIE_FILE.exists():
        try:
            historie_df = pd.read_parquet(HISTORIE_FILE)
        except Exception:
            pass

    if not uploaded_files:
        return historie_df

    nieuwe_dfs = []
    for f in uploaded_files:
        filename_stem = Path(f.name).stem
        if "_" in filename_stem:
            loc_name = filename_stem.split("_", 1)[1].strip()
        else:
            loc_name = filename_stem

        try:
            xls = pd.ExcelFile(f)
            sheet_to_read = "Devices" if "Devices" in xls.sheet_names else 0
            df_raw = pd.read_excel(f, sheet_name=sheet_to_read, header=None)

            if sheet_to_read == "Devices" or (
                len(df_raw) > 3 and "tijdstempel" in str(df_raw.iloc[3, 0]).lower()
            ):
                data_df = df_raw.iloc[4:].copy()
                data_df.columns = ["DatumTijd", "Waarde"]
                data_df["DatumTijd"] = pd.to_datetime(
                    data_df["DatumTijd"], errors="coerce"
                )

                def clean_val(val):
                    if pd.isna(val):
                        return None
                    if isinstance(val, (int, float)):
                        return float(val)
                    m = re.search(r"[-+]?\d*\.\d+|\d+", str(val))
                    return float(m.group()) if m else None

                data_df["Waarde"] = data_df["Waarde"].apply(clean_val)
                data_df = data_df.dropna(subset=["DatumTijd", "Waarde"])

                is_vocht = any(
                    kw in loc_name.lower()
                    for kw in ["vocht", "moisture", "humidity", "rv", "%"]
                )
                data_df["Locatie"] = loc_name
                data_df["Type"] = "Vochtgehalte" if is_vocht else "Temperatuur"

                nieuwe_dfs.append(
                    data_df[["DatumTijd", "Waarde", "Locatie", "Type"]]
                )
        except Exception as e:
            st.warning(f"Fout bij verwerken van {f.name}: {e}")

    if not nieuwe_dfs:
        return historie_df

    df_nieuw = pd.concat(nieuwe_dfs, ignore_index=True)

    if not historie_df.empty:
        historie_df["DatumTijd"] = pd.to_datetime(historie_df["DatumTijd"])
        df_gecombineerd = pd.concat(
            [historie_df, df_nieuw], ignore_index=True
        )
    else:
        df_gecombineerd = df_nieuw

    df_gecombineerd = df_gecombineerd.drop_duplicates(
        subset=["DatumTijd", "Locatie"], keep="last"
    )
    df_gecombineerd = df_gecombineerd.sort_values("DatumTijd").reset_index(
        drop=True
    )

    df_gecombineerd["Datum"] = df_gecombineerd["DatumTijd"].dt.date
    week_nr = df_gecombineerd["DatumTijd"].dt.isocalendar().week
    monday = df_gecombineerd["DatumTijd"].dt.floor("D") - pd.to_timedelta(
        df_gecombineerd["DatumTijd"].dt.dayofweek, unit="D"
    )
    sunday = monday + pd.Timedelta(days=6)

    df_gecombineerd["Week_Label"] = (
        "Week "
        + week_nr.astype(str)
        + " ("
        + monday.dt.strftime("%d/%m")
        + " - "
        + sunday.dt.strftime("%d/%m/%Y")
        + ")"
    )
    df_gecombineerd["Week_Sort"] = monday

    try:
        df_gecombineerd.to_parquet(HISTORIE_FILE, index=False)
    except Exception as e:
        st.error(f"Kon historiebestand niet wegschrijven: {e}")

    return df_gecombineerd


# ==================================================
# SIDEBAR: WACHTWOORD, UPLOADEN & FILTERS
# ==================================================

st.sidebar.header("📂 Databron Beheer")

# Wachtwoordbeveiliging voor uploads
beheerders_wachtwoord = st.sidebar.text_input(
    "Beheerderswachtwoord", type="password"
)

if beheerders_wachtwoord == "adminUCLL":
    st.sidebar.success("Beheerdersmodus actief")
    uploaded_files = st.sidebar.file_uploader(
        "Upload Senzemo Excel-bestanden",
        type=["xlsx", "xlsm", "xls"],
        accept_multiple_files=True,
    )

    if uploaded_files:
        if st.sidebar.button(
            "🔄 Verwerk bestanden & update historie", use_container_width=True
        ):
            with st.spinner("Nieuwe data inlezen en samenvoegen met historie..."):
                verwerk_geuploade_bestanden(uploaded_files)
            st.sidebar.success("Historie succesvol bijgewerkt!")
            st.rerun()
else:
    if beheerders_wachtwoord:
        st.sidebar.error("Onjuist wachtwoord")
    st.sidebar.info(
        "🔒 Vul het beheerderswachtwoord in om bestanden te kunnen uploaden."
    )

# Altijd de bestaande historie inlezen
if HISTORIE_FILE.exists():
    df = pd.read_parquet(HISTORIE_FILE)
else:
    df = pd.DataFrame()

if df.empty:
    st.warning(
        "⚠️ Nog geen historische data gevonden. Vul het wachtwoord in en upload je Excel-bestanden om te beginnen."
    )
    st.stop()

st.sidebar.write("---")
st.sidebar.header("📊 Filters & Instellingen")

locaties = sorted(df["Locatie"].unique().tolist())
with st.sidebar.popover("📍 Locaties kiezen", use_container_width=True):
    col_b1, col_b2 = st.columns(2)
    if col_b1.button("Alles", key="btn_all_loc"):
        for loc in locaties:
            st.session_state[f"cb_loc_{loc}"] = True
        st.rerun()
    if col_b2.button("Wis", key="btn_none_loc"):
        for loc in locaties:
            st.session_state[f"cb_loc_{loc}"] = False
        st.rerun()

    gekozen_locaties = []
    for loc in locaties:
        key = f"cb_loc_{loc}"
        if key not in st.session_state:
            if "einde" in loc.lower():
                st.session_state[key] = False
            else:
                st.session_state[key] = True

        if st.checkbox(loc, key=key):
            gekozen_locaties.append(loc)

st.sidebar.caption(
    f"_{len(gekozen_locaties)} van {len(locaties)} locaties geselecteerd_"
)
st.sidebar.write("---")

df_weken_sorted = df.sort_values("Week_Sort")
weken = df_weken_sorted["Week_Label"].unique().tolist()

with st.sidebar.popover("📅 Weken kiezen", use_container_width=True):
    col_b1, col_b2 = st.columns(2)
    if col_b1.button("Alles", key="btn_all_week"):
        for w in weken:
            st.session_state[f"cb_week_{w}"] = True
        st.rerun()
    if col_b2.button("Wis", key="btn_none_week"):
        for w in weken:
            st.session_state[f"cb_week_{w}"] = False
        st.rerun()

    gekozen_weken = []
    for w in weken:
        key = f"cb_week_{w}"
        if key not in st.session_state:
            st.session_state[key] = True
        if st.checkbox(w, key=key):
            gekozen_weken.append(w)

st.sidebar.caption(f"_{len(gekozen_weken)} van {len(weken)} weken geselecteerd_")
st.sidebar.write("---")

df_temp_week = df[df["Week_Label"].isin(gekozen_weken)]
beschikbare_datums = sorted(df_temp_week["Datum"].unique().tolist())

with st.sidebar.popover("📆 Datums kiezen", use_container_width=True):
    col_b1, col_b2 = st.columns(2)
    if col_b1.button("Alles", key="btn_all_datum"):
        for d in beschikbare_datums:
            st.session_state[f"cb_datum_{d}"] = True
        st.rerun()
    if col_b2.button("Wis", key="btn_none_datum"):
        for d in beschikbare_datums:
            st.session_state[f"cb_datum_{d}"] = False
        st.rerun()

    gekozen_datums = []
    for d in beschikbare_datums:
        key = f"cb_datum_{d}"
        if key not in st.session_state:
            st.session_state[key] = True
        if st.checkbox(d.strftime("%d/%m/%Y"), key=key):
            gekozen_datums.append(d)

st.sidebar.caption(
    f"_{len(gekozen_datums)} van {len(beschikbare_datums)} datums geselecteerd_"
)
st.sidebar.write("---")

saved_colors = load_saved_colors()
kleuren_map = {}
color_changed = False

with st.sidebar.popover("🎨 Kleuren aanpassen", use_container_width=True):
    st.markdown("**Kies een kleur per locatie:**")
    for idx, loc in enumerate(locaties):
        initial_color = saved_colors.get(
            loc, DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
        )
        gekozen_kleur = st.color_picker(
            f"{loc}", value=initial_color, key=f"cp_{loc}"
        )
        kleuren_map[loc] = gekozen_kleur

        if saved_colors.get(loc) != gekozen_kleur:
            saved_colors[loc] = gekozen_kleur
            color_changed = True

    if color_changed:
        save_colors(saved_colors)

df_filtered = df[
    (df["Locatie"].isin(gekozen_locaties))
    & (df["Week_Label"].isin(gekozen_weken))
    & (df["Datum"].isin(gekozen_datums))
]

# ==================================================
# HOOFDPAGINA: BEDIENING & GRAFIEK
# ==================================================

st.subheader("Temperatuur & Vochtgehalte Verloop")

if df_filtered.empty:
    st.info("Geen data beschikbaar voor de gekozen filters.")
else:
    st.markdown("#### 📊 Y-as Instellingen")
    df_temp_base = df_filtered[df_filtered["Type"] == "Temperatuur"]
    min_temp_default = (
        float(df_temp_base["Waarde"].min()) if not df_temp_base.empty else 0.0
    )
    max_temp_default = (
        float(df_temp_base["Waarde"].max()) if not df_temp_base.empty else 40.0
    )

    col_y1, col_y2 = st.columns(2)

    with col_y1:
        y_min_temp = st.number_input(
            "Y-as Temp Min (°C)",
            value=float(round(min_temp_default - 1.0, 1)),
            step=1.0,
        )
        y_max_temp = st.number_input(
            "Y-as Temp Max (°C)",
            value=float(round(max_temp_default + 1.0, 1)),
            step=1.0,
        )

    with col_y2:
        y_min_vocht = st.number_input("Y-as Vocht Min (%)", value=0.0, step=5.0)
        y_max_vocht = st.number_input(
            "Y-as Vocht Max (%)", value=100.0, step=5.0
        )

    st.write("---")

    st.markdown("#### ⚙️ Grenzen & Weergave")
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns(3)

    with col_ctrl1:
        tonen_grens = st.checkbox("Toon groeigrens", value=True)
        grens_waarde = st.number_input("Groeigrens (°C)", value=10.0, step=1.0)

    with col_ctrl2:
        tonen_stress = st.checkbox("Toon stressgrens", value=True)
        stress_waarde = st.number_input(
            "Stressgrens (°C)", value=27.0, step=1.0
        )

    with col_ctrl3:
        st.write("")
        tonen_zon = st.checkbox("Toon zonsopgang & -ondergang", value=False)

    st.write("---")

    min_dt = df_filtered["DatumTijd"].min().to_pydatetime()
    max_dt = df_filtered["DatumTijd"].max().to_pydatetime()

    if "x_axis_slider" not in st.session_state:
        st.session_state["x_axis_slider"] = (min_dt, max_dt)

    selected_dt_range = st.session_state["x_axis_slider"]
    if selected_dt_range[0] < min_dt or selected_dt_range[1] > max_dt:
        selected_dt_range = (min_dt, max_dt)
        if "x_axis_slider" in st.session_state:
            del st.session_state["x_axis_slider"]
        st.session_state["x_axis_slider"] = selected_dt_range

    # ==========================================
    # SLIDER + SCHUIF-KNOPPEN
    # ==========================================
    duration = selected_dt_range[1] - selected_dt_range[0]

    col_btn_l, col_slider, col_btn_r = st.columns([1, 8, 1])

    with col_btn_l:
        st.write("")
        if st.button("◀️ Terug", use_container_width=True, help="Schuif periode terug"):
            new_start = max(min_dt, selected_dt_range[0] - duration)
            new_end = new_start + duration
            if "x_axis_slider" in st.session_state:
                del st.session_state["x_axis_slider"]
            st.session_state["x_axis_slider"] = (new_start, new_end)
            st.rerun()

    with col_slider:
        selected_dt_range = st.slider(
            "🔍 Zoom in op Datum / Tijd bereik:",
            min_value=min_dt,
            max_value=max_dt,
            value=selected_dt_range,
            format="DD/MM/YYYY HH:mm",
            key="x_axis_slider",
        )

    with col_btn_r:
        st.write("")
        if st.button("Verder ▶️", use_container_width=True, help="Schuif periode verder"):
            new_end = min(max_dt, selected_dt_range[1] + duration)
            new_start = new_end - duration
            if "x_axis_slider" in st.session_state:
                del st.session_state["x_axis_slider"]
            st.session_state["x_axis_slider"] = (new_start, new_end)
            st.rerun()

    df_slider_filtered = df_filtered[
        (df_filtered["DatumTijd"] >= selected_dt_range[0])
        & (df_filtered["DatumTijd"] <= selected_dt_range[1])
    ]

    df_temp = df_slider_filtered[df_slider_filtered["Type"] == "Temperatuur"]
    df_vocht = df_slider_filtered[df_slider_filtered["Type"] == "Vochtgehalte"]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    for loc in gekozen_locaties:
        sub_df = df_temp[df_temp["Locatie"] == loc]
        if not sub_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=sub_df["DatumTijd"],
                    y=sub_df["Waarde"],
                    name=f"🌡️ {loc} (Temp)",
                    mode="lines",
                    line=dict(color=kleuren_map.get(loc, "#1f77b4")),
                    connectgaps=True,
                ),
                secondary_y=False,
            )

    for loc in gekozen_locaties:
        sub_df = df_vocht[df_vocht["Locatie"] == loc]
        if not sub_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=sub_df["DatumTijd"],
                    y=sub_df["Waarde"],
                    name=f"💧 {loc} (Vocht)",
                    mode="lines",
                    line=dict(
                        color=kleuren_map.get(loc, "#1f77b4"), dash="dash"
                    ),
                    connectgaps=True,
                ),
                secondary_y=True,
            )

    if tonen_grens:
        fig.add_trace(
            go.Scatter(
                x=[selected_dt_range[0], selected_dt_range[1]],
                y=[grens_waarde, grens_waarde],
                name=f"❄️ Groeigrens ({grens_waarde}°C)",
                mode="lines",
                line=dict(color="#1E88E5", dash="dot", width=2),
            ),
            secondary_y=False,
        )

    if tonen_stress:
        fig.add_trace(
            go.Scatter(
                x=[selected_dt_range[0], selected_dt_range[1]],
                y=[stress_waarde, stress_waarde],
                name=f"🔥 Stressgrens ({stress_waarde}°C)",
                mode="lines",
                line=dict(color="#D32F2F", dash="dashdot", width=2),
            ),
            secondary_y=False,
        )

    if tonen_zon:
        start_date = selected_dt_range[0].date()
        end_date = selected_dt_range[1].date()

        zichtbare_datums = [
            d
            for d in df_slider_filtered["Datum"].unique()
            if start_date <= d <= end_date
        ]

        for d in zichtbare_datums:
            sunrise_dt, sunset_dt = get_sun_times(d)
            if (
                sunrise_dt
                and selected_dt_range[0] <= sunrise_dt <= selected_dt_range[1]
            ):
                fig.add_vline(
                    x=sunrise_dt,
                    line_dash="dot",
                    line_color="#FFB300",
                    line_width=1.5,
                    opacity=0.7,
                )
            if (
                sunset_dt
                and selected_dt_range[0] <= sunset_dt <= selected_dt_range[1]
            ):
                fig.add_vline(
                    x=sunset_dt,
                    line_dash="dot",
                    line_color="#4F4F4F",
                    line_width=1.5,
                    opacity=0.7,
                )

        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="#FFB300", dash="dot", width=2),
                name="🌅 Zonsopgang",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                line=dict(color="#4F4F4F", dash="dot", width=2),
                name="🌇 Zonsondergang",
            ),
            secondary_y=False,
        )

    fig.update_layout(
        height=700,
        legend_title="Metingen & Lijnen",
        hovermode="x unified",
        uirevision=True,
    )

    fig.update_xaxes(
        title_text="Datum / Tijd",
        range=[selected_dt_range[0], selected_dt_range[1]],
        uirevision=True,
    )

    fig.update_yaxes(
        title_text="Temperatuur (°C)",
        range=[y_min_temp, y_max_temp],
        secondary_y=False,
        uirevision=False,
        anchor="x",
        autoshift=False,
    )
    fig.update_yaxes(
        title_text="Vochtgehalte (%)",
        range=[y_min_vocht, y_max_vocht],
        secondary_y=True,
        uirevision=False,
        anchor="x",
        autoshift=False,
    )

    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": True})

# ==================================================
# GROEITIJD EXPORT SECTIE (EXCEL)
# ==================================================

st.write("---")
st.subheader("🌱 Groeitijd Winst Analyse")

col_exp1, col_exp2 = st.columns([2, 1])

with col_exp1:
    st.write(
        "Bereken de groeitijd per locatie tussen zonsopgang en zonsondergang."
    )
    st.caption(
        f"Criteria: Temperatuur tussen **{grens_waarde}°C** en **{stress_waarde}°C** (binnen het geselecteerde slider-bereik)."
    )

with col_exp2:
    if st.button("🔄 Bereken Groeitijd Analyse", use_container_width=True):
        st.session_state["run_groeitijd"] = True

    if st.session_state.get("run_groeitijd", False):
        with st.spinner("Groeitijden berekenen..."):
            df_groeitijd = bereken_groeitijd(
                df_slider_filtered, grens_waarde, stress_waarde
            )

        if not df_groeitijd.empty:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                df_groeitijd.to_excel(
                    writer, index=False, sheet_name="Groeitijd_Analyse"
                )

            st.download_button(
                label="📊 Download Excel Bestand",
                data=output.getvalue(),
                file_name="Groeitijd_Analyse_Wilderhof.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        else:
            st.warning("Geen geschikte temperatuurdata gevonden.")

# ==================================================
# RUWE DATA SECTIE
# ==================================================

with st.expander("Ruwe data bekijken (van actieve slider-selectie)"):
    st.dataframe(df_slider_filtered, use_container_width=True)