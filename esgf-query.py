#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CMIP6 Availability Inventory & NetCDF Files Builder
===================================================

Construye un inventario de disponibilidad de variables CMIP6 a partir
del índice ESGF-West (MetaGrid) y extrae las URLs HTTPS directas de los
archivos NetCDF correspondientes a las realizaciones seleccionadas,
dando prioridad a los nodos con acceso Globus.

El flujo se divide en dos fases:

Fase 1: Inventario y Selección
------------------------------
1. Consulta automática de datasets en el índice ESGF mediante la API Solr (/proxy/search, type=Dataset).
2. Evaluación de disponibilidad para cada terna:
       source_id, variant_label, experiment_id
3. Resumen y consolidación por realización:
       source_id, variant_label
4. Comparación con el catálogo de modelos evaluados en GCMEval (gcmeval_models.csv).
5. Selección de realizaciones completas (todas las variables en todos los experimentos).

Fase 2: Extracción de URLs y Archivos NetCDF
--------------------------------------------
6. Para cada realización seleccionada, consulta a nivel de archivo (type=File)
   para cada combinación de experimento y variable requerida.
7. Extracción de metadatos de archivo: nombre, URLs directas HTTPS, dataset_id,
   instance_id, master_id, data_node, tamaño, checksum y método de acceso.
8. Resolución inteligente de réplicas priorizando:
       - URLs HTTPS de Globus (*.data.globus.org o nodos con soporte Globus)
       - URLs HTTPS seguras de THREDDS (https://...)
       - URLs HTTP estándar (http://...)
9. Validación estadística y exportación estructurada.

Salidas
-------
cmip6_daily_inventory.csv : Inventario de disponibilidad por modelo-realización-experimento.
cmip6_files.csv           : Listado detallado de archivos NetCDF con URLs directas.
cmip6_daily_inventory.xlsx: Libro Excel con 4 hojas:
    - 'inventory': Disponibilidad detallada por experimento con formato condicional.
    - 'summary'  : Resumen consolidado por realización.
    - 'selected' : Realizaciones completas con enlaces directos a MetaGrid.
    - 'files'    : Catálogo de archivos NetCDF con enlaces directos clicables de descarga.

Autor original: Will Abarca (wabarca@ambiente.gob.sv)
"""

import os
import sys
import json
import time
import re
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
# Configuración general
# ---------------------------------------------------------------------

# Endpoint utilizado por MetaGrid para consultar el índice ESGF Solr
BASE_URL = "https://metagrid.esgf-west.org/proxy/search"

# Variables atmosféricas y de superficie de interés
VARIABLES = [
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

# Experimentos CMIP6 considerados
EXPERIMENTS = [
    "historical",
    "ssp126",
    "ssp245",
    "ssp370",
    "ssp585",
]

# Periodos de Interés Configurables por Experimento (Start Year, End Year)
# Pueden modificarse según los requerimientos del proyecto
PERIOD_RANGES = {
    "historical": (1950, 2014),
    "ssp126": (2015, 2100),
    "ssp245": (2015, 2100),
    "ssp370": (2015, 2100),
    "ssp585": (2015, 2100),
}

# Frecuencia temporal requerida
TABLE_ID = "day"

# Tamaño de página para consultas a ESGF Solr
PAGE_SIZE = 1000
FILES_PAGE_SIZE = 1000

# Concurrencia para consultas de archivos (hilos de red)
MAX_WORKERS = 6


def extract_file_years(file_name):
    """
    Extrae el año de inicio y fin desde el nombre estándar de un archivo NetCDF CMIP6.
    Ejemplos:
        hur_day_ACCESS-CM2_historical_r1i1p1f1_gn_19500101-19541231.nc -> (1950, 1954)
        pr_day_ACCESS-CM2_ssp126_r1i1p1f1_gn_22510101-23001231.nc -> (2251, 2300)
    """
    m = re.search(r'_(\d{4,8})-(\d{4,8})\.nc$', str(file_name))
    if m:
        s_str, e_str = m.group(1), m.group(2)
        return int(s_str[:4]), int(e_str[:4])
    return None, None


def extract_dataset_years(doc):
    """
    Extrae el año de inicio y fin desde un documento Solr de tipo Dataset.
    Intenta leer datetime_start, datetime_stop / datetime_end o campos de texto.
    """
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


def is_dataset_in_period(doc, experiment_id, period_ranges=None):
    """
    Verifica si un dataset ESGF intersecta con el período de interés configurado
    para el experimento dado.
    """
    ranges = period_ranges if period_ranges is not None else PERIOD_RANGES
    req_range = ranges.get(experiment_id)
    if not req_range:
        return True

    s_yr, e_yr = extract_dataset_years(doc)
    if s_yr is None and e_yr is None:
        # Si ESGF no proporciona metadatos temporales a nivel de dataset, no descartar
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
    """
    Crea una sesión requests con pool de conexiones y reintentos automáticos
    para robustez frente a microcortes o sobrecargas en nodos ESGF.

    Parameters
    ----------
    retries : int
        Número máximo de reintentos para fallos temporales.
    backoff_factor : float
        Factor de espera exponencial entre reintentos.

    Returns
    -------
    requests.Session
    """
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


def build_metagrid_url(source_id, variant_label):
    """
    Construye una URL de búsqueda de MetaGrid para una realización específica.

    Parameters
    ----------
    source_id : str
        Nombre del modelo CMIP6.
    variant_label : str
        Identificador de la realización.

    Returns
    -------
    str
        URL completa de MetaGrid con facetas activas codificadas.
    """
    active_facets = {
        "table_id": TABLE_ID,
        "experiment_id": EXPERIMENTS,
        "variable_id": VARIABLES,
        "frequency": TABLE_ID,
        "source_id": source_id,
        "variant_label": variant_label,
    }

    return (
        "https://metagrid.esgf-west.org/search?"
        f"project=CMIP6&activeFacets="
        f"{quote(json.dumps(active_facets, separators=(',', ':')))}"
    )


def first(value):
    """
    Devuelve el primer elemento si el valor es una lista, o el valor mismo.

    Parameters
    ----------
    value : object

    Returns
    -------
    object
    """
    if isinstance(value, list):
        return value[0] if value else None
    return value


# ---------------------------------------------------------------------
# FASE 1: Inventario de Datasets
# ---------------------------------------------------------------------

def fetch_variable_experiment(variable, experiment, session=None):
    """
    Recupera todos los datasets asociados a una combinación variable-experimento
    mediante consultas paginadas al índice ESGF Solr (/proxy/search).

    Parameters
    ----------
    variable : str
        Identificador de variable (ej. 'ua').
    experiment : str
        Identificador de experimento (ej. 'historical').
    session : requests.Session, optional
        Sesión HTTP reutilizable.

    Returns
    -------
    tuple (docs_all, num_found)
        docs_all : list of dict
            Documentos Solr recuperados.
        num_found : int
            Total de documentos reportados por ESGF.
    """
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

        print(f"{experiment:10s} {variable:5s} offset={offset:5d}")

        if len(docs) < PAGE_SIZE:
            break

    return docs_all, num_found_total


def build_inventory(session=None, period_ranges=None):
    """
    Construye la matriz de disponibilidad a nivel de dataset considerando
    únicamente aquellos datasets que cubren o intersectan el período de interés.

    Parameters
    ----------
    session : requests.Session, optional
    period_ranges : dict, optional
        Diccionario con rangos (año_inicio, año_fin) por experimento.

    Returns
    -------
    tuple (pandas.DataFrame, dict)
        df : DataFrame con columnas por variable, score y complete.
        stats : Diccionario con estadísticas globales de ESGF.
    """
    inventory = defaultdict(set)
    total_numfound = 0
    total_downloaded = 0
    discarded_out_of_period = 0

    ranges = period_ranges if period_ranges is not None else PERIOD_RANGES

    for experiment in EXPERIMENTS:
        print()
        print("=" * 70)
        req_p = ranges.get(experiment, "Sin filtro")
        print(f"Procesando experimento: {experiment} (Período de interés: {req_p})")
        print("=" * 70)

        for variable in VARIABLES:
            docs, num_found = fetch_variable_experiment(variable, experiment, session=session)

            if num_found > 9999:
                raise RuntimeError(
                    f"{experiment}-{variable}: {num_found} resultados exceden el límite ESGF (9999)"
                )

            total_numfound += num_found
            total_downloaded += len(docs)

            valid_in_period = 0
            for doc in docs:
                if is_dataset_in_period(doc, experiment, period_ranges=ranges):
                    source_id = first(doc.get("source_id"))
                    variant_label = first(doc.get("variant_label"))
                    experiment_id = first(doc.get("experiment_id"))
                    variable_id = first(doc.get("variable_id"))

                    key = (source_id, variant_label, experiment_id)
                    inventory[key].add(variable_id)
                    valid_in_period += 1
                else:
                    discarded_out_of_period += 1

            print(
                f"{experiment:10s} "
                f"{variable:5s} "
                f"numFound={num_found:5d} "
                f"en_periodo={valid_in_period:5d}"
            )

    rows = []
    for key, vars_found in inventory.items():
        source_id, variant_label, experiment_id = key
        req_p = ranges.get(experiment_id)
        p_str = f"{req_p[0]}-{req_p[1]}" if req_p else "N/A"

        row = {
            "source_id": source_id,
            "variant_label": variant_label,
            "experiment_id": experiment_id,
            "period_range": p_str,
        }

        for var in VARIABLES:
            row[var] = var in vars_found

        row["score"] = len(vars_found)
        row["complete"] = row["score"] == len(VARIABLES)
        row["period_available"] = row["complete"]
        rows.append(row)

    df = pd.DataFrame(rows)
    # Ordenar primero por disponibilidad en período (TRUE arriba) y luego alfabéticamente
    df = df.sort_values(
        by=["period_available", "source_id", "variant_label", "experiment_id"],
        ascending=[False, True, True, True]
    )

    stats = {
        "total_numfound": total_numfound,
        "total_downloaded": total_downloaded,
        "discarded_out_of_period": discarded_out_of_period,
        "inventory_rows": len(df),
        "unique_models": df["source_id"].nunique() if not df.empty else 0,
    }

    print()
    print("=" * 70)
    print("RESUMEN ESGF (DATASETS EN PERÍODO DE INTERÉS)")
    print("=" * 70)
    print(f"Documentos reportados por ESGF : {stats['total_numfound']:,}")
    print(f"Documentos descargados         : {stats['total_downloaded']:,}")
    print(f"Datasets fuera de período      : {stats['discarded_out_of_period']:,}")
    print(f"Filas inventario válidas      : {stats['inventory_rows']:,}")
    print(f"Modelos únicos                : {stats['unique_models']:,}")
    print("=" * 70)
    print()

    return df, stats


def build_summary(df):
    """
    Consolida la disponibilidad a nivel de (source_id, variant_label).

    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame generado por build_inventory.

    Returns
    -------
    pandas.DataFrame
        Resumen consolidado con métricas de completitud y disponibilidad de período.
    """
    max_possible = len(VARIABLES) * len(EXPERIMENTS)

    summary = (
        df.groupby(["source_id", "variant_label"])
        .agg(
            complete_experiments=("complete", "sum"),
            total_variables=("score", "sum"),
        )
        .reset_index()
    )

    summary["availability_pct"] = 100.0 * summary["total_variables"] / max_possible
    summary["all_experiments_complete"] = summary["complete_experiments"] == len(EXPERIMENTS)
    summary["period_available"] = summary["all_experiments_complete"]

    # Ordenar primero por modelos que cumplen todas las condiciones (TRUE primero) y luego alfabéticamente
    summary = summary.sort_values(
        by=["period_available", "source_id", "variant_label"],
        ascending=[False, True, True],
    )

    return summary


# ---------------------------------------------------------------------
# FASE 2: Consulta y Extracción de Archivos NetCDF (type=File)
# ---------------------------------------------------------------------

def parse_file_doc(doc, source_id, variant_label, experiment_id, variable_id):
    """
    Parsea un documento Solr de tipo File (type=File) y extrae las URLs directas,
    metadatos de hash, tamaño y determina el método de acceso y prioridad de réplica.

    Estructura del campo 'url' en ESGF Solr:
        ["<URL>|<MIME_TYPE>|<SERVICE_TYPE>", ...]

    Servicios comunes en ESGF:
        - 'HTTPServer': Enlace directo HTTP/HTTPS al archivo NetCDF.
          Si está alojado en nodos con Globus (ej. eagle.alcf.anl.gov o LLNL),
          la URL apunta a 'https://*.data.globus.org/...'.
        - 'Globus': Enlace nativo 'globus:<endpoint-uuid>/ruta'.
        - 'OPENDAP': Enlace a servicio OPeNDAP.
        - 'GridFTP': Enlace gsiftp.

    Ranking de prioridad para réplicas:
        - Prioridad 3 (Máxima): HTTPS directas de Globus (*.data.globus.org) o
          nodos con acceso Globus activo + HTTPS.
        - Prioridad 2: URLs HTTPS seguras de THREDDS (https://...).
        - Prioridad 1: URLs HTTP estándar de THREDDS (http://...).
        - Prioridad 0: Otros accesos sin URL HTTP/HTTPS directa.

    Parameters
    ----------
    doc : dict
        Documento JSON de Solr para un archivo.
    source_id : str
    variant_label : str
    experiment_id : str
    variable_id : str

    Returns
    -------
    dict
        Metadatos parseados del archivo con puntaje de prioridad.
    """
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

    # Determinar la mejor URL HTTPS directa y el método de acceso
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
    """
    Consulta a ESGF Solr todos los archivos NetCDF correspondientes a una combinación
    específica de modelo, variante, experimento y variable, aplicando filtrado por
    período de interés.

    Maneja réplicas entre diferentes data nodes seleccionando para cada archivo
    físico único la copia con mayor prioridad (Globus HTTPS > HTTPS > HTTP).

    Parameters
    ----------
    source_id : str
    variant_label : str
    experiment_id : str
    variable_id : str
    session : requests.Session, optional
    period_ranges : dict, optional

    Returns
    -------
    tuple (list of dict, bool)
        files : Lista de registros de archivos únicos seleccionados.
        success : True si la consulta fue exitosa, False en caso de error.
    """
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

    # Deduplicar réplicas del mismo archivo físico (identificado por file_name)
    # seleccionando la réplica con el mayor priority_rank
    best_file_by_name = {}
    for doc in docs_all:
        parsed = parse_file_doc(doc, source_id, variant_label, experiment_id, variable_id)
        fname = parsed["file_name"]

        if fname not in best_file_by_name:
            best_file_by_name[fname] = parsed
        else:
            # Comparar prioridad de la nueva réplica
            if parsed["priority_rank"] > best_file_by_name[fname]["priority_rank"]:
                best_file_by_name[fname] = parsed

    # Filtrar por período de interés si está configurado
    ranges = period_ranges if period_ranges is not None else PERIOD_RANGES
    req_range = ranges.get(experiment_id)

    filtered_files = []
    for f in best_file_by_name.values():
        s_yr, e_yr = extract_file_years(f["file_name"])
        f["start_year"] = s_yr
        f["end_year"] = e_yr

        if req_range and s_yr is not None and e_yr is not None:
            req_start, req_end = req_range
            # Comprobar si el archivo intersecta con el período de interés
            if s_yr <= req_end and e_yr >= req_start:
                filtered_files.append(f)
        else:
            filtered_files.append(f)

    # Ordenar por nombre de archivo cronológico
    sorted_files = sorted(filtered_files, key=lambda x: x["file_name"] or "")
    return sorted_files, True


def build_files_inventory(selected_df, max_workers=MAX_WORKERS, session=None, period_ranges=None):
    """
    Ejecuta la segunda etapa de consulta para extraer el listado completo de archivos
    NetCDF con URLs directas HTTPS para todas las realizaciones seleccionadas,
    filtrando únicamente los archivos que pertenecen al período de interés.

    Utiliza concurrencia controlada para consultar de manera eficiente sin saturar Solr.

    Parameters
    ----------
    selected_df : pandas.DataFrame
        DataFrame con las realizaciones seleccionadas (source_id, variant_label).
    max_workers : int
        Número de hilos concurrentes para consultas a la API.
    session : requests.Session, optional
    period_ranges : dict, optional
        Diccionario con rangos (año_inicio, año_fin) por experimento.

    Returns
    -------
    tuple (pandas.DataFrame, list)
        files_df : DataFrame con todos los archivos NetCDF y URLs dentro del período.
        unresolved : Lista de combinaciones que no pudieron resolverse o sin archivos en el período.
    """
    print()
    print("=" * 70)
    print("FASE 2: CONSULTA DETALLADA DE ARCHIVOS NETCDF (FILTRADO POR PERÍODO)")
    print(f"Realizaciones seleccionadas a procesar: {len(selected_df)}")
    print(f"Total combinaciones dataset teóricas: {len(selected_df) * len(EXPERIMENTS) * len(VARIABLES):,}")
    print("Períodos de interés configurados:")
    eff_ranges = period_ranges if period_ranges is not None else PERIOD_RANGES
    for exp_k, r_v in eff_ranges.items():
        print(f"   - {exp_k:12s}: {r_v[0]} a {r_v[1]}")
    print("=" * 70)
    print()

    http_session = session or get_http_session()

    # Generar la lista de tareas: (source_id, variant_label, experiment_id, variable_id)
    tasks = []
    for _, row in selected_df.iterrows():
        s_id = row["source_id"]
        v_lbl = row["variant_label"]
        for exp in EXPERIMENTS:
            for var in VARIABLES:
                tasks.append((s_id, v_lbl, exp, var))

    total_tasks = len(tasks)
    all_files_records = []
    unresolved_combinations = []
    completed_tasks = 0
    t0 = time.time()

    def worker_func(task_args):
        src, var_lbl, exp, var = task_args
        files, success = fetch_files_for_combination(
            src, var_lbl, exp, var, session=http_session, period_ranges=eff_ranges
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

        # Calcular tamaño en MB para conveniencia del usuario
        if "file_size_bytes" in files_df.columns:
            files_df["file_size_mb"] = (
                files_df["file_size_bytes"].fillna(0) / (1024.0 * 1024.0)
            ).round(2)
        else:
            files_df["file_size_mb"] = 0.0

        # Texto para hipervínculo en Excel
        files_df["file_link"] = "Abrir"

        # Ordenar columnas lógicamente
        column_order = [
            "source_id",
            "variant_label",
            "experiment_id",
            "variable_id",
            "start_year",
            "end_year",
            "file_name",
            "file_link",
            "https_url",
            "access_method",
            "data_node",
            "file_size_mb",
            "file_size_bytes",
            "checksum",
            "checksum_type",
            "dataset_id",
            "instance_id",
            "master_id",
        ]
        # Asegurar que todas las columnas existan
        existing_cols = [c for c in column_order if c in files_df.columns]
        extra_cols = [c for c in files_df.columns if c not in column_order and c not in ("priority_rank", "has_globus")]
        files_df = files_df[existing_cols + extra_cols]

        files_df = files_df.sort_values(
            ["source_id", "variant_label", "experiment_id", "variable_id", "file_name"]
        )
    else:
        files_df = pd.DataFrame()

    return files_df, unresolved_combinations


def validate_files_inventory(files_df, selected_df, unresolved_combinations, period_ranges=None):
    """
    Ejecuta una rutina de validación que calcula y muestra estadísticas clave de los
    archivos extraídos, incluyendo verificación de cobertura temporal:
        - Cantidad de combinaciones procesadas vs esperadas
        - Total de archivos NetCDF encontrados en período
        - Archivos con URL HTTPS directa
        - Archivos con acceso Globus
        - Combinaciones no resueltas o sin datos en período
        - Cobertura temporal completa por dataset (min_yr <= inicio, max_yr >= fin)

    Parameters
    ----------
    files_df : pandas.DataFrame
    selected_df : pandas.DataFrame
    unresolved_combinations : list
    period_ranges : dict, optional
    """
    total_expected_datasets = len(selected_df) * len(EXPERIMENTS) * len(VARIABLES)
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

    # Validación de Cobertura Temporal por Dataset
    ranges = period_ranges if period_ranges is not None else PERIOD_RANGES
    if not files_df.empty and "start_year" in files_df.columns:
        combos = files_df.groupby(["source_id", "variant_label", "experiment_id", "variable_id"]).agg(
            min_yr=("start_year", "min"),
            max_yr=("end_year", "max"),
            file_count=("file_name", "count")
        ).reset_index()

        incomplete_temporal = []
        for _, row in combos.iterrows():
            exp = row["experiment_id"]
            req_r = ranges.get(exp)
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
# Exportación Excel y CSV con Formato
# ---------------------------------------------------------------------

def export_results(df, summary, selected, files_df,
                   csv_inventory="cmip6_daily_inventory.csv",
                   csv_files="cmip6_files.csv",
                   csv_complete_models="cmip6_complete_models.csv",
                   xlsx_file="cmip6_daily_inventory.xlsx"):
    """
    Exporta el inventario, resumen, seleccionados y archivos a archivos CSV y Excel,
    aplicando hipervínculos dinámicos y formato condicional con openpyxl.

    Parameters
    ----------
    df : pandas.DataFrame
        Inventario detallado.
    summary : pandas.DataFrame
        Resumen por modelo-realización.
    selected : pandas.DataFrame
        Realizaciones completas seleccionadas.
    files_df : pandas.DataFrame
        Catálogo detallado de archivos NetCDF.
    csv_inventory : str
    csv_files : str
    csv_complete_models : str
    xlsx_file : str
    """
    # Guardar CSVs
    df.to_csv(csv_inventory, index=False)
    print(f"Inventario CSV guardado: {csv_inventory}")

    if not files_df.empty:
        files_df.to_csv(csv_files, index=False)
        print(f"Catálogo de archivos CSV guardado: {csv_files}")

    # Exportar CSV con los nombres de los modelos que cumplen todas las condiciones en formato NOMBRE.variante (sin encabezado)
    complete_models_df = summary[summary["period_available"] == True].copy()
    complete_models_df["model"] = complete_models_df["source_id"].astype(str) + "." + complete_models_df["variant_label"].astype(str)
    complete_models_df = complete_models_df.sort_values("model")

    complete_models_df[["model"]].to_csv(csv_complete_models, index=False, header=False)
    print(f"Listado de modelos completos CSV guardado ({len(complete_models_df)} modelos, sin encabezado): {csv_complete_models}")

    if not OPENPYXL_AVAILABLE:
        print("[AVISO] openpyxl no está instalado en este entorno; se exportará Excel básico sin formato.")
        try:
            with pd.ExcelWriter(xlsx_file) as writer:
                df.to_excel(writer, sheet_name="inventory", index=False)
                summary.to_excel(writer, sheet_name="summary", index=False)
                selected.to_excel(writer, sheet_name="selected", index=False)
                if not files_df.empty:
                    files_df.to_excel(writer, sheet_name="files", index=False)
            print(f"Libro Excel guardado: {xlsx_file}")
        except Exception as e:
            print(f"[ERROR] No se pudo guardar Excel: {e}")
        return

    # Guardar Excel estilizado con openpyxl
    try:
        with pd.ExcelWriter(xlsx_file, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="inventory", index=False)
            summary.to_excel(writer, sheet_name="summary", index=False)
            selected.to_excel(writer, sheet_name="selected", index=False)

            if not files_df.empty:
                files_df.to_excel(writer, sheet_name="files", index=False)

            # Estilos de celda
            green_fill = PatternFill(fill_type="solid", start_color="C6EFCE", end_color="C6EFCE")
            red_fill = PatternFill(fill_type="solid", start_color="FFC7CE", end_color="FFC7CE")

            # Formato condicional en 'inventory'
            ws_inventory = writer.sheets["inventory"]
            var_cols = [i for i, cell in enumerate(ws_inventory[1], start=1) if cell.value in VARIABLES]
            comp_cols = [i for i, cell in enumerate(ws_inventory[1], start=1) if cell.value in ("complete", "period_available")]

            for col_num in var_cols + comp_cols:
                for row in range(2, ws_inventory.max_row + 1):
                    cell = ws_inventory.cell(row=row, column=col_num)
                    if cell.value is True:
                        cell.fill = green_fill
                    elif cell.value is False:
                        cell.fill = red_fill

            # Formato condicional en 'summary'
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

                    # Ocultar la columna con la URL cruda para mantener la vista limpia
                    ws_files.column_dimensions[get_column_letter(f_url_col)].hidden = True

        print(f"Libro Excel guardado exitosamente: {xlsx_file}")
    except PermissionError:
        alt_xlsx = f"cmip6_daily_inventory_{int(time.time())}.xlsx"
        print(f"[ADVERTENCIA] No se pudo escribir '{xlsx_file}' (posiblemente abierto en Excel). Guardando en '{alt_xlsx}'...")
        export_results(df, summary, selected, files_df, csv_inventory, csv_files, csv_complete_models, alt_xlsx)


# ---------------------------------------------------------------------
# Función Principal
# ---------------------------------------------------------------------

def main():
    """
    Flujo principal de ejecución:
        1. Construcción del inventario global de datasets ESGF.
        2. Resumen y cruce con GCMEval.
        3. Selección de realizaciones completas.
        4. Consulta detallada de archivos NetCDF para realizaciones seleccionadas.
        5. Validación y exportación en CSV y Excel.
    """
    print()
    print("=" * 70)
    print("INICIANDO INVENTARIO Y EXTRACCIÓN DE ARCHIVOS CMIP6 (ESGF METAGRID)")
    print("=" * 70)
    print()

    session = get_http_session()

    # Fase 1: Inventario
    df, stats = build_inventory(session=session)
    summary = build_summary(df)

    # Cruce con GCMEval
    if os.path.exists("gcmeval_models.csv"):
        try:
            gcmeval_set = set()
            with open("gcmeval_models.csv", "r", encoding="utf-8") as f:
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

            summary["model_pipe"] = summary["source_id"].astype(str) + "|" + summary["variant_label"].astype(str)
            summary["model_dot"] = summary["source_id"].astype(str) + "." + summary["variant_label"].astype(str)
            summary["gcmeval"] = summary["model_pipe"].isin(gcmeval_set) | summary["model_dot"].isin(gcmeval_set)
            summary = summary.drop(columns=["model_pipe", "model_dot"])
        except Exception as e:
            print(f"[ADVERTENCIA] Error al procesar gcmeval_models.csv: {e}")
            summary["gcmeval"] = False
    else:
        print("[AVISO] gcmeval_models.csv no encontrado; omitiendo cruce con GCMEval.")
        summary["gcmeval"] = False

    # Filtrar realizaciones seleccionadas (completitud total en todos los experimentos)
    selected = summary[summary["complete_experiments"] == len(EXPERIMENTS)].copy()
    selected["dataset_url"] = selected.apply(
        lambda row: build_metagrid_url(row["source_id"], row["variant_label"]),
        axis=1,
    )
    selected["metagrid"] = "Abrir"

    # Fase 2: Archivos NetCDF de las realizaciones seleccionadas
    files_df, unresolved = build_files_inventory(
        selected_df=selected,
        max_workers=MAX_WORKERS,
        session=session,
    )

    # Validación estadística
    validate_files_inventory(files_df, selected, unresolved)

    # Exportación
    export_results(
        df=df,
        summary=summary,
        selected=selected,
        files_df=files_df,
        csv_inventory="cmip6_daily_inventory.csv",
        csv_files="cmip6_files.csv",
        csv_complete_models="cmip6_complete_models.csv",
        xlsx_file="cmip6_daily_inventory.xlsx",
    )

    print()
    print("=" * 70)
    print("PROCESO COMPLETADO EXITOSAMENTE")
    print("=" * 70)
    print(f"Modelos únicos identificados          : {stats['unique_models']:,}")
    print(f"Realizaciones completas en período    : {len(selected):,}")
    print(f"Realizaciones compatibles con GCMEval : {selected['gcmeval'].sum():,}")
    print(f"Total archivos NetCDF catalogados     : {len(files_df):,}")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
