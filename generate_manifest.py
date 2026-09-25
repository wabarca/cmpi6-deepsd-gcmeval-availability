#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generador Dinámico de Catálogo y Manifiesto CMIP6
=================================================

Lee una lista dinámica de modelos CMIP6 desde un archivo CSV/texto externo,
consulta los archivos NetCDF directos en ESGF aplicando filtrado por período
de interés y genera los manifiestos listos para descarga y procesamiento CDO.

Uso:
----
    python generate_manifest.py [opciones]

Ejemplos:
---------
    python generate_manifest.py
    python generate_manifest.py -i selected_models.csv -o cmip6_manifest.tsv
    python generate_manifest.py --input-csv cmip6_complete_models.csv --workers 8

Formatos de entrada soportados en el CSV (-i):
----------------------------------------------
1. Sin encabezado (un modelo por línea):
       EC-Earth3.r1i1p1f1
       NorESM2-MM.r1i1p1f1
2. Con encabezado 'model' o 'modelo':
       model
       EC-Earth3.r1i1p1f1
3. Con columnas separadas 'source_id' y 'variant_label':
       source_id,variant_label
       EC-Earth3,r1i1p1f1
"""

import os
import sys
import argparse
import importlib
import pandas as pd

# Importar módulo base esgf-query
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
esgf_mod = importlib.import_module("esgf-query")

build_files_inventory = esgf_mod.build_files_inventory
validate_files_inventory = esgf_mod.validate_files_inventory
DEFAULT_PERIOD_RANGES = getattr(esgf_mod, "DEFAULT_PERIOD_RANGES", getattr(esgf_mod, "PERIOD_RANGES", {
    "historical": (1950, 2014),
    "ssp126": (2015, 2100),
    "ssp245": (2015, 2100),
    "ssp370": (2015, 2100),
    "ssp585": (2015, 2100),
}))


def load_models_from_file(file_path):
    """
    Carga y analiza una lista de modelos desde un archivo CSV o de texto plano.

    Parameters
    ----------
    file_path : str
        Ruta al archivo con la lista de modelos.

    Returns
    -------
    pandas.DataFrame
        DataFrame con columnas ['source_id', 'variant_label'].
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"No se encontró el archivo de modelos: '{file_path}'")

    models_list = []

    # Intentar leer primero con pandas para detectar si tiene encabezados conocidos
    try:
        df_raw = pd.read_csv(file_path, header=None)
        # Si tiene 2 columnas o más
        if df_raw.shape[1] >= 2:
            first_row_c0 = str(df_raw.iloc[0, 0]).strip().lower()
            first_row_c1 = str(df_raw.iloc[0, 1]).strip().lower()

            if "source" in first_row_c0 and "variant" in first_row_c1:
                # Tiene encabezado source_id, variant_label
                df_header = pd.read_csv(file_path)
                s_col = [c for c in df_header.columns if "source" in c.lower()][0]
                v_col = [c for c in df_header.columns if "variant" in c.lower()][0]
                for _, r in df_header.iterrows():
                    s_val = str(r[s_col]).strip()
                    v_val = str(r[v_col]).strip()
                    if s_val and v_val and s_val != "nan":
                        models_list.append((s_val, v_val))
                return pd.DataFrame(models_list, columns=["source_id", "variant_label"])
    except Exception:
        pass

    # Lectura línea por línea para formatos NOMBRE.variante o NOMBRE,variante
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line_clean = line.strip()
            # Omitir líneas vacías o comentarios
            if not line_clean or line_clean.startswith("#"):
                continue

            # Omitir fila de encabezado si dice 'model' o 'modelo'
            if line_clean.lower() in ("model", "modelo", "model_variant", "source_id.variant_label"):
                continue

            # Parsear formato 'NOMBRE.variante' o 'NOMBRE,variante' o 'NOMBRE\tvariante'
            if "," in line_clean:
                parts = line_clean.split(",")
                s_val, v_val = parts[0].strip(), parts[1].strip()
            elif "\t" in line_clean:
                parts = line_clean.split("\t")
                s_val, v_val = parts[0].strip(), parts[1].strip()
            elif "." in line_clean:
                parts = line_clean.rsplit(".", 1)
                s_val, v_val = parts[0].strip(), parts[1].strip()
            else:
                print(f"[ADVERTENCIA] Formato no reconocido en la línea: '{line_clean}'. Se esperaba 'NOMBRE.variante'.")
                continue

            if s_val and v_val:
                models_list.append((s_val, v_val))

    if not models_list:
        raise ValueError(f"No se pudieron extraer modelos válidos desde '{file_path}'.")

    # Eliminar duplicados manteniendo orden
    seen = set()
    unique_models = []
    for s, v in models_list:
        if (s, v) not in seen:
            seen.add((s, v))
            unique_models.append((s, v))

    return pd.DataFrame(unique_models, columns=["source_id", "variant_label"])


def main():
    parser = argparse.ArgumentParser(
        description="Generador dinámico de manifiestos y catálogos CMIP6 para CDO & Aria2c"
    )
    parser.add_argument(
        "-i", "--input-csv",
        default="selected_models.csv",
        help="Archivo CSV o texto con la lista de modelos (por defecto: selected_models.csv)"
    )
    parser.add_argument(
        "-o", "--output-tsv",
        default="cmip6_manifest.tsv",
        help="Nombre del manifiesto TSV de salida (por defecto: cmip6_manifest.tsv)"
    )
    parser.add_argument(
        "--output-csv",
        default="cmip6_files.csv",
        help="Nombre del catálogo CSV detallado de archivos (por defecto: cmip6_files.csv)"
    )
    parser.add_argument(
        "--output-urls",
        default="cmip6_urls.txt",
        help="Nombre de la lista plana de URLs (por defecto: cmip6_urls.txt)"
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=6,
        help="Número de hilos concurrentes para consultas a ESGF (por defecto: 6)"
    )
    parser.add_argument(
        "--hist-start",
        type=int,
        default=1950,
        help="Año de inicio para historical (por defecto: 1950)"
    )
    parser.add_argument(
        "--hist-end",
        type=int,
        default=2014,
        help="Año de fin para historical (por defecto: 2014)"
    )
    parser.add_argument(
        "--ssp-start",
        type=int,
        default=2015,
        help="Año de inicio para escenarios SSP (por defecto: 2015)"
    )
    parser.add_argument(
        "--ssp-end",
        type=int,
        default=2100,
        help="Año de fin para escenarios SSP (por defecto: 2100)"
    )

    args = parser.parse_args()

    # Configurar períodos de interés
    period_ranges = {
        "historical": (args.hist_start, args.hist_end),
        "ssp126": (args.ssp_start, args.ssp_end),
        "ssp245": (args.ssp_start, args.ssp_end),
        "ssp370": (args.ssp_start, args.ssp_end),
        "ssp585": (args.ssp_start, args.ssp_end),
    }

    print("=" * 70)
    print("GENERADOR DINÁMICO DE MANIFIESTO CMIP6")
    print("=" * 70)
    print(f"Archivo de entrada de modelos : {args.input_csv}")
    print(f"Manifiesto TSV de salida      : {args.output_tsv}")
    print(f"Catálogo CSV de archivos      : {args.output_csv}")
    print(f"Lista de URLs                 : {args.output_urls}")
    print(f"Concurrencia (workers)        : {args.workers}")
    print("Períodos de interés:")
    for exp_k, r_v in period_ranges.items():
        print(f"   - {exp_k:12s}: {r_v[0]} a {r_v[1]}")
    print("=" * 70)
    print()

    # 1. Cargar modelos desde el archivo
    selected_df = load_models_from_file(args.input_csv)
    print(f"[OK] Se cargaron {len(selected_df)} modelos/realizaciones desde '{args.input_csv}':")
    for idx, row in selected_df.iterrows():
        print(f"   {idx + 1:2d}. {row['source_id']}.{row['variant_label']}")
    print()

    # 2. Consultar archivos en ESGF aplicando filtrado por período
    files_df, unresolved = build_files_inventory(
        selected_df=selected_df,
        max_workers=args.workers,
        period_ranges=period_ranges
    )

    # 3. Validar inventario
    validate_files_inventory(files_df, selected_df, unresolved, period_ranges=period_ranges)

    if files_df.empty:
        print("[ERROR] No se encontraron archivos para los modelos seleccionados.")
        sys.exit(1)

    # 4. Guardar Catálogo CSV
    files_df.to_csv(args.output_csv, index=False)
    print(f"[OK] Catálogo CSV guardado: {args.output_csv} ({len(files_df):,} archivos)")

    # 5. Guardar Manifiesto TSV para el script Bash de descarga y procesamiento
    tsv_cols = [
        "source_id", "variant_label", "experiment_id", "variable_id",
        "start_year", "end_year", "file_name", "https_url", "checksum",
        "checksum_type", "file_size_mb", "data_node"
    ]
    avail_cols = [c for c in tsv_cols if c in files_df.columns]
    files_df[avail_cols].to_csv(args.output_tsv, sep="\t", index=False)
    print(f"[OK] Manifiesto TSV guardado: {args.output_tsv}")

    # 6. Guardar lista de URLs plana
    with open(args.output_urls, "w", encoding="utf-8") as f:
        for _, row in files_df.iterrows():
            url = row.get("https_url", "")
            if url:
                f.write(f"{url}\n")
    print(f"[OK] Lista de URLs guardada: {args.output_urls}")

    print()
    print("=" * 70)
    print("MANIFIESTO GENERADO EXITOSAMENTE")
    print("=" * 70)
    print("Archivos listos para el flujo de descarga:")
    print(f"   1. {args.output_tsv} (Manifiesto estructurado TSV)")
    print(f"   2. {args.output_csv} (Catálogo detallado CSV)")
    print(f"   3. {args.output_urls} (Lista plana de URLs)")
    print("=" * 70)
    print()
    print("=" * 70)
    print("SIGUIENTE PASO RECOMENDADO")
    print("=" * 70)
    print("Para iniciar la descarga concurrente con aria2c, preprocesamiento con")
    print("CDO y transferencia automática por SSH/rsync, ejecuta en Linux:")
    print(f"   MANIFEST={args.output_tsv} ./download_preprocess_cmip6.sh")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
