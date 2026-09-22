#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generador del catálogo y manifiesto para los 10 modelos CMIP6 100% completos
=============================================================================
Modelos incluidos:
  1. NorESM2-MM   (r1i1p1f1)
  2. EC-Earth3    (r4i1p1f1)
  3. UKESM1-0-LL  (r1i1p1f2)
  4. MPI-ESM1-2-LR (r5i1p1f1)
  5. TaiESM1      (r1i1p1f1)
  6. MRI-ESM2-0   (r1i1p1f1)
  7. ACCESS-CM2   (r1i1p1f1)
  8. IPSL-CM6A-LR (r2i1p1f1)
  9. INM-CM4-8    (r1i1p1f1)
  10. KACE-1-0-G  (r1i1p1f1)

10 variables: ua, va, ta, hur, hus, zg, psl, tasmax, tasmin, pr
5 experimentos: historical, ssp126, ssp245, ssp370, ssp585
Total combinaciones teóricas: 500 datasets
"""

import os
import sys
import importlib
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
esgf_mod = importlib.import_module("esgf-query")

build_files_inventory = esgf_mod.build_files_inventory
validate_files_inventory = esgf_mod.validate_files_inventory

TARGET_10_MODELS = [
    ("NorESM2-MM", "r1i1p1f1"),
    ("EC-Earth3", "r4i1p1f1"),
    ("UKESM1-0-LL", "r1i1p1f2"),
    ("MPI-ESM1-2-LR", "r5i1p1f1"),
    ("TaiESM1", "r1i1p1f1"),
    ("MRI-ESM2-0", "r1i1p1f1"),
    ("ACCESS-CM2", "r1i1p1f1"),
    ("IPSL-CM6A-LR", "r2i1p1f1"),
    ("INM-CM4-8", "r1i1p1f1"),
    ("KACE-1-0-G", "r1i1p1f1"),
]


def main():
    print("=" * 70)
    print("GENERANDO CATÁLOGO Y MANIFIESTO PARA LOS 10 MODELOS CMIP6 (10 VARIABLES)")
    print("=" * 70)

    selected_df = pd.DataFrame([
        {"source_id": s, "variant_label": v} for s, v in TARGET_10_MODELS
    ])

    files_df, unresolved = build_files_inventory(selected_df, max_workers=6)
    validate_files_inventory(files_df, selected_df, unresolved)

    # 1. Guardar CSV completo de 10 modelos
    csv_out = "cmip6_files_10_models.csv"
    files_df.to_csv(csv_out, index=False)
    print(f"[OK] CSV de 10 modelos guardado: {csv_out}")

    # 2. Guardar TSV para el shell script de descarga y procesamiento CDO
    tsv_out = "cmip6_manifest_10_models.tsv"
    tsv_cols = [
        "source_id", "variant_label", "experiment_id", "variable_id",
        "file_name", "https_url", "checksum", "checksum_type", "file_size_mb", "data_node"
    ]
    avail_cols = [c for c in tsv_cols if c in files_df.columns]
    files_df[avail_cols].to_csv(tsv_out, sep="\t", index=False)
    print(f"[OK] Manifiesto TSV para Shell script guardado: {tsv_out}")

    # 3. Guardar lista de URLs plana
    txt_out = "cmip6_urls_10_models.txt"
    with open(txt_out, "w", encoding="utf-8") as f:
        for _, row in files_df.iterrows():
            url = row.get("https_url", "")
            if url:
                f.write(f"{url}\n")
    print(f"[OK] Lista de URLs guardada: {txt_out}")


if __name__ == "__main__":
    main()
