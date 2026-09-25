#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMIP6 Availability Inventory & NetCDF Files Builder (Interactivo & con Caché)
============================================================================

Construye un inventario de disponibilidad de variables CMIP6 a partir
del índice ESGF-West (MetaGrid) o desde una copia local en caché, aplicando
filtrado por período de interés y verificación estricta con el catálogo GCMEval.

Flujo:
------
1. Selección de Fuente de Metadatos (Caché local vs Consulta API ESGF).
2. Resumen interactivo de parámetros de filtrado (período, experimentos, variables).
3. Construcción del inventario y verificación cruzada obligatoria con GCMEval (gcmeval/gcmeval_models.csv).
4. Exportación de resultados:
   - cmip6_daily_inventory.xlsx (Libro Excel con formato condicional y enlaces)
   - cmip6_daily_inventory.csv (Inventario tabular)
   - cmip6_complete_models.csv (Modelos 100% completos y verificados en GCMEval, sin encabezado)
   - selected_models.csv (Modelos listos para generate_manifest.py)
   - cmip6_files.csv (Catálogo detallado de archivos NetCDF)

Autor original: Will Abarca (wabarca@ambiente.gob.sv)
"""

import os
import sys
import json
import time
import re
import argparse
from urllib.parse import quote
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

try:
    from openpyxl.styles import PatternFill
    from openpyxl.utils import get_column_letter
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

# ---------------------------------------------------------------------
# Configuración general por defecto
# ---------------------------------------------------------------------

BASE_URL = "https://metagrid.esgf-west.org/proxy/search"
CACHE_FILE_DATASETS = "esgf_raw_datasets.json"
CACHE_FILE_FILES = "esgf_raw_files.json"

DEFAULT_VARIABLES = [
    "ua",      # Viento zonal
    "va",      # Viento meridional
    "ta",      # Temperatura del aire
    "hur",     # Humedad relativa
    "hus",     # Humedad específica
    "zg",      # Altura geopotencial
    "psl",     # Presión reducida al nivel del mar
    "tasmax",  # Temperatura máxima diaria del aire en superficie
    "tasmin",  # Temperatura mínima diaria del aire en superficie
    "pr",      # Precipitación diaria
]

DEFAULT_EXPERIMENTS = [
    "historical",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp585",
]

DEFAULT_PERIOD_RANGES = {
    "historical": (1950, 2014),
    "ssp126": (2015, 2100),
    "ssp245": (2015, 2100),
    "ssp370": (2015, 2100),
    "ssp585": (2015, 2100),
}

TABLE_ID = "day"
PAGE_SIZE = 1000
FILES_PAGE_SIZE = 1000
MAX_WORKERS = 6

# Ruta al catálogo de modelos de GCMEval
GCMEVAL_PATHS = [
    os.path.join("gcmeval", "gcmeval_models.csv"),
    "gcmeval_models.csv",
]


# ---------------------------------------------------------------------
# Utilidades de Red y Metadatos
# ---------------------------------------------------------------------

def first(value):
    """Devuelve el primer elemento si el valor es una lista, o el valor mismo."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def extract_file_years(file_name):
    """Extrae el año de inicio y fin desde el nombre estándar de un archivo NetCDF CMIP6."""
    m = re.search(r'_(\d{4,8})-(\d{4,8})\.nc$', str(file_name))
    if m:
        s_str, e_str = m.group(1), m.group(2)
        return int(s_str[:4]), int(e_str[:4])
    return None, None


def extract_dataset_years(doc):
    """Extrae el año de inicio y fin desde un documento Solr de tipo Dataset."""
    d_start = first(doc.get("datetime_start"))
    d_stop = first(doc.get("datetime_stop")) or first(doc.get("datetime_end"))
    s_yr, e_yr = None, None
    if d_start:
        m = re.match(r'^(\d{4})', str(d_start).strip())
        if m:
            s_yr = int(m.group(1))
    if d_stop:
        m = re.match(r'^(\d{4})', str(d_stop).strip())
        if m:
            e_yr = int(m.group(1))
    if s_yr is None or e_yr is None:
        inst = first(doc.get("instance_id")) or first(doc.get("id")) or first(doc.get("title")) or ""
        m_inst = re.search(r'_(\d{4,8})-(\d{4,8})', str(inst))
        if m_inst:
            if s_yr is None:
                s_yr = int(m_inst.group(1)[:4])
            if e_yr is None:
                e_yr = int(m_inst.group(2)[:4])
    return s_yr, e_yr


def is_dataset_in_period(doc, experiment_id, period_ranges):
    """Verifica si un dataset ESGF intersecta con el período de interés configurado."""
    req_range = period_ranges.get(experiment_id)
    if not req_range:
        return True

    s_yr, e_yr = extract_dataset_years(doc)
    if s_yr is None and e_yr is None:
        return True

    req_start, req_end = req_range
    if s_yr is not None and e_yr is not None:
        return (s_yr <= req_end and e_yr >= req_start)
    elif s_yr is not None:
        return s_yr <= req_end
    elif e_yr is not None:
        return e_yr >= req_start
    return True


def get_http_session(retries=3, backoff_factor=0.5):
    """Crea una sesión requests con pool de conexiones y reintentos automáticos."""
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def build_metagrid_url(source_id, variant_label, experiments, variables):
    """Construye una URL de búsqueda de MetaGrid para una realización específica."""
    active_facets = {
        "table_id": TABLE_ID,
        "experiment_id": experiments,
        "variable_id": variables,
        "frequency": TABLE_ID,
        "source_id": source_id,
        "variant_label": variant_label,
    }
    return (
        "https://metagrid.esgf-west.org/search?"
        f"project=CMIP6&activeFacets="
        f"{quote(json.dumps(active_facets, separators=(',', ':')))}"
    )


# ---------------------------------------------------------------------
# Manejo de GCMEval
# ---------------------------------------------------------------------

def locate_gcmeval_file():
    """Busca el archivo gcmeval_models.csv en las rutas estándar."""
    for path in GCMEVAL_PATHS:
        if os.path.exists(path):
            return path
    return None


def load_gcmeval_models(file_path=None):
    """
    Carga el conjunto de modelos evaluados en GCMEval.
    Soporta formato 'NOMBRE.variante' o 'source_id,variant_label'.
    """
    target_path = file_path or locate_gcmeval_file()
    if not target_path or not os.path.exists(target_path):
        return set(), None

    gcmeval_set = set()
    with open(target_path, "r", encoding="utf-8") as f:
        for line in f:
            l = line.strip()
            if not l or l.startswith("#"):
                continue
            if l.lower() in ("model", "modelo", "source_id,variant_label", "source_id.variant_label"):
                continue
            if "," in l:
                parts = l.split(",")
                s_id, v_lbl = parts[0].strip(), parts[1].strip()
            elif "." in l:
                parts = l.rsplit(".", 1)
                s_id, v_lbl = parts[0].strip(), parts[1].strip()
            else:
                s_id, v_lbl = l, ""
            if s_id and v_lbl:
                gcmeval_set.add(f"{s_id}|{v_lbl}")
                gcmeval_set.add(f"{s_id}.{v_lbl}")

    return gcmeval_set, target_path


# ---------------------------------------------------------------------
# Consulta y Caché de Datasets (Fase 1)
# ---------------------------------------------------------------------

def fetch_variable_experiment(variable, experiment, session=None):
    """Recupera todos los datasets asociados a una combinación variable-experimento desde ESGF Solr."""
    http = session or requests
    offset = 0
    docs_all = []
    num_found_total = 0

    while True:
        params = {
            "project": "CMIP6",
            "table_id": TABLE_ID,
            "experiment_id": experiment,
            "variable_id": variable,
            "latest": "true",
            "replica": "false",
            "type": "Dataset",
            "format": "application/solr+json",
            "limit": PAGE_SIZE,
            "offset": offset,
        }

        r = http.get(BASE_URL, params=params, timeout=120)
        r.raise_for_status()
        data = r.json()

        response = data.get("response", {})
        docs = response.get("docs", [])
        num_found_total = response.get("numFound", 0)

        if not docs:
            break

        docs_all.extend(docs)
        offset += len(docs)

        if len(docs) < PAGE_SIZE:
            break

    return docs_all, num_found_total


def download_all_raw_datasets(experiments, variables, session=None, cache_path=CACHE_FILE_DATASETS):
    """
    Descarga todos los documentos Solr de tipo Dataset para todas las combinaciones
    y los almacena localmente en un archivo JSON de caché.
    """
    print()
    print("=" * 70)
    print("DESCARGANDO METADATOS CRUDOS DESDE ESGF SOLR (METAGRID)")
    print(f"Total consultas a ejecutar: {len(experiments) * len(variables)} (Experimentos: {len(experiments)}, Variables: {len(variables)})")
    print("=" * 70)

    http_session = session or get_http_session()
    raw_data = {}
    t0 = time.time()
    total_docs = 0

    for exp in experiments:
        raw_data[exp] = {}
        for var in variables:
            docs, num_found = fetch_variable_experiment(var, exp, session=http_session)
            raw_data[exp][var] = docs
            total_docs += len(docs)
            print(f"   - {exp:12s} {var:6s} -> {len(docs):4d} datasets (reportados por ESGF: {num_found:4d})")

    elapsed = time.time() - t0
    print("-" * 70)
    print(f"[OK] Descarga de metadatos completada en {elapsed:.1f}s. Total datasets: {total_docs:,}")

    # Guardar en caché JSON
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(raw_data, f)
        print(f"[OK] Caché de metadatos guardado exitosamente: '{cache_path}'")
    except Exception as e:
        print(f"[ADVERTENCIA] No se pudo guardar archivo de caché: {e}")

    return raw_data


def load_raw_datasets_from_cache(cache_path=CACHE_FILE_DATASETS):
    """Carga los metadatos crudos desde el archivo de caché JSON."""
    if not os.path.exists(cache_path):
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"[ADVERTENCIA] Error al leer caché '{cache_path}': {e}")
        return None


def build_inventory_from_raw(raw_data, experiments, variables, period_ranges):
    """
    Procesa los metadatos crudos de datasets aplicando el filtrado por período
    de interés para construir la matriz de disponibilidad.
    """
    inventory = defaultdict(set)
    total_docs_processed = 0
    discarded_out_of_period = 0

    for exp in experiments:
        exp_data = raw_data.get(exp, {})
        for var in variables:
            docs = exp_data.get(var, [])
            total_docs_processed += len(docs)

            for doc in docs:
                if is_dataset_in_period(doc, exp, period_ranges):
                    source_id = first(doc.get("source_id"))
                    variant_label = first(doc.get("variant_label"))
                    experiment_id = first(doc.get("experiment_id"))
                    variable_id = first(doc.get("variable_id"))

                    if source_id and variant_label and experiment_id and variable_id:
                        key = (source_id, variant_label, experiment_id)
                        inventory[key].add(variable_id)
                else:
                    discarded_out_of_period += 1

    rows = []
    for key, vars_found in inventory.items():
        source_id, variant_label, experiment_id = key
        req_p = period_ranges.get(experiment_id)
        p_str = f"{req_p[0]}-{req_p[1]}" if req_p else "N/A"

        row = {
            "source_id": source_id,
            "variant_label": variant_label,
            "experiment_id": experiment_id,
            "period_range": p_str,
        }

        for var in variables:
            row[var] = var in vars_found

        row["score"] = len(vars_found)
        row["complete"] = row["score"] == len(variables)
        row["period_available"] = row["complete"]
        rows.append(row)

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(
            by=["period_available", "source_id", "variant_label", "experiment_id"],
            ascending=[False, True, True, True]
        )

    stats = {
        "total_docs_processed": total_docs_processed,
        "discarded_out_of_period": discarded_out_of_period,
        "inventory_rows": len(df),
        "unique_models": df["source_id"].nunique() if not df.empty else 0,
    }

    return df, stats


def build_summary(df, experiments, variables, gcmeval_set=None):
    """
    Consolida la disponibilidad por (source_id, variant_label) y cruza con GCMEval.
    """
    max_possible = len(variables) * len(experiments)

    if df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby(["source_id", "variant_label"])
        .agg(
            complete_experiments=("complete", "sum"),
            total_variables=("score", "sum"),
        )
        .reset_index()
    )

    summary["availability_pct"] = (100.0 * summary["total_variables"] / max_possible).round(2)
    summary["all_experiments_complete"] = summary["complete_experiments"] == len(experiments)
    summary["period_available"] = summary["all_experiments_complete"]

    # Cruce con GCMEval
    if gcmeval_set:
        summary["model_pipe"] = summary["source_id"].astype(str) + "|" + summary["variant_label"].astype(str)
        summary["model_dot"] = summary["source_id"].astype(str) + "." + summary["variant_label"].astype(str)
        summary["gcmeval"] = summary["model_pipe"].isin(gcmeval_set) | summary["model_dot"].isin(gcmeval_set)
        summary = summary.drop(columns=["model_pipe", "model_dot"])
    else:
        summary["gcmeval"] = False

    # Ordenar primero por modelos que cumplen todas las condiciones (TRUE primero) y luego alfabéticamente
    summary = summary.sort_values(
        by=["period_available", "gcmeval", "source_id", "variant_label"],
        ascending=[False, False, True, True],
    )

    return summary


# ---------------------------------------------------------------------
# Consulta de Archivos NetCDF (Fase 2)
# ---------------------------------------------------------------------

def parse_file_doc(doc, source_id, variant_label, experiment_id, variable_id):
    """Parsea un documento Solr de tipo File y determina la mejor URL y método de acceso."""
    file_name = doc.get("title") or doc.get("instance_id")
    dataset_id = doc.get("dataset_id")
    instance_id = doc.get("instance_id")
    master_id = doc.get("master_id")
    data_node = doc.get("data_node")
    file_size = doc.get("size")

    checksum_raw = doc.get("checksum")
    checksum = first(checksum_raw) if checksum_raw else None

    checksum_type_raw = doc.get("checksum_type")
    checksum_type = first(checksum_type_raw) if checksum_type_raw else None

    urls = doc.get("url") or []
    https_globus_url = None
    https_thredds_url = None
    http_thredds_url = None
    globus_native_uri = None

    for entry in urls:
        if not isinstance(entry, str):
            continue
        parts = entry.split("|")
        if len(parts) >= 3:
            link, mime, service = parts[0].strip(), parts[1].strip(), parts[2].strip()
            service_lower = service.lower()

            if "httpserver" in service_lower or service == "HTTPServer":
                if "data.globus.org" in link:
                    https_globus_url = link
                elif link.startswith("https://"):
                    https_thredds_url = link
                elif link.startswith("http://") and not http_thredds_url:
                    http_thredds_url = link
            elif "globus" in service_lower or link.startswith("globus:"):
                globus_native_uri = link

    if https_globus_url:
        selected_url = https_globus_url
        access_method = "HTTPS (Globus)"
        priority_rank = 3
    elif https_thredds_url:
        selected_url = https_thredds_url
        access_method = "HTTPS (THREDDS + Globus)" if globus_native_uri else "HTTPS (THREDDS)"
        priority_rank = 2
    elif http_thredds_url:
        selected_url = http_thredds_url
        access_method = "HTTP (THREDDS + Globus)" if globus_native_uri else "HTTP (THREDDS)"
        priority_rank = 1
    elif globus_native_uri:
        selected_url = globus_native_uri
        access_method = "Globus Native"
        priority_rank = 0
    else:
        selected_url = None
        access_method = "No URL"
        priority_rank = -1

    return {
        "source_id": source_id,
        "variant_label": variant_label,
        "experiment_id": experiment_id,
        "variable_id": variable_id,
        "file_name": file_name,
        "https_url": selected_url,
        "access_method": access_method,
        "data_node": data_node,
        "file_size_bytes": file_size,
        "checksum": checksum,
        "checksum_type": checksum_type,
        "dataset_id": dataset_id,
        "instance_id": instance_id,
        "master_id": master_id,
        "has_globus": bool(globus_native_uri or https_globus_url),
        "priority_rank": priority_rank,
    }


def fetch_files_for_combination(source_id, variant_label, experiment_id, variable_id, session=None, period_ranges=None):
    """Consulta archivos NetCDF para una combinación aplicando filtrado por período."""
    http = session or requests
    offset = 0
    docs_all = []

    params = {
        "project": "CMIP6",
        "source_id": source_id,
        "variant_label": variant_label,
        "experiment_id": experiment_id,
        "variable_id": variable_id,
        "table_id": TABLE_ID,
        "latest": "true",
        "type": "File",
        "format": "application/solr+json",
        "limit": FILES_PAGE_SIZE,
        "offset": offset,
    }

    try:
        while True:
            params["offset"] = offset
            r = http.get(BASE_URL, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()

            response = data.get("response", {})
            docs = response.get("docs", [])

            if not docs:
                break

            docs_all.extend(docs)
            offset += len(docs)

            if len(docs) < FILES_PAGE_SIZE:
                break

    except Exception as e:
        print(f"[ERROR] Fallo al consultar archivos para {source_id} {variant_label} {experiment_id} {variable_id}: {e}")
        return [], False

    if not docs_all:
        return [], True

    best_file_by_name = {}
    for doc in docs_all:
        parsed = parse_file_doc(doc, source_id, variant_label, experiment_id, variable_id)
        fname = parsed["file_name"]

        if fname not in best_file_by_name:
            best_file_by_name[fname] = parsed
        else:
            if parsed["priority_rank"] > best_file_by_name[fname]["priority_rank"]:
                best_file_by_name[fname] = parsed

    ranges = period_ranges if period_ranges is not None else DEFAULT_PERIOD_RANGES
    req_range = ranges.get(experiment_id)

    filtered_files = []
    for f in best_file_by_name.values():
        s_yr, e_yr = extract_file_years(f["file_name"])
        f["start_year"] = s_yr
        f["end_year"] = e_yr

        if req_range and s_yr is not None and e_yr is not None:
            req_start, req_end = req_range
            if s_yr <= req_end and e_yr >= req_start:
                filtered_files.append(f)
        else:
            filtered_files.append(f)

    sorted_files = sorted(filtered_files, key=lambda x: x["file_name"] or "")
    return sorted_files, True


def build_files_inventory(selected_df, experiments=DEFAULT_EXPERIMENTS, variables=DEFAULT_VARIABLES,
                          max_workers=MAX_WORKERS, session=None, period_ranges=DEFAULT_PERIOD_RANGES):
    """Consulta detallada de archivos NetCDF para las realizaciones seleccionadas."""
    print()
    print("=" * 70)
    print("FASE 2: CONSULTA DETALLADA DE ARCHIVOS NETCDF (FILTRADO POR PERÍODO)")
    print(f"Realizaciones seleccionadas a procesar: {len(selected_df)}")
    print(f"Total combinaciones dataset teóricas: {len(selected_df) * len(experiments) * len(variables):,}")
    print("=" * 70)

    http_session = session or get_http_session()

    tasks = []
    for _, row in selected_df.iterrows():
        s_id = row["source_id"]
        v_lbl = row["variant_label"]
        for exp in experiments:
            for var in variables:
                tasks.append((s_id, v_lbl, exp, var))

    total_tasks = len(tasks)
    all_files_records = []
    unresolved_combinations = []
    completed_tasks = 0
    t0 = time.time()

    def worker_func(task_args):
        src, var_lbl, exp, var = task_args
        files, success = fetch_files_for_combination(
            src, var_lbl, exp, var, session=http_session, period_ranges=period_ranges
        )
        return task_args, files, success

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(worker_func, t): t for t in tasks}

        for future in as_completed(futures):
            task_args, files, success = future.result()
            completed_tasks += 1

            src, var_lbl, exp, var = task_args

            if not success or (not files):
                unresolved_combinations.append({
                    "source_id": src,
                    "variant_label": var_lbl,
                    "experiment_id": exp,
                    "variable_id": var,
                    "reason": "Error en consulta" if not success else "Sin archivos en el período de interés",
                })
            else:
                all_files_records.extend(files)

            if completed_tasks % 25 == 0 or completed_tasks == total_tasks:
                elapsed = time.time() - t0
                pct = (completed_tasks / total_tasks) * 100.0
                rate = completed_tasks / elapsed if elapsed > 0 else 0
                print(
                    f"Progreso archivos: {completed_tasks:4d}/{total_tasks:4d} ({pct:5.1f}%) "
                    f"| Archivos acumulados: {len(all_files_records):6d} "
                    f"| Tasa: {rate:.1f} req/s"
                )

    if all_files_records:
        files_df = pd.DataFrame(all_files_records)

        if "file_size_bytes" in files_df.columns:
            files_df["file_size_mb"] = (
                files_df["file_size_bytes"].fillna(0) / (1024.0 * 1024.0)
            ).round(2)
        else:
            files_df["file_size_mb"] = 0.0

        files_df["file_link"] = "Abrir"

        column_order = [
            "source_id", "variant_label", "experiment_id", "variable_id",
            "start_year", "end_year", "file_name", "file_link", "https_url",
            "access_method", "data_node", "file_size_mb", "file_size_bytes",
            "checksum", "checksum_type", "dataset_id", "instance_id", "master_id",
        ]
        existing_cols = [c for c in column_order if c in files_df.columns]
        extra_cols = [c for c in files_df.columns if c not in column_order and c not in ("priority_rank", "has_globus")]
        files_df = files_df[existing_cols + extra_cols]
        files_df = files_df.sort_values(
            ["source_id", "variant_label", "experiment_id", "variable_id", "file_name"]
        )
    else:
        files_df = pd.DataFrame()

    return files_df, unresolved_combinations


def validate_files_inventory(files_df, selected_df, unresolved_combinations, experiments=DEFAULT_EXPERIMENTS,
                             variables=DEFAULT_VARIABLES, period_ranges=DEFAULT_PERIOD_RANGES):
    """Valida y reporta estadísticas clave de los archivos extraídos."""
    total_expected_datasets = len(selected_df) * len(experiments) * len(variables)
    total_files = len(files_df)

    if not files_df.empty:
        https_count = files_df["https_url"].dropna().str.startswith("https://").sum()
        http_count = files_df["https_url"].dropna().str.startswith("http://").sum()
        globus_count = files_df["access_method"].str.contains("Globus", case=False, na=False).sum()
        unique_urls = files_df["https_url"].dropna().nunique()
        total_size_gb = (files_df["file_size_bytes"].sum() / (1024.0 ** 3))
    else:
        https_count = 0
        http_count = 0
        globus_count = 0
        unique_urls = 0
        total_size_gb = 0.0

    print()
    print("=" * 70)
    print("VALIDACIÓN Y ESTADÍSTICAS DE ARCHIVOS NETCDF")
    print("=" * 70)
    print(f"Realizaciones seleccionadas procesadas : {len(selected_df):,}")
    print(f"Combinaciones dataset esperadas        : {total_expected_datasets:,}")
    print(f"Combinaciones no resueltas en período  : {len(unresolved_combinations):,}")
    print(f"Total archivos NetCDF en período       : {total_files:,}")
    print(f"Archivos con URL HTTPS directa         : {https_count:,}")
    print(f"Archivos con URL HTTP estándar         : {http_count:,}")
    print(f"Archivos con soporte Globus            : {globus_count:,}")
    print(f"URLs directas únicas                   : {unique_urls:,}")
    print(f"Volumen total catalogado               : {total_size_gb:,.2f} GB")
    print("=" * 70)

    if not files_df.empty and "start_year" in files_df.columns:
        combos = files_df.groupby(["source_id", "variant_label", "experiment_id", "variable_id"]).agg(
            min_yr=("start_year", "min"),
            max_yr=("end_year", "max"),
            file_count=("file_name", "count")
        ).reset_index()

        incomplete_temporal = []
        for _, row in combos.iterrows():
            exp = row["experiment_id"]
            req_r = period_ranges.get(exp)
            if req_r:
                req_s, req_e = req_r
                if row["min_yr"] > req_s or row["max_yr"] < req_e:
                    incomplete_temporal.append({
                        "source_id": row["source_id"],
                        "variant_label": row["variant_label"],
                        "experiment_id": exp,
                        "variable_id": row["variable_id"],
                        "covered_range": f"{row['min_yr']}-{row['max_yr']}",
                        "required_range": f"{req_s}-{req_e}",
                    })

        if incomplete_temporal:
            print("\n[ADVERTENCIA] Datasets con cobertura temporal PARCIAL para el periodo requerido:")
            for inc in incomplete_temporal:
                print(f"   [PARCIAL] {inc['source_id']} ({inc['variant_label']}) {inc['experiment_id']} {inc['variable_id']}: Cubre {inc['covered_range']} (Requerido: {inc['required_range']})")
        else:
            print("\n[OK] Todos los datasets catalogados cubren el 100% de los periodos de interes configurados.")

    if unresolved_combinations:
        print()
        print("Combinaciones sin archivos disponibles en el periodo de interes:")
        for unres in unresolved_combinations[:15]:
            print(f"  [SIN DATOS] {unres['source_id']} ({unres['variant_label']}) {unres['experiment_id']} {unres['variable_id']}: {unres['reason']}")
        if len(unresolved_combinations) > 15:
            print(f"  ... y {len(unresolved_combinations) - 15} mas.")
    print("=" * 70)
    print()


# ---------------------------------------------------------------------
# Exportación Excel y CSV
# ---------------------------------------------------------------------

def export_results(df, summary, selected, files_df, variables=DEFAULT_VARIABLES,
                   csv_inventory="cmip6_daily_inventory.csv",
                   csv_files="cmip6_files.csv",
                   csv_complete_models="cmip6_complete_models.csv",
                   csv_selected_models="selected_models.csv",
                   xlsx_file="cmip6_daily_inventory.xlsx"):
    """Exporta inventarios, resúmenes y catálogos en CSV y Excel estilizado."""
    df.to_csv(csv_inventory, index=False)
    print(f"[OK] Inventario CSV guardado: {csv_inventory}")

    if not files_df.empty:
        files_df.to_csv(csv_files, index=False)
        print(f"[OK] Catálogo de archivos CSV guardado: {csv_files}")

    # Exportar CSV con modelos 100% completos y verificados con GCMEval (sin encabezado)
    if not selected.empty:
        selected_export = selected.copy()
        selected_export["model"] = selected_export["source_id"].astype(str) + "." + selected_export["variant_label"].astype(str)
        selected_export = selected_export.sort_values("model")

        # Guardar en cmip6_complete_models.csv
        selected_export[["model"]].to_csv(csv_complete_models, index=False, header=False)
        print(f"[OK] Modelos completos y en GCMEval ({len(selected_export)} modelos, sin encabezado): {csv_complete_models}")

        # Guardar copia en directorio gcmeval/
        gcmeval_dir = os.path.dirname(locate_gcmeval_file() or "gcmeval") or "gcmeval"
        if os.path.exists(gcmeval_dir):
            gcmeval_target = os.path.join(gcmeval_dir, os.path.basename(csv_complete_models))
            selected_export[["model"]].to_csv(gcmeval_target, index=False, header=False)
            print(f"[OK] Copia guardada en subdirectorio gcmeval: {gcmeval_target}")

        # Guardar también en selected_models.csv para uso directo en generate_manifest.py
        selected_export[["model"]].to_csv(csv_selected_models, index=False, header=False)
        print(f"[OK] Lista para generador de manifiestos guardada: {csv_selected_models}")

    if not OPENPYXL_AVAILABLE:
        print("[AVISO] openpyxl no está instalado; se exportará Excel básico sin formato.")
        try:
            with pd.ExcelWriter(xlsx_file) as writer:
                df.to_excel(writer, sheet_name="inventory", index=False)
                summary.to_excel(writer, sheet_name="summary", index=False)
                selected.to_excel(writer, sheet_name="selected", index=False)
                if not files_df.empty:
                    files_df.to_excel(writer, sheet_name="files", index=False)
            print(f"[OK] Libro Excel guardado: {xlsx_file}")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar Excel: {e}")
        return

    try:
        with pd.ExcelWriter(xlsx_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="inventory", index=False)
            summary.to_excel(writer, sheet_name="summary", index=False)
            selected.to_excel(writer, sheet_name="selected", index=False)

            if not files_df.empty:
                files_df.to_excel(writer, sheet_name="files", index=False)

            green_fill = PatternFill(fill_type="solid", start_color="C6EFCE", end_color="C6EFCE")
            red_fill = PatternFill(fill_type="solid", start_color="FFC7CE", end_color="FFC7CE")

            # Formato en 'inventory'
            ws_inventory = writer.sheets["inventory"]
            var_cols = [i for i, cell in enumerate(ws_inventory[1], start=1) if cell.value in variables]
            comp_cols = [i for i, cell in enumerate(ws_inventory[1], start=1) if cell.value in ("complete", "period_available")]

            for col_num in var_cols + comp_cols:
                for row in range(2, ws_inventory.max_row + 1):
                    cell = ws_inventory.cell(row=row, column=col_num)
                    if cell.value is True:
                        cell.fill = green_fill
                    elif cell.value is False:
                        cell.fill = red_fill

            # Formato en 'summary'
            if "summary" in writer.sheets:
                ws_summary = writer.sheets["summary"]
                bool_sum_cols = [
                    i for i, cell in enumerate(ws_summary[1], start=1)
                    if cell.value in ("all_experiments_complete", "period_available", "gcmeval")
                ]
                for col_num in bool_sum_cols:
                    for row in range(2, ws_summary.max_row + 1):
                        cell = ws_summary.cell(row=row, column=col_num)
                        if cell.value is True:
                            cell.fill = green_fill
                        elif cell.value is False:
                            cell.fill = red_fill

            # Hipervínculos y formato en 'selected'
            ws_selected = writer.sheets["selected"]
            meta_col, url_col, gcm_col = None, None, None

            for col_num, cell in enumerate(ws_selected[1], start=1):
                if cell.value == "metagrid":
                    meta_col = col_num
                elif cell.value == "dataset_url":
                    url_col = col_num
                elif cell.value == "gcmeval":
                    gcm_col = col_num

            if meta_col and url_col:
                for row in range(2, ws_selected.max_row + 1):
                    link_cell = ws_selected.cell(row=row, column=meta_col)
                    url_cell = ws_selected.cell(row=row, column=url_col)
                    if url_cell.value:
                        link_cell.hyperlink = str(url_cell.value)
                        link_cell.style = "Hyperlink"
                ws_selected.column_dimensions[get_column_letter(url_col)].hidden = True

            if gcm_col:
                for row in range(2, ws_selected.max_row + 1):
                    cell = ws_selected.cell(row=row, column=gcm_col)
                    if cell.value is True:
                        cell.fill = green_fill
                    elif cell.value is False:
                        cell.fill = red_fill

            # Hipervínculos en 'files'
            if not files_df.empty and "files" in writer.sheets:
                ws_files = writer.sheets["files"]
                f_link_col = None
                f_url_col = None

                for col_num, cell in enumerate(ws_files[1], start=1):
                    if cell.value == "file_link":
                        f_link_col = col_num
                    elif cell.value == "https_url":
                        f_url_col = col_num

                if f_link_col and f_url_col:
                    for row in range(2, ws_files.max_row + 1):
                        link_cell = ws_files.cell(row=row, column=f_link_col)
                        url_cell = ws_files.cell(row=row, column=f_url_col)
                        if url_cell.value and str(url_cell.value).startswith(("http://", "https://")):
                            link_cell.hyperlink = str(url_cell.value)
                            link_cell.style = "Hyperlink"

                    ws_files.column_dimensions[get_column_letter(f_url_col)].hidden = True

        print(f"[OK] Libro Excel guardado exitosamente: {xlsx_file}")
    except PermissionError:
        alt_xlsx = f"cmip6_daily_inventory_{int(time.time())}.xlsx"
        print(f"[ADVERTENCIA] No se pudo escribir '{xlsx_file}' (abierto en Excel). Guardando en '{alt_xlsx}'...")
        export_results(df, summary, selected, files_df, variables, csv_inventory, csv_files, csv_complete_models, csv_selected_models, alt_xlsx)


# ---------------------------------------------------------------------
# Menú y Flujo Interactivo en Consola
# ---------------------------------------------------------------------

def prompt_choice(prompt_text, default_val="1", is_interactive=True):
    """Solicita una opción al usuario si la consola es interactiva, o retorna el valor por defecto."""
    if not is_interactive or not sys.stdin.isatty():
        return default_val
    try:
        ans = input(prompt_text).strip()
        return ans if ans else default_val
    except (EOFError, KeyboardInterrupt):
        print()
        return default_val


def interactive_config_wizard(is_interactive=True):
    """
    Asistente interactivo en consola para seleccionar la fuente de datos
    y verificar/personalizar los parámetros de filtrado y períodos.
    """
    print()
    print("=" * 70)
    print("  INVENTARIO DE DISPONIBILIDAD CMIP6 (ESGF METAGRID & GCMEVAL)  ")
    print("=" * 70)
    print()

    # 1. Comprobación de Caché Local
    cache_exists = os.path.exists(CACHE_FILE_DATASETS)
    use_cache = False

    if cache_exists:
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(CACHE_FILE_DATASETS)))
        size_mb = os.path.getsize(CACHE_FILE_DATASETS) / (1024.0 * 1024.0)
        print("1. FUENTE DE METADATOS ESGF")
        print("-" * 70)
        print(f"Se encontró un archivo de caché local: '{CACHE_FILE_DATASETS}' ({size_mb:.2f} MB, guardado el {mtime})")
        print("   [1] Usar metadatos locales en caché (Rápido, sin conexión a internet) [POR DEFECTO]")
        print("   [2] Realizar nueva consulta a la API de ESGF MetaGrid (Descargar y actualizar caché)")
        ans = prompt_choice("Selecciona una opción [1/2] (Enter = 1): ", default_val="1", is_interactive=is_interactive)
        use_cache = (ans == "1")
    else:
        print("1. FUENTE DE METADATOS ESGF")
        print("-" * 70)
        print("No se encontró caché local. Se consultará la API de ESGF MetaGrid y se guardará una copia local.")
        use_cache = False

    print()

    # 2. Resumen y Confirmación de Parámetros
    period_ranges = dict(DEFAULT_PERIOD_RANGES)
    experiments = list(DEFAULT_EXPERIMENTS)
    variables = list(DEFAULT_VARIABLES)

    gcmeval_file = locate_gcmeval_file()

    print("2. RESUMEN DE PARÁMETROS DE FILTRADO")
    print("-" * 70)
    print(f"• Frecuencia / Tabla   : {TABLE_ID}")
    print(f"• Variables ({len(variables):2d})        : {', '.join(variables)}")
    print(f"• Experimentos ({len(experiments):2d})     : {', '.join(experiments)}")
    print("• Períodos de Interés  :")
    for exp_k, r_v in period_ranges.items():
        print(f"     - {exp_k:12s}: {r_v[0]} a {r_v[1]}")
    if gcmeval_file:
        print(f"• Catálogo GCMEval     : '{gcmeval_file}' [DETECTADO Y ACTIVO]")
    else:
        print("• Catálogo GCMEval     : [NO ENCONTRADO en gcmeval/gcmeval_models.csv]")

    print("-" * 70)
    print("   [1] Continuar con estos parámetros [POR DEFECTO]")
    print("   [2] Personalizar años de los períodos de interés")
    print("   [3] Personalizar lista de experimentos y variables")
    ans_p = prompt_choice("Selecciona una opción [1/2/3] (Enter = 1): ", default_val="1", is_interactive=is_interactive)

    if ans_p == "2":
        print()
        print("--- Personalización de Períodos de Interés ---")
        h_start = prompt_choice(f"Año inicio historical [{period_ranges['historical'][0]}]: ", str(period_ranges['historical'][0]), is_interactive)
        h_end = prompt_choice(f"Año fin historical [{period_ranges['historical'][1]}]: ", str(period_ranges['historical'][1]), is_interactive)
        period_ranges["historical"] = (int(h_start), int(h_end))

        s_start = prompt_choice(f"Año inicio escenarios SSP [{period_ranges['ssp126'][0]}]: ", str(period_ranges['ssp126'][0]), is_interactive)
        s_end = prompt_choice(f"Año fin escenarios SSP [{period_ranges['ssp126'][1]}]: ", str(period_ranges['ssp126'][1]), is_interactive)
        for exp in ["ssp126", "ssp245", "ssp370", "ssp585"]:
            period_ranges[exp] = (int(s_start), int(s_end))

        print(f"[OK] Períodos actualizados: historical={period_ranges['historical']}, SSPs=({s_start}, {s_end})")

    elif ans_p == "3":
        print()
        print("--- Personalización de Experimentos y Variables ---")
        exp_input = prompt_choice(f"Experimentos separados por coma [{','.join(experiments)}]: ", ",".join(experiments), is_interactive)
        experiments = [e.strip() for e in exp_input.split(",") if e.strip()]

        var_input = prompt_choice(f"Variables separadas por coma [{','.join(variables)}]: ", ",".join(variables), is_interactive)
        variables = [v.strip() for v in var_input.split(",") if v.strip()]
        print(f"[OK] Experimentos: {experiments}")
        print(f"[OK] Variables: {variables}")

    print()
    return use_cache, period_ranges, experiments, variables, gcmeval_file


# ---------------------------------------------------------------------
# Función Principal
# ---------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CMIP6 Availability Inventory & NetCDF Builder")
    parser.add_argument("--batch", "--no-interactive", action="store_true", help="Ejecutar en modo no interactivo con valores por defecto")
    parser.add_argument("--use-cache", action="store_true", help="Forzar el uso de la caché local")
    parser.add_argument("--refresh-cache", action="store_true", help="Forzar la recarga desde la API de ESGF")
    parser.add_argument("--skip-files", action="store_true", help="Omitir la Fase 2 (consulta detallada de archivos NetCDF)")
    args = parser.parse_args()

    is_interactive = not args.batch

    # 1. Asistente interactivo
    if args.refresh_cache:
        use_cache = False
        period_ranges = dict(DEFAULT_PERIOD_RANGES)
        experiments = list(DEFAULT_EXPERIMENTS)
        variables = list(DEFAULT_VARIABLES)
        gcmeval_file = locate_gcmeval_file()
    elif args.use_cache:
        use_cache = True
        period_ranges = dict(DEFAULT_PERIOD_RANGES)
        experiments = list(DEFAULT_EXPERIMENTS)
        variables = list(DEFAULT_VARIABLES)
        gcmeval_file = locate_gcmeval_file()
    else:
        use_cache, period_ranges, experiments, variables, gcmeval_file = interactive_config_wizard(is_interactive=is_interactive)

    session = get_http_session()

    # 2. Cargar o descargar metadatos crudos de datasets
    raw_data = None
    if use_cache:
        print(f"Cargando metadatos crudos desde caché '{CACHE_FILE_DATASETS}'...")
        raw_data = load_raw_datasets_from_cache(CACHE_FILE_DATASETS)
        if not raw_data:
            print("[AVISO] No se pudo cargar la caché. Procediendo a descargar desde ESGF...")
            raw_data = download_all_raw_datasets(experiments, variables, session=session)
    else:
        raw_data = download_all_raw_datasets(experiments, variables, session=session)

    # 3. Construir Inventario filtrado por período
    print()
    print("=" * 70)
    print("PROCESANDO MATRIZ DE DISPONIBILIDAD CON FILTRADO POR PERÍODO")
    print("=" * 70)
    df, stats = build_inventory_from_raw(raw_data, experiments, variables, period_ranges)
    print(f"Documentos Solr evaluados    : {stats['total_docs_processed']:,}")
    print(f"Datasets fuera de período    : {stats['discarded_out_of_period']:,}")
    print(f"Combinaciones válidas        : {stats['inventory_rows']:,}")
    print(f"Modelos únicos identificados : {stats['unique_models']:,}")
    print("=" * 70)

    # 4. Cruce y Validación con GCMEval
    gcmeval_set, gcmeval_path = load_gcmeval_models(gcmeval_file)
    summary = build_summary(df, experiments, variables, gcmeval_set=gcmeval_set)

    # 5. Filtrar realizaciones completas (100% variables y experimentos en período Y verificadas en GCMEval)
    all_complete = summary[summary["all_experiments_complete"] == True]
    gcmeval_complete = summary[(summary["all_experiments_complete"] == True) & (summary["gcmeval"] == True)].copy()

    # Si hay catálogo GCMEval, se seleccionan estrictamente los modelos que están en GCMEval
    if gcmeval_set:
        selected = gcmeval_complete.copy()
    else:
        selected = all_complete.copy()

    if not selected.empty:
        selected["dataset_url"] = selected.apply(
            lambda row: build_metagrid_url(row["source_id"], row["variant_label"], experiments, variables),
            axis=1,
        )
        selected["metagrid"] = "Abrir"

    print()
    print("=" * 70)
    print("FLUJO DE FILTRADO Y DISPONIBILIDAD (ESGF METAGRID -> GCMEVAL)")
    print("=" * 70)
    n_esgf_models = stats['unique_models']
    n_esgf_realizations = len(summary)
    n_complete_models = all_complete['source_id'].nunique() if not all_complete.empty else 0
    n_complete_realizations = len(all_complete)
    n_gcmeval_catalog = len([x for x in gcmeval_set if "." in x]) if gcmeval_set else 0
    n_selected_models = selected['source_id'].nunique() if not selected.empty else 0
    n_selected_realizations = len(selected)

    print(f"1. UNIVERSO ESGF / METAGRID:")
    print(f"   • Familias de modelos detectadas             : {n_esgf_models:,}")
    print(f"   • Realizaciones totales evaluadas            : {n_esgf_realizations:,}")
    print()
    print(f"2. CRITERIO DE DISPONIBILIDAD TÉCNICA ESGF (10 vars × 5 exps en período):")
    print(f"   • Familias con al menos 1 corrida completa   : {n_complete_models:,}")
    print(f"   • Realizaciones 100% completas en período    : {n_complete_realizations:,}")
    print()
    print(f"3. SUB-CONJUNTO VALIDADO EN GCMEVAL ('{os.path.basename(gcmeval_path or 'gcmeval_models.csv')}'):")
    print(f"   • Universo objetivo definido en GCMEval      : {n_gcmeval_catalog:,} realizaciones")
    print(f"   • Familias seleccionadas (ESGF + GCMEval)    : {n_selected_models:,}")
    print(f"   • Realizaciones seleccionadas finales        : {n_selected_realizations:,} [100% COMPLETAS Y EN GCMEVAL]")
    print("=" * 70)

    if not selected.empty:
        print("\nModelos Seleccionados (100% completos en período y en GCMEval):")
        for idx, (_, r) in enumerate(selected.iterrows(), start=1):
            print(f"   {idx:2d}. {r['source_id']}.{r['variant_label']} (GCMEval: {r['gcmeval']})")
    print()

    # 6. Fase 2: Consulta detallada de archivos NetCDF (opcional o automática)
    files_df = pd.DataFrame()
    unresolved = []

    if not args.skip_files and not selected.empty:
        files_df, unresolved = build_files_inventory(
            selected_df=selected,
            experiments=experiments,
            variables=variables,
            max_workers=MAX_WORKERS,
            session=session,
            period_ranges=period_ranges,
        )
        validate_files_inventory(files_df, selected, unresolved, experiments, variables, period_ranges)

    # 7. Exportación de Resultados
    print()
    print("=" * 70)
    print("EXPORTANDO RESULTADOS")
    print("=" * 70)
    export_results(
        df=df,
        summary=summary,
        selected=selected,
        files_df=files_df,
        variables=variables,
        csv_inventory="cmip6_daily_inventory.csv",
        csv_files="cmip6_files.csv",
        csv_complete_models="cmip6_complete_models.csv",
        csv_selected_models="selected_models.csv",
        xlsx_file="cmip6_daily_inventory.xlsx",
    )

    print()
    print("=" * 70)
    print("INVENTARIO ESGF Y CRUCE CON GCMEVAL COMPLETADO")
    print("=" * 70)
    print("Archivos generados:")
    print("   1. cmip6_daily_inventory.xlsx (Inventario Excel)")
    print("   2. cmip6_complete_models.csv  (36 modelos candidatos completos)")
    print("   3. cmip6_files.csv            (Catálogo general de archivos NetCDF)")
    print("=" * 70)
    print()
    print("=" * 70)
    print("SIGUIENTE PASO RECOMENDADO")
    print("=" * 70)
    print("Para evaluar el desempeño climatológico y seleccionar los 10 mejores")
    print("modelos para Centroamérica con GCMEval, ejecuta:")
    print("   python run_evaluation.py")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
