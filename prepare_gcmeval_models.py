#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preparador e Incorporador de Nuevos Modelos CMIP6 y Referencias para GCMEval
==============================================================================
1. Identifica modelos 100% completos en ESGF (results/cmip6_daily_inventory.csv)
   que aún no figuran en gcmeval/gcmeval_models.csv.
2. Verifica (y descarga si faltan) los archivos observacionales de referencia
   (GPCP mensual público y ERA5 mensual vía Copernicus CDS/.cdsapirc o .env).
3. Consulta ESGF (table_id=Amon, tas y pr), descarga y concatena globalmente
   (historical + escenario) con CDO sin recorte regional.
4. Respalda meta.rda y statistics.rda, ejecuta gcmeval/update_gcmeval_db.R,
   reinstala el paquete local y sincroniza gcmeval/gcmeval_models.csv.
"""

import os
import sys
import csv
import shutil
import argparse
import subprocess
import importlib.util
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

GPCP_URL = "https://downloads.psl.noaa.gov/Datasets/gpcp/precip.mon.mean.nc"
REQUIRED_EXPS = {"historical", "ssp126", "ssp245", "ssp370", "ssp585"}


def load_esgf_query_module(repo_root):
    """Importa dinámicamente funciones de esgf-query.py para reutilizar sesión y búsqueda ESGF."""
    eq_path = Path(repo_root) / "esgf-query.py"
    spec = importlib.util.spec_from_file_location("esgf_query", str(eq_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_dotenv(repo_root):
    """Carga variables clave=valor desde .env local (si existe) sin sobreescribir el entorno."""
    env_path = Path(repo_root) / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def resolve_cds_credentials(repo_root):
    """
    Resuelve credenciales de Copernicus CDS desde:
      1) Variables de entorno / .env: CDSAPI_URL y CDSAPI_KEY
      2) Archivo .cdsapirc en la raíz del repositorio
      3) Archivo ~/.cdsapirc en el directorio del usuario
    Retorna dict {'mode': 'env'|'rc', 'url': ..., 'key': ..., 'rc_path': ...} o None.
    """
    load_dotenv(repo_root)
    env_key = os.environ.get("CDSAPI_KEY", "").strip()
    env_url = os.environ.get("CDSAPI_URL", "https://cds.climate.copernicus.eu/api").strip()
    if env_key:
        return {"mode": "env", "url": env_url, "key": env_key, "rc_path": None}

    for candidate in [Path(repo_root) / ".cdsapirc", Path.home() / ".cdsapirc"]:
        if candidate.is_file():
            return {"mode": "rc", "url": None, "key": None, "rc_path": str(candidate)}
    return None


def check_cdo_years(nc_path, start_year=1981, end_year=2010):
    """Verifica con CDO que el archivo NetCDF sea válido y cubra start_year..end_year."""
    p = Path(nc_path)
    if not p.is_file() or p.stat().st_size < 1024:
        return False
    cdo_exe = shutil.which("cdo")
    if not cdo_exe:
        return False
    res = subprocess.run([cdo_exe, "-s", "showyear", str(p)], capture_output=True, text=True)
    if res.returncode != 0:
        return False
    years = {int(tok) for tok in res.stdout.split() if tok.isdigit()}
    return all(y in years for y in range(start_year, end_year + 1))


def ensure_reference_data(repo_root, ref_dir, eq_mod):
    """Verifica GPCP y ERA5 (1981-2010) en ref_dir y descarga únicamente lo faltante."""
    ref_path = Path(ref_dir)
    ref_path.mkdir(parents=True, exist_ok=True)
    cdo_exe = shutil.which("cdo")
    if not cdo_exe:
        raise RuntimeError("Se requiere 'cdo' en el PATH para verificar y preparar los datos de referencia.")

    gpcp_target = ref_path / "gpcp.nc"
    era5_target = ref_path / "era5_monthly_1979-2018_tas.2.5deg.nc"

    # 1. GPCP mensual
    if check_cdo_years(gpcp_target, 1981, 2010):
        print(f"[OK] Referencia GPCP verificada (1981-2010): {gpcp_target}")
    else:
        print(f"[INFO] Descargando referencia pública GPCP v2.3 desde NOAA PSL...")
        raw_gpcp = ref_path / "gpcp_raw.nc"
        session = eq_mod.create_session()
        with session.get(GPCP_URL, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(raw_gpcp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        subprocess.run([cdo_exe, "-O", "-s", "selyear,1979/2018", str(raw_gpcp), str(gpcp_target)], check=True)
        raw_gpcp.unlink(missing_ok=True)
        if not check_cdo_years(gpcp_target, 1981, 2010):
            raise RuntimeError(f"El archivo GPCP descargado no cubre 1981-2010: {gpcp_target}")
        print(f"[OK] Referencia GPCP preparada: {gpcp_target}")

    # 2. ERA5 mensual (tas)
    if check_cdo_years(era5_target, 1981, 2010):
        print(f"[OK] Referencia ERA5 verificada (1981-2010): {era5_target}")
    else:
        creds = resolve_cds_credentials(repo_root)
        if not creds:
            print("\n[ERROR] Falta el archivo de referencia ERA5 y no se encontraron credenciales de Copernicus CDS.")
            print("Para habilitar la descarga automática de ERA5, usa una de estas dos opciones:")
            print(f"  1) Coloca tu archivo '.cdsapirc' en '{Path.home() / '.cdsapirc'}' o en '{Path(repo_root) / '.cdsapirc'}'")
            print("  2) Define 'CDSAPI_URL' y 'CDSAPI_KEY' en tu archivo '.env' o en variables de entorno.")
            print(f"  3) O coloca manualmente 'era5_monthly_1979-2018_tas.2.5deg.nc' en '{ref_path}'.\n")
            sys.exit(1)

        try:
            import cdsapi
        except ImportError:
            print("[ERROR] El paquete 'cdsapi' no está instalado. Instálalo con: pip install cdsapi")
            sys.exit(1)

        print("[INFO] Descargando ERA5 mensual (2m_temperature, 1979-2018) desde Copernicus CDS...")
        if creds["mode"] == "env":
            client = cdsapi.Client(url=creds["url"], key=creds["key"])
        else:
            os.environ["CDSAPI_RC"] = creds["rc_path"]
            client = cdsapi.Client()

        raw_era5 = ref_path / "era5_raw_t2m.nc"
        client.retrieve(
            "reanalysis-era5-single-levels-monthly-means",
            {
                "product_type": ["monthly_averaged_reanalysis"],
                "variable": ["2m_temperature"],
                "year": [str(y) for y in range(1979, 2019)],
                "month": [f"{m:02d}" for m in range(1, 13)],
                "time": ["00:00"],
                "data_format": "netcdf",
            },
            str(raw_era5),
        )
        subprocess.run(
            [cdo_exe, "-O", "-s", "-b", "F32", "remapbil,r144x72", "-chname,t2m,tas", str(raw_era5), str(era5_target)],
            check=True,
        )
        raw_era5.unlink(missing_ok=True)
        if not check_cdo_years(era5_target, 1981, 2010):
            raise RuntimeError(f"El archivo ERA5 descargado no cubre 1981-2010: {era5_target}")
        print(f"[OK] Referencia ERA5 preparada: {era5_target}")


def find_missing_gcmeval_models(repo_root, eq_mod):
    """Retorna realizaciones 100% completas en ESGF que aún no están en gcmeval/gcmeval_models.csv."""
    root = Path(repo_root)
    inv_csv = root / "results" / "cmip6_daily_inventory.csv"
    if not inv_csv.is_file():
        raise FileNotFoundError(
            f"No se encontró '{inv_csv}'. Ejecuta primero: python esgf-query.py"
        )

    gcmeval_set, _ = eq_mod.load_gcmeval_models()
    complete_by_model = defaultdict(set)
    with open(inv_csv, "r", encoding="utf-8", errors="replace", newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("complete", "")).strip().lower() == "true":
                key = (row["source_id"].strip(), row["variant_label"].strip())
                complete_by_model[key].add(row["experiment_id"].strip())

    missing = []
    for (s_id, v_lbl), exps in sorted(complete_by_model.items()):
        if REQUIRED_EXPS.issubset(exps):
            if f"{s_id}|{v_lbl}" not in gcmeval_set:
                missing.append((s_id, v_lbl))
    return missing


def query_amon_files(eq_mod, source_id, variant_label, scenario="ssp585"):
    """Consulta archivos Amon (tas, pr) en ESGF para historical y scenario."""
    session = eq_mod.create_session()
    records = []
    for exp in ("historical", scenario):
        for var in ("tas", "pr"):
            params = {
                "project": "CMIP6",
                "source_id": source_id,
                "variant_label": variant_label,
                "experiment_id": exp,
                "table_id": "Amon",
                "variable_id": var,
                "type": "File",
                "latest": "true",
                "limit": 1000,
            }
            data = eq_mod.solr_get(params, session=session)
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                raise RuntimeError(f"No se encontraron archivos Amon para {source_id}.{variant_label} {exp} {var}")

            by_fname = {}
            for d in docs:
                fname = d.get("title") or (d.get("id", "").split("|")[0].split(".")[-1])
                urls = d.get("url") or []
                http_urls = [u.split("|")[0] for u in urls if "HTTPServer" in u or u.startswith("http")]
                if not http_urls:
                    continue
                by_fname.setdefault(fname, []).extend(http_urls)

            for fname, urls in sorted(by_fname.items()):
                ranked = sorted(set(urls), key=eq_mod.url_priority_key)
                records.append({
                    "source_id": source_id,
                    "variant_label": variant_label,
                    "experiment_id": exp,
                    "variable_id": var,
                    "file_name": fname,
                    "urls": ranked,
                })
    return records


def download_and_stage_model(eq_mod, source_id, variant_label, scenario, staging_root):
    """Descarga archivos Amon y genera un NetCDF global concatenado por variable (tas y pr)."""
    cdo_exe = shutil.which("cdo")
    if not cdo_exe:
        raise RuntimeError("Se requiere 'cdo' en el PATH para preparar los archivos NetCDF de GCMEval.")

    raw_dir = Path(staging_root) / "raw" / f"{source_id}_{variant_label}"
    out_dir = Path(staging_root) / "CMIP6"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    records = query_amon_files(eq_mod, source_id, variant_label, scenario=scenario)
    session = eq_mod.create_session()

    for var in ("tas", "pr"):
        final_nc = out_dir / f"{var}_Amon_{source_id}_{scenario}_{variant_label}_198001-210012.nc"
        if final_nc.is_file() and check_cdo_years(final_nc, 1981, 2010) and check_cdo_years(final_nc, 2071, 2100):
            print(f"[CHECKPOINT] Ya preparado: {final_nc.name}")
            continue

        var_recs = [r for r in records if r["variable_id"] == var]
        local_chunks = []
        for r in var_recs:
            dest = raw_dir / r["file_name"]
            if not (dest.is_file() and dest.stat().st_size > 1024):
                downloaded = False
                for url in r["urls"]:
                    try:
                        with session.get(url, stream=True, timeout=120) as resp:
                            resp.raise_for_status()
                            with open(dest, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                                    if chunk:
                                        f.write(chunk)
                        downloaded = True
                        break
                    except Exception:
                        continue
                if not downloaded:
                    raise RuntimeError(f"No se pudo descargar {r['file_name']} desde ninguna réplica.")
            local_chunks.append(str(dest))

        merged_tmp = out_dir / f".tmp_{var}_{source_id}_{variant_label}.nc"
        subprocess.run([cdo_exe, "-O", "-s", "mergetime", *local_chunks, str(merged_tmp)], check=True)
        subprocess.run([cdo_exe, "-O", "-s", "selyear,1980/2100", str(merged_tmp), str(final_nc)], check=True)
        merged_tmp.unlink(missing_ok=True)
        print(f"[OK] Preparado NetCDF global para GCMEval: {final_nc.name}")


def main():
    parser = argparse.ArgumentParser(
        description="Prepara e incorpora nuevos modelos CMIP6 (Amon tas/pr) a GCMEval con respaldo previo."
    )
    parser.add_argument("--list", action="store_true", help="Lista modelos completos en ESGF ausentes en GCMEval y sale.")
    parser.add_argument("--model", default=None, help="Modelo(s) a incorporar separados por coma (ej. ACCESS-CM2.r4i1p1f1).")
    parser.add_argument("-y", "--yes", action="store_true", help="Ejecuta sin menú interactivo.")
    parser.add_argument("--scenario", default="ssp585", help="Escenario SSP objetivo (por defecto: ssp585).")
    parser.add_argument("--ref-dir", default="cache/ref", help="Directorio para ERA5 y GPCP (por defecto: cache/ref).")
    parser.add_argument("--staging-dir", default="cache/gcmeval_staging", help="Directorio temporal de descarga/preparación.")
    parser.add_argument("--restore-backup", action="store_true", help="Restaura el último respaldo de meta.rda y statistics.rda.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    eq_mod = load_esgf_query_module(repo_root)
    rscript = eq_mod._find_rscript()

    if args.restore_backup:
        if not rscript:
            print("[ERROR] No se encontró Rscript para restaurar el respaldo.")
            sys.exit(1)
        subprocess.run([rscript, "gcmeval/update_gcmeval_db.R", "--restore-backup"], cwd=str(repo_root), check=True)
        eq_mod.sync_gcmeval_models_csv()
        return

    missing = find_missing_gcmeval_models(repo_root, eq_mod)
    print("=" * 72)
    print(f" MODELOS 100% COMPLETOS EN ESGF AUSENTES EN GCMEVAL ({len(missing)} modelos)")
    print("=" * 72)
    for idx, (s_id, v_lbl) in enumerate(missing, 1):
        print(f"  [{idx:2d}] {s_id}.{v_lbl}")
    print("=" * 72)

    if args.list or not missing:
        return

    selected = []
    if args.model:
        req = {m.strip().lower() for m in args.model.split(",") if m.strip()}
        selected = [(s, v) for (s, v) in missing if f"{s}.{v}".lower() in req or s.lower() in req]
    elif not args.yes and sys.stdin.isatty():
        ans = input("\nIngresa números o nombres separados por coma (ENTER = cancelar): ").strip()
        if not ans:
            print("[INFO] Operación cancelada.")
            return
        for tok in ans.split(","):
            tok = tok.strip()
            if tok.isdigit() and 1 <= int(tok) <= len(missing):
                selected.append(missing[int(tok) - 1])
            else:
                for (s, v) in missing:
                    if tok.lower() in (f"{s}.{v}".lower(), s.lower()):
                        selected.append((s, v))
    else:
        print("[ERROR] Especifica '--model' en modo no interactivo.")
        sys.exit(1)

    selected = list(dict.fromkeys(selected))
    if not selected:
        print("[AVISO] No se seleccionó ningún modelo válido.")
        return

    print(f"\n[INFO] Se prepararán {len(selected)} modelo(s): {', '.join(f'{s}.{v}' for s, v in selected)}")
    ensure_reference_data(repo_root, args.ref_dir, eq_mod)

    for s_id, v_lbl in selected:
        download_and_stage_model(eq_mod, s_id, v_lbl, args.scenario, args.staging_dir)

    if not rscript:
        print("[ERROR] No se encontró Rscript para actualizar meta.rda y statistics.rda.")
        sys.exit(1)

    subprocess.run(
        [
            rscript,
            "gcmeval/update_gcmeval_db.R",
            "--staging-dir", str(Path(args.staging_dir) / "CMIP6"),
            "--ref-dir", str(args.ref_dir),
        ],
        cwd=str(repo_root),
        check=True,
    )
    eq_mod.sync_gcmeval_models_csv()


if __name__ == "__main__":
    main()
