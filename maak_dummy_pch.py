import numpy as np
from pathlib import Path
import pandas as pd

# Pad naar de centrale mappen
wilderhof_file = Path("historie_database_wilderhof.parquet")
pch_file = Path("historie_database_pch.parquet")

if not wilderhof_file.exists():
    print(
        "Fout: De Wilderhof database is niet gevonden in deze map! Zorg dat"
        " deze hier eerst staat."
    )
else:
    # 1. Lees de echte Wilderhof data in
    df_wilderhof = pd.read_parquet(wilderhof_file)

    # 2. Maak een kopie voor PC Hoogstraten
    df_pch = df_wilderhof.copy()

    # Zorg voor een herhaalbare random generator (optioneel, voor stabiele resultaten)
    np.random.seed(42)

    # 3. Voeg random afwijkingen toe per meetwaarde
    # Voor temperaturen: tel een vaste offset van +2 graden op + een random getal tussen -2.5 en +2.5 graden
    mask_temp = df_pch["Type"] == "Temperatuur"
    random_temp_noise = np.random.uniform(-2.5, 2.5, size=mask_temp.sum())
    df_pch.loc[mask_temp, "Waarde"] = (
        df_pch.loc[mask_temp, "Waarde"] + 2.0 + random_temp_noise
    )

    # Voor vochtgehalte: vermenigvuldig met een factor rond de 1 + random afwijking tussen -10% en +10%
    mask_vocht = df_pch["Type"] == "Vochtgehalte"
    random_vocht_noise = np.random.uniform(-10.0, 10.0, size=mask_vocht.sum())
    df_pch.loc[mask_vocht, "Waarde"] = (
        df_pch.loc[mask_vocht, "Waarde"] + random_vocht_noise
    )
    # Zorg dat vocht altijd realistisch blijft tussen 0% en 100%
    df_pch.loc[mask_vocht, "Waarde"] = df_pch.loc[mask_vocht, "Waarde"].clip(
        0, 100
    )

    # 4. Opslaan als de nieuwe centrale PCH parquet file
    df_pch.to_parquet(pch_file, index=False)
    print(
        "Succes! De PC Hoogstraten database is bijgewerkt met dezelfde datums"
        " en een unieke random trend."
    )