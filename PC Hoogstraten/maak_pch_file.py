import pandas as pd
import numpy as np

# Lijst van de 9 PCH bestanden
pch_files = [
    "pch_kou20-001_R1_EINDE.xlsx",
    "pch_kou20-002_R5_BEGIN.xlsx",
    "pch_kou20-003_BIOMEILER_RAND_BOVENAAN.xlsx",
    "pch_kou20-004_R7_BEGIN.xlsx",
    "pch_kou20-005_NIET_VERWARMD_EINDE.xlsx",
    "pch_kou20-006_BIOMEILER_RAND_ONDERAAN.xlsx",
    "pch_kou20-007_R1_BEGIN.xlsx",
    "pch_kou20-008_BIOMEILER_CENTER.xlsx",
    "pch_kou20-009_NIET_VERWARMD_BEGIN.xlsx"
]

# Genereer datum-tijdstempels
dates = pd.date_range(start="2026-09-01 00:00:00", periods=100, freq="15min")

for fname in pch_files:
    loc_name = fname.replace(".xlsx", "").replace("pch_", "").upper()
    
    # Maak de structuur exact zoals Wilderhof (met Devices tabblad en 2 lege rijen)
    df_dummy = pd.DataFrame({
        loc_name: [np.nan, np.nan, "Tijdstempel van bericht"],
        "Unnamed: 1": [np.nan, np.nan, "TemperatureProbe1"]
    })
    
    rows = []
    for d in dates:
        val = round(np.random.uniform(20.0, 45.0), 2)
        rows.append({loc_name: str(d), "Unnamed: 1": f"{val} [°C]"})
        
    df_data = pd.DataFrame(rows)
    df_final = pd.concat([df_dummy, df_data], ignore_index=True)
    
    # Wegschrijven naar Excel
    df_final.to_excel(fname, sheet_name='Devices', index=False, header=False)
    print(f"Aangemaakt: {fname}")

print("Klaar! Alle 9 PCH-bestanden staan in je map.")