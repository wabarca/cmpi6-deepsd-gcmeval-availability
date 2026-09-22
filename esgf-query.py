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

# Frecuencia temporal requerida
TABLE_ID = "day"

# Tamaño de página para consultas a ESGF Solr
PAGE_SIZE = 1000
FILES_PAGE_SIZE = 1000

# Concurrencia para consultas de archivos (hilos de red)
MAX_WORKERS = 6


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


def build_inventory(session=None):
    """
    Construye la matriz de disponibilidad a nivel de dataset.

    Returns
    -------
    tuple (pandas.DataFrame, dict)
        df : DataFrame con columnas por variable, score y complete.
        stats : Diccionario con estadísticas globales de ESGF.
    """
    inventory = defaultdict(set)
    total_numfound = 0
    total_downloaded = 0

    for experiment in EXPERIMENTS:
        print()
        print("=" * 70)
        print(f"Procesando experimento: {experiment}")
        print("=" * 70)

        for variable in VARIABLES:
            docs, num_found = fetch_variable_experiment(variable, experiment, session=session)

            if num_found > 9999:
                raise RuntimeError(
                    f"{experiment}-{variable}: {num_found} resultados exceden el límite ESGF (9999)"
                )

            total_numfound += num_found
            total_downloaded += len(docs)

            print(
                f"{experiment:10s} "
                f"{variable:5s} "
                f"numFound={num_found:5d} "
                f"downloaded={len(docs):5d}"
            )

            for doc in docs:
                source_id = first(doc.get("source_id"))
                variant_label = first(doc.get("variant_label"))
                experiment_id = first(doc.get("experiment_id"))
                variable_id = first(doc.get("variable_id"))

                key = (source_id, variant_label, experiment_id)
                inventory[key].add(variable_id)

    rows = []
    for key, vars_found in inventory.items():
        source_id, variant_label, experiment_id = key
        row = {
            "source_id": source_id,
            "variant_label": variant_label,
            "experiment_id": experiment_id,
        }

        for var in VARIABLES:
            row[var] = var in vars_found

        row["score"] = len(vars_found)
        row["complete"] = row["score"] == len(VARIABLES)
        rows.append(row)

    df = pd.DataFrame(rows)
    df = df.sort_values(["source_id", "variant_label", "experiment_id"])

    stats = {
        "total_numfound": total_numfound,
        "total_downloaded": total_downloaded,
        "inventory_rows": len(df),
        "unique_models": df["source_id"].nunique() if not df.empty else 0,
    }

    print()
    print("=" * 70)
    print("RESUMEN ESGF (DATASETS)")
    print("=" * 70)
    print(f"Documentos reportados por ESGF : {stats['total_numfound']:,}")
    print(f"Documentos descargados         : {stats['total_downloaded']:,}")
    print(f"Filas inventario              : {stats['inventory_rows']:,}")
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
        Resumen consolidado con métricas de completitud.
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

    summary = summary.sort_values(
        ["complete_experiments", "total_variables", "availability_pct"],
        ascending=False,
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


def fetch_files_for_combination(source_id, variant_label, experiment_id, variable_id, session=None):
    """
    Consulta a ESGF Solr todos los archivos NetCDF correspondientes a una combinación
    específica de modelo, variante, experimento y variable.

    Maneja réplicas entre diferentes data nodes seleccionando para cada archivo
    físico único la copia con mayor prioridad (Globus HTTPS > HTTPS > HTTP).

    Parameters
    ----------
    source_id : str
    variant_label : str
    experiment_id : str
    variable_id : str
    session : requests.Session, optional

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

    # Ordenar por nombre de archivo cronológico
    sorted_files = sorted(best_file_by_name.values(), key=lambda x: x["file_name"] or "")
    return sorted_files, True


def build_files_inventory(selected_df, max_workers=MAX_WORKERS, session=None):
    """
    Ejecuta la segunda etapa de consulta para extraer el listado completo de archivos
    NetCDF con URLs directas HTTPS para todas las realizaciones seleccionadas.

    Utiliza concurrencia controlada para consultar de manera eficiente sin saturar Solr.

    Parameters
    ----------
    selected_df : pandas.DataFrame
        DataFrame con las realizaciones seleccionadas (source_id, variant_label).
    max_workers : int
        Número de hilos concurrentes para consultas a la API.
    session : requests.Session, optional

    Returns
    -------
    tuple (pandas.DataFrame, list)
        files_df : DataFrame con todos los archivos NetCDF y URLs.
        unresolved : Lista de combinaciones que no pudieron resolverse.
    """
    print()
    print("=" * 70)
    print("FASE 2: CONSULTA DETALLADA DE ARCHIVOS NETCDF")
    print(f"Realizaciones seleccionadas a procesar: {len(selected_df)}")
    print(f"Total combinaciones dataset teóricas: {len(selected_df) * len(EXPERIMENTS) * len(VARIABLES):,}")
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
            src, var_lbl, exp, var, session=http_session
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
                    "reason": "Error en consulta" if not success else "Sin archivos devueltos",
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


def validate_files_inventory(files_df, selected_df, unresolved_combinations):
    """
    Ejecuta una rutina de validación que calcula y muestra estadísticas clave de los
    archivos extraídos:
        - Cantidad de combinaciones procesadas vs esperadas
        - Total de archivos NetCDF encontrados
        - Archivos con URL HTTPS directa
        - Archivos con acceso Globus
        - Combinaciones no resueltas
        - URLs únicas

    Parameters
    ----------
    files_df : pandas.DataFrame
    selected_df : pandas.DataFrame
    unresolved_combinations : list
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
    print(f"Combinaciones dataset no resueltas     : {len(unresolved_combinations):,}")
    print(f"Total archivos NetCDF encontrados      : {total_files:,}")
    print(f"Archivos con URL HTTPS directa         : {https_count:,}")
    print(f"Archivos con URL HTTP estándar         : {http_count:,}")
    print(f"Archivos con soporte Globus            : {globus_count:,}")
    print(f"URLs directas únicas                   : {unique_urls:,}")
    print(f"Volumen total catalogado               : {total_size_gb:,.2f} GB")
    print("=" * 70)

    if unresolved_combinations:
        print()
        print("ADVERTENCIA: Combinaciones no resueltas:")
        for unres in unresolved_combinations[:10]:
            print(f"  - {unres['source_id']} {unres['variant_label']} {unres['experiment_id']} {unres['variable_id']}: {unres['reason']}")
        if len(unresolved_combinations) > 10:
            print(f"  ... y {len(unresolved_combinations) - 10} más.")
    print()


# ---------------------------------------------------------------------
# Exportación Excel y CSV con Formato
# ---------------------------------------------------------------------

def export_results(df, summary, selected, files_df,
                   csv_inventory="cmip6_daily_inventory.csv",
                   csv_files="cmip6_files.csv",
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
    xlsx_file : str
    """
    # Guardar CSVs
    df.to_csv(csv_inventory, index=False)
    print(f"Inventario CSV guardado: {csv_inventory}")

    if not files_df.empty:
        files_df.to_csv(csv_files, index=False)
        print(f"Catálogo de archivos CSV guardado: {csv_files}")

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
            comp_cols = [i for i, cell in enumerate(ws_inventory[1], start=1) if cell.value == "complete"]

            for col_num in var_cols + comp_cols:
                for row in range(2, ws_inventory.max_row + 1):
                    cell = ws_inventory.cell(row=row, column=col_num)
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
        export_results(df, summary, selected, files_df, csv_inventory, csv_files, alt_xlsx)


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
        gcmeval = pd.read_csv("gcmeval_models.csv")
        gcmeval["model_key"] = (
            gcmeval["source_id"].astype(str) + "|" + gcmeval["variant_label"].astype(str)
        )
        summary["model_key"] = (
            summary["source_id"].astype(str) + "|" + summary["variant_label"].astype(str)
        )
        gcmeval_set = set(gcmeval["model_key"])
        summary["gcmeval"] = summary["model_key"].isin(gcmeval_set)
        summary = summary.drop(columns=["model_key"])
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
        xlsx_file="cmip6_daily_inventory.xlsx",
    )

    print()
    print("=" * 70)
    print("PROCESO COMPLETADO EXITOSAMENTE")
    print("=" * 70)
    print(f"Modelos únicos identificados          : {stats['unique_models']:,}")
    print(f"Realizaciones completas seleccionadas : {len(selected):,}")
    print(f"Realizaciones compatibles con GCMEval : {selected['gcmeval'].sum():,}")
    print(f"Total archivos NetCDF catalogados     : {len(files_df):,}")
    print("=" * 70)
    print()


if __name__ == "__main__":
    main()
