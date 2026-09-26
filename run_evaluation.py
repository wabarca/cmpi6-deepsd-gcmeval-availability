#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
Orquestador en Python para la Evaluación Climatológica CMIP6 con GCMEval
==============================================================================
Este script permite ejecutar todo el marco de evaluación de modelos climáticos
de GCMEval (desarrollado en R) de forma automatizada desde el entorno Python.

Funcionalidades:
1. Detección automática del ejecutable Rscript en Windows, Linux y macOS.
2. Validación de dependencias y paquetes de R requeridos.
3. Ejecución concurrente y streaming en tiempo real de los 9 experimentos (E0-E8).
4. Verificación de artefactos generados (rankings CSV, gráficos HTML interactivos y PNG).
"""

import os
import sys
import glob
import json
import shutil
import argparse
import subprocess
from pathlib import Path

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

# Configurar salida estándar en UTF-8 para evitar errores de codificación en consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Catálogo de regiones SREX y dominios disponibles en GCMEval
AVAILABLE_REGIONS = [
    "Central America/Mexico [CAM:6]",
    "small islands regions Caribbean",
    "Amazon [AMZ:7]",
    "West Coast South America [WSA:9]",
    "Southeastern South America [SSA:10]",
    "North-East Brazil [NEB:8]",
    "Central North America [CNA:4]",
    "East North America [ENA:5]",
    "Global"
]

AVAILABLE_OBS_TEMP = ["ERA5", "NCEP", "CRU"]
AVAILABLE_OBS_PREC = ["GPCP", "CHIRPS", "MSWEP"]


def get_default_config():
    """Genera la estructura de configuración predeterminada."""
    return {
        "scenario": "ssp585",
        "observations": {
            "temperature": "ERA5",
            "precipitation": "GPCP"
        },
        "regions": {
            "primary": {
                "name": "Central America/Mexico [CAM:6]",
                "weight": 1.0
            },
            "secondary": {
                "enabled": False,
                "name": "small islands regions Caribbean",
                "weight": 0.3
            }
        },
        "metrics_weights": {
            "bias": 1.0,
            "std_dev": 1.0,
            "correlation": 1.0,
            "rmse": 1.0
        },
        "experiments": {
            "E0": {"name": "E0_Control_Equilibrado", "wt": 1.0, "wp": 1.0, "seasons": [1, 1, 1, 1, 1], "desc": "Control / Balance General"},
            "E1": {"name": "E1_Enfasis_Temperatura", "wt": 2.0, "wp": 1.0, "seasons": [1, 1, 1, 1, 1], "desc": "Énfasis en Temperatura"},
            "E2": {"name": "E2_Enfasis_Precipitacion", "wt": 1.0, "wp": 2.0, "seasons": [1, 1, 1, 1, 1], "desc": "Énfasis en Precipitación"},
            "E3": {"name": "E3_Epoca_Seca", "wt": 1.0, "wp": 1.0, "seasons": [1, 2, 2, 0, 0], "desc": "Época Seca (Estiaje DJF+MAM)"},
            "E4": {"name": "E4_Epoca_Lluviosa", "wt": 1.0, "wp": 1.0, "seasons": [1, 0, 2, 2, 2], "desc": "Época Lluviosa (MAM+JJA+SON)"},
            "E5": {"name": "E5_Temperatura_Epoca_Seca", "wt": 2.0, "wp": 1.0, "seasons": [1, 2, 2, 0, 0], "desc": "Temperatura en Época Seca"},
            "E6": {"name": "E6_Precipitacion_Lluviosa", "wt": 1.0, "wp": 2.0, "seasons": [1, 0, 2, 2, 2], "desc": "Precipitación en Época Lluviosa"},
            "E7": {"name": "E7_Solo_Temperatura", "wt": 2.0, "wp": 0.0, "seasons": [1, 1, 1, 1, 1], "desc": "Termodinámica Pura (Solo Temp)"},
            "E8": {"name": "E8_Solo_Precipitacion", "wt": 0.0, "wp": 2.0, "seasons": [1, 1, 1, 1, 1], "desc": "Hidrología Pura (Solo Lluvia)"}
        }
    }


def load_or_create_config(config_path):
    """Carga el archivo de configuración YAML o lo crea si no existe."""
    p = Path(config_path)
    if p.is_file():
        try:
            if HAS_YAML:
                with open(p, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if isinstance(cfg, dict):
                        return cfg
            else:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"[AVISO] No se pudo leer '{config_path}': {e}. Usando configuración por defecto.")

    cfg = get_default_config()
    save_config(cfg, config_path)
    return cfg


def save_config(config, config_path):
    """Guarda la configuración en formato YAML (o JSON como fallback)."""
    p = Path(config_path)
    try:
        if HAS_YAML:
            with open(p, "w", encoding="utf-8") as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        else:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[ERROR] No se pudo guardar la configuración en '{config_path}': {e}")
        return False


def print_config_summary(config):
    """Muestra en consola un resumen visual estructurado de los parámetros activos."""
    scen = config.get("scenario", "ssp585")
    obs = config.get("observations", {})
    obs_t = obs.get("temperature", "ERA5")
    obs_p = obs.get("precipitation", "GPCP")
    
    regs = config.get("regions", {})
    reg_p = regs.get("primary", {})
    p_name = reg_p.get("name", "Central America/Mexico [CAM:6]")
    p_weight = float(reg_p.get("weight", 1.0))
    
    reg_s = regs.get("secondary", {})
    s_enabled = bool(reg_s.get("enabled", False))
    s_name = reg_s.get("name", "Desactivada")
    s_weight = float(reg_s.get("weight", 0.3)) if s_enabled else 0.0

    total_w = p_weight + s_weight
    p_pct = (p_weight / total_w) * 100 if total_w > 0 else 100
    s_pct = (s_weight / total_w) * 100 if total_w > 0 else 0

    metrics = config.get("metrics_weights", {})
    w_bias = float(metrics.get("bias", 1.0))
    w_sd = float(metrics.get("std_dev", 1.0))
    w_corr = float(metrics.get("correlation", 1.0))
    w_rmse = float(metrics.get("rmse", 1.0))

    n_exp = len(config.get("experiments", {}))

    print("=" * 75)
    print(" CONFIGURACIÓN ACTIVA DE EVALUACIÓN CLIMATOLÓGICA (GCMEVAL)")
    print("=" * 75)
    print(f" [1] Escenario / Forzamiento : {scen} (Período base historical 1981-2014)")
    print(f" [2] Observaciones de Ref.   : Temp: {obs_t} | Prec: {obs_p}")
    print(f" [3] Región Primaria         : {p_name} ({p_pct:.1f}% del peso)")
    if s_enabled:
        print(f" [4] Región Secundaria       : {s_name} ({s_pct:.1f}% del peso) [ACTIVADA]")
    else:
        print(f" [4] Región Secundaria       : Desactivada (Solo región primaria)")
    print(f" [5] Ponderación de Métricas : Bias={w_bias:.1f} | Desv.Est={w_sd:.1f} | Corr={w_corr:.1f} | RMSE={w_rmse:.1f}")
    print(f" [6] Matriz de Sensibilidad  : {n_exp} Experimentos configurados (E0 a E{n_exp - 1})")
    print("=" * 75)


def interactive_config_wizard(config, config_path):
    """Asistente interactivo por consola para modificar los parámetros de evaluación."""
    print("\n--- ASISTENTE INTERACTIVO DE CONFIGURACIÓN ---")
    print("(Presiona ENTER en cualquier opción para mantener el valor actual)\n")

    # 1. Región Primaria
    print("Seleccione la Región Primaria:")
    for idx, reg in enumerate(AVAILABLE_REGIONS, 1):
        curr_mark = " (Actual)" if reg == config["regions"]["primary"]["name"] else ""
        print(f"  [{idx}] {reg}{curr_mark}")
    ans = input(f"Número de región primaria [1-{len(AVAILABLE_REGIONS)}]: ").strip()
    if ans.isdigit() and 1 <= int(ans) <= len(AVAILABLE_REGIONS):
        config["regions"]["primary"]["name"] = AVAILABLE_REGIONS[int(ans) - 1]

    # 2. Región Secundaria
    curr_s_en = config["regions"]["secondary"].get("enabled", False)
    s_prompt = "s" if curr_s_en else "n"
    ans_s = input(f"\n¿Desea activar un Dominio Secundario? (s/n) [{s_prompt}]: ").strip().lower()
    if ans_s in ("s", "si", "y", "yes"):
        config["regions"]["secondary"]["enabled"] = True
        print("\nSeleccione la Región Secundaria:")
        for idx, reg in enumerate(AVAILABLE_REGIONS, 1):
            curr_mark = " (Actual)" if reg == config["regions"]["secondary"]["name"] else ""
            print(f"  [{idx}] {reg}{curr_mark}")
        ans_reg_s = input(f"Número de región secundaria [1-{len(AVAILABLE_REGIONS)}]: ").strip()
        if ans_reg_s.isdigit() and 1 <= int(ans_reg_s) <= len(AVAILABLE_REGIONS):
            config["regions"]["secondary"]["name"] = AVAILABLE_REGIONS[int(ans_reg_s) - 1]
        
        curr_w_s = config["regions"]["secondary"].get("weight", 0.3)
        ans_w_s = input(f"Peso relativo del dominio secundario (0.1 a 1.0) [{curr_w_s}]: ").strip()
        try:
            if ans_w_s:
                config["regions"]["secondary"]["weight"] = float(ans_w_s)
        except ValueError:
            pass
    elif ans_s in ("n", "no"):
        config["regions"]["secondary"]["enabled"] = False

    # 3. Observaciones
    print(f"\nConjunto observacional para Temperatura {AVAILABLE_OBS_TEMP}:")
    curr_obs_t = config["observations"].get("temperature", "ERA5")
    ans_obs_t = input(f"Observación Temp [{curr_obs_t}]: ").strip().upper()
    if ans_obs_t in AVAILABLE_OBS_TEMP:
        config["observations"]["temperature"] = ans_obs_t

    print(f"\nConjunto observacional para Precipitación {AVAILABLE_OBS_PREC}:")
    curr_obs_p = config["observations"].get("precipitation", "GPCP")
    ans_obs_p = input(f"Observación Prec [{curr_obs_p}]: ").strip().upper()
    if ans_obs_p in AVAILABLE_OBS_PREC:
        config["observations"]["precipitation"] = ans_obs_p

    # Guardar en YAML
    save_config(config, config_path)
    print(f"\n[OK] Configuración actualizada y guardada con éxito en '{config_path}'.\n")
    return config


def find_rscript(custom_path=None):
    """
    Localiza el ejecutable 'Rscript' en el sistema de manera robusta y multiplataforma.

    Prioridad de búsqueda:
    1. Ruta personalizada provista por el usuario (--r-path).
    2. Variable de entorno RSCRIPT_PATH o R_HOME.
    3. Entorno activo Conda / Mamba / Virtualenv ($CONDA_PREFIX, $VIRTUAL_ENV).
    4. PATH del sistema operativo (shutil.which).
    5. Rutas estándar de instalación en Linux (/usr/bin, /usr/local/bin, /usr/lib/R/bin, /opt/R, etc.).
    6. Rutas estándar de instalación en macOS (/opt/homebrew/bin, /usr/local/Cellar, etc.).
    7. Rutas estándar de instalación en Windows (C:\\Program Files\\R\\R-*, AppData, etc.).
    """
    if custom_path:
        p = Path(custom_path)
        if p.is_file() and os.access(p, os.X_OK):
            return str(p.resolve())
        elif p.is_dir():
            cand = p / ("Rscript.exe" if sys.platform == "win32" else "Rscript")
            if cand.is_file():
                return str(cand.resolve())
        raise FileNotFoundError(f"No se encontró un ejecutable válido de R en la ruta especificada: '{custom_path}'")

    # 1. Variable de entorno RSCRIPT_PATH
    env_rscript = os.environ.get("RSCRIPT_PATH")
    if env_rscript and os.path.isfile(env_rscript):
        return os.path.abspath(env_rscript)

    # 2. Variable de entorno R_HOME
    r_home = os.environ.get("R_HOME")
    if r_home:
        cand1 = Path(r_home) / "bin" / ("Rscript.exe" if sys.platform == "win32" else "Rscript")
        cand2 = Path(r_home) / "bin" / "x64" / "Rscript.exe"
        if cand1.is_file():
            return str(cand1.resolve())
        if cand2.is_file():
            return str(cand2.resolve())

    # 3. Entorno activo Conda / Mamba / Virtualenv
    for env_var in ("CONDA_PREFIX", "MAMBA_ROOT_PREFIX", "VIRTUAL_ENV"):
        prefix = os.environ.get(env_var)
        if prefix:
            cand = Path(prefix) / ("Scripts/Rscript.exe" if sys.platform == "win32" else "bin/Rscript")
            if cand.is_file():
                return str(cand.resolve())

    # 4. Búsqueda directa en el PATH del sistema
    which_r = shutil.which("Rscript") or shutil.which("Rscript.exe")
    if which_r:
        return os.path.abspath(which_r)

    # Fallback si en el PATH solo está 'R' y no 'Rscript' directamente
    which_r_bin = shutil.which("R")
    if which_r_bin:
        cand = Path(which_r_bin).parent / ("Rscript.exe" if sys.platform == "win32" else "Rscript")
        if cand.is_file():
            return str(cand.resolve())

    # 5. Búsqueda en rutas estándar de Windows
    if sys.platform == "win32":
        search_patterns = [
            r"C:\Program Files\R\R-*\bin\Rscript.exe",
            r"C:\Program Files\R\R-*\bin\x64\Rscript.exe",
            r"C:\Program Files (x86)\R\R-*\bin\Rscript.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\R\R-*\bin\Rscript.exe"),
            os.path.expanduser(r"~\miniforge3\envs\*\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\miniforge3\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\miniconda3\envs\*\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\miniconda3\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\anaconda3\envs\*\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\anaconda3\Scripts\Rscript.exe"),
            os.path.expanduser(r"~\.conda\envs\*\Scripts\Rscript.exe"),
        ]
        candidates = []
        for pat in search_patterns:
            candidates.extend(glob.glob(pat))
        if candidates:
            candidates.sort(reverse=True)
            return os.path.abspath(candidates[0])

    # 6. Búsqueda exhaustiva en rutas estándar de Linux y macOS / Unix
    else:
        unix_search_patterns = [
            # Paquetes del sistema estándar (Debian, Ubuntu, Rocky, RHEL, CentOS, Fedora, Arch, openSUSE)
            "/usr/bin/Rscript",
            "/usr/local/bin/Rscript",
            "/usr/lib/R/bin/Rscript",
            "/usr/lib64/R/bin/Rscript",
            # Rutas de instalación manual o módulos
            "/opt/R/*/bin/Rscript",
            "/opt/R/bin/Rscript",
            "/opt/local/bin/Rscript",
            "/opt/homebrew/bin/Rscript",
            "/usr/local/Cellar/r/*/bin/Rscript",
            # Nix / Spack / Guix / Entornos de usuario
            os.path.expanduser("~/.nix-profile/bin/Rscript"),
            "/nix/var/nix/profiles/default/bin/Rscript",
            os.path.expanduser("~/.local/bin/Rscript"),
            # Gestores de entornos científicos (Conda, Miniforge, Mamba)
            os.path.expanduser("~/miniforge3/bin/Rscript"),
            os.path.expanduser("~/miniforge3/envs/*/bin/Rscript"),
            os.path.expanduser("~/miniconda3/bin/Rscript"),
            os.path.expanduser("~/miniconda3/envs/*/bin/Rscript"),
            os.path.expanduser("~/anaconda3/bin/Rscript"),
            os.path.expanduser("~/anaconda3/envs/*/bin/Rscript"),
            os.path.expanduser("~/micromamba/bin/Rscript"),
            os.path.expanduser("~/micromamba/envs/*/bin/Rscript"),
            os.path.expanduser("~/.conda/envs/*/bin/Rscript"),
            # Servidores y clusters HPC
            "/software/R/*/bin/Rscript",
            "/software/apps/R/*/bin/Rscript",
            "/apps/R/*/bin/Rscript",
        ]
        candidates = []
        for pat in unix_search_patterns:
            candidates.extend(glob.glob(pat))
        if candidates:
            candidates.sort(reverse=True)
            return os.path.abspath(candidates[0])

    return None


def check_r_packages(rscript_exe, auto_install=False):
    """
    Verifica si los paquetes de R necesarios para la evaluación están instalados.
    Soporta la instalación inteligente en Conda (binarios pre-compilados sin necesidad de compilar fuentes C++)
    y la instalación del paquete local 'gcmeval' desde el subdirectorio 'gcmeval/back-end'.
    """
    repo_root = Path(__file__).parent.resolve()
    backend_dir = repo_root / "gcmeval" / "back-end"
    
    check_code = (
        'req_cran <- c("ncdf4", "raster", "RCurl", "sf", "sp", "zoo", "ggplot2", "plotly", "htmlwidgets", "DT", "fields", "plotrix"); '
        'installed <- rownames(installed.packages()); '
        'missing_cran <- req_cran[!req_cran %in% installed]; '
        'has_gcmeval <- "gcmeval" %in% installed; '
        'cat(paste("CRAN_MISSING:", paste(missing_cran, collapse=","), "\n")); '
        'cat(paste("GCMEVAL_INSTALLED:", has_gcmeval, "\n"))'
    )
    
    try:
        res = subprocess.run(
            [rscript_exe, "-e", check_code],
            capture_output=True,
            text=True,
            check=True
        )
        output = res.stdout.strip()
        missing_cran = []
        gcmeval_installed = True
        
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("CRAN_MISSING:"):
                val = line.split("CRAN_MISSING:")[1].strip()
                if val:
                    missing_cran = [p.strip() for p in val.split(",") if p.strip()]
            elif line.startswith("GCMEVAL_INSTALLED:"):
                val = line.split("GCMEVAL_INSTALLED:")[1].strip()
                gcmeval_installed = (val.lower() == "true")

        if not missing_cran and gcmeval_installed:
            print("[OK] Todas las dependencias de R requeridas están instaladas.")
            return True

        missing_all = list(missing_cran)
        if not gcmeval_installed:
            missing_all.append("gcmeval")

        print(f"[AVISO] Faltan los siguientes paquetes de R: {', '.join(missing_all)}")

        # Detectar si R se ejecuta dentro de un entorno Conda / Mamba
        rscript_lower = str(rscript_exe).lower()
        is_conda_env = "conda" in rscript_lower or "miniconda" in rscript_lower or "miniforge" in rscript_lower or "envs" in rscript_lower or "CONDA_PREFIX" in os.environ
        conda_bin = shutil.which("mamba") or shutil.which("conda")

        if auto_install:
            success = True
            # 1. Si estamos en Conda y faltan paquetes CRAN, intentar instalar vía conda-forge (evita errores de compilación C++)
            if missing_cran:
                if is_conda_env and conda_bin:
                    conda_pkgs = [f"r-{p.lower()}" for p in missing_cran]
                    print(f"[INFO] Instalando paquetes binarios desde conda-forge con {os.path.basename(conda_bin)}: {conda_pkgs}...")
                    c_res = subprocess.run([conda_bin, "install", "-y", "-c", "conda-forge"] + conda_pkgs)
                    if c_res.returncode != 0:
                        print("[AVISO] Falló la instalación vía conda, intentando con install.packages() de R...")
                        install_code = f'install.packages(c({", ".join([repr(p) for p in missing_cran])}), repos="https://cloud.r-project.org")'
                        inst_res = subprocess.run([rscript_exe, "-e", install_code])
                        if inst_res.returncode != 0:
                            success = False
                else:
                    print(f"[INFO] Instalando paquetes CRAN desde R: {missing_cran}...")
                    install_code = f'install.packages(c({", ".join([repr(p) for p in missing_cran])}), repos="https://cloud.r-project.org")'
                    inst_res = subprocess.run([rscript_exe, "-e", install_code])
                    if inst_res.returncode != 0:
                        success = False

            # 2. Instalar paquete local 'gcmeval'
            if not gcmeval_installed:
                if backend_dir.is_dir():
                    backend_r_path = str(backend_dir.as_posix())
                    print(f"[INFO] Instalando paquete local 'gcmeval' desde '{backend_r_path}'...")
                    install_local_code = f'install.packages("{backend_r_path}", repos = NULL, type = "source")'
                    inst_local_res = subprocess.run([rscript_exe, "-e", install_local_code])
                    if inst_local_res.returncode != 0:
                        print("[ERROR] No se pudo instalar el paquete local 'gcmeval'.")
                        success = False
                else:
                    print(f"[ERROR] No se encontró el directorio de desarrollo 'gcmeval/back-end' en '{backend_dir}'.")
                    success = False

            return success
        else:
            print("\n[GUÍA DE INSTALACIÓN DE DEPENDENCIAS]")
            if is_conda_env:
                conda_pkgs = [f"r-{p.lower()}" for p in missing_cran]
                print("• Recomendado para Linux / Conda (instala binarios pre-compilados sin requerir cmake):")
                print(f"    conda install -y -c conda-forge {' '.join(conda_pkgs)}")
                if not gcmeval_installed:
                    print("    Rscript -e \"install.packages('gcmeval/back-end', repos=NULL, type='source')\"")
            else:
                if missing_cran:
                    print(f"• Desde R (CRAN): install.packages(c({', '.join([repr(p) for p in missing_cran])}))")
                if not gcmeval_installed:
                    print("• Paquete local gcmeval: Rscript -e \"install.packages('gcmeval/back-end', repos=NULL, type='source')\"")
            print("• O ejecuta automáticamente: python run_evaluation.py --install-deps\n")
            return False
    except Exception as e:
        print(f"[AVISO] No se pudo verificar la lista de paquetes de R: {e}")
        return True


def run_evaluation(rscript_exe, script_path, models_csv=None, output_dir=None, config=None):
    """
    Ejecuta el script de evaluación R con streaming de salida en tiempo real,
    pasando los parámetros de configuración en formato JSON temporal.
    """
    repo_root = Path(__file__).parent.resolve()
    target_script = Path(script_path)
    if not target_script.is_absolute():
        target_script = (repo_root / target_script).resolve()

    if not target_script.is_file():
        raise FileNotFoundError(f"No se encontró el script de evaluación R: '{target_script}'")

    cmd = [rscript_exe, str(target_script)]
    
    # Exportar configuración temporal para consumo directo en R
    temp_json = repo_root / "evaluation_config.json"
    if config:
        with open(temp_json, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        cmd.extend(["--config", str(temp_json)])

    # Argumentos opcionales
    if models_csv:
        cmd.extend(["--models", str(models_csv)])
    if output_dir:
        cmd.extend(["--output-dir", str(output_dir)])

    print("\n" + "=" * 75)
    print("INICIANDO EVALUACIÓN CLIMATOLÓGICA CON GCMEVAL (ORQUESTADOR PYTHON)")
    print("=" * 75)
    print(f"Ejecutable Rscript : {rscript_exe}")
    print(f"Script R           : {target_script}")
    print(f"Directorio base    : {repo_root}")
    print("=" * 75)
    print()

    # Ejecutar con streaming de salida en vivo
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            universal_newlines=True
        )

        for line in iter(process.stdout.readline, ''):
            print(line, end='', flush=True)

        process.stdout.close()
        return_code = process.wait()
    finally:
        # Limpiar archivo temporal JSON
        if temp_json.exists():
            try:
                temp_json.unlink()
            except Exception:
                pass

    if return_code != 0:
        print(f"\n[ERROR] El proceso de evaluación en R finalizó con código de error {return_code}.")
        sys.exit(return_code)

    print("\n" + "=" * 75)
    print("EVALUACIÓN Y RANKING COMPLETADOS CON ÉXITO")
    print("=" * 75)
    
    results_dir = repo_root / "results"
    if results_dir.exists():
        print(f"\nArtefactos generados en '{results_dir}':")
        for f in sorted(results_dir.glob("*")):
            size_kb = f.stat().st_size / 1024.0
            print(f"  • {f.name:36s} ({size_kb:7.1f} KB)")
    print("=" * 75)
    print()
    print("=" * 75)
    print("SIGUIENTE PASO RECOMENDADO")
    print("=" * 75)
    print("Para generar el manifiesto técnico y catálogo de descarga NetCDF de los")
    print("10 modelos seleccionados (cmip6_manifest.tsv), ejecuta:")
    print("   python generate_manifest.py")
    print("=" * 75)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Orquestador en Python para la Evaluación Climatológica CMIP6 con GCMEval"
    )
    parser.add_argument(
        "--config",
        default="evaluation_config.yaml",
        help="Ruta al archivo de configuración YAML/JSON (por defecto: evaluation_config.yaml)"
    )
    parser.add_argument(
        "-y", "--yes", "--non-interactive",
        action="store_true",
        dest="non_interactive",
        help="Ejecuta directamente sin solicitar confirmación interactiva"
    )
    parser.add_argument(
        "--wizard", "--configure",
        action="store_true",
        dest="wizard",
        help="Inicia el asistente interactivo para modificar los parámetros de evaluación"
    )
    parser.add_argument(
        "--r-path",
        default=None,
        help="Ruta explícita al ejecutable Rscript o al directorio de instalación de R"
    )
    parser.add_argument(
        "--script",
        default="gcmeval/run_cmip6_evaluation.R",
        help="Ruta al script de evaluación R (por defecto: gcmeval/run_cmip6_evaluation.R)"
    )
    parser.add_argument(
        "--models-csv",
        default=None,
        help="Ruta a un archivo CSV alternativo con la lista de modelos a evaluar"
    )
    parser.add_argument(
        "--install-deps",
        action="store_true",
        help="Instala automáticamente las librerías de R faltantes antes de ejecutar"
    )

    args = parser.parse_args()

    # 1. Cargar o crear configuración de evaluación
    config = load_or_create_config(args.config)

    # 2. Manejo de asistente interactivo o confirmación por consola
    if args.wizard:
        config = interactive_config_wizard(config, args.config)
        print_config_summary(config)
    elif not args.non_interactive:
        print_config_summary(config)
        try:
            prompt_msg = " ¿Deseas ejecutar la evaluación con estos parámetros? [S/n / (c)onfigurar]: "
            user_choice = input(prompt_msg).strip().lower()
            if user_choice in ("c", "config", "configurar"):
                config = interactive_config_wizard(config, args.config)
                print_config_summary(config)
            elif user_choice in ("n", "no"):
                print("\n[INFO] Ejecución cancelada por el usuario.")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print("\n[INFO] Cancelado por el usuario.")
            sys.exit(0)
    else:
        print_config_summary(config)

    # 3. Detectar ejecutable Rscript
    rscript_exe = find_rscript(args.r_path)
    if not rscript_exe:
        print("[ERROR] No se pudo encontrar el ejecutable 'Rscript' en el sistema.")
        print()
        print("Instrucciones de instalación según tu sistema operativo:")
        print("  • Ubuntu / Debian:")
        print("       sudo apt-get update && sudo apt-get install -y r-base r-base-dev")
        print("  • RedHat / Rocky Linux / CentOS / Fedora:")
        print("       sudo dnf install -y epel-release && sudo dnf install -y R-core R-devel")
        print("  • Entorno Conda / Mamba (Linux / Windows / macOS):")
        print("       conda install -y -c conda-forge r-base")
        print("  • Windows:")
        print("       Descarga el instalador desde CRAN: https://cran.r-project.org/bin/windows/base/")
        print("       O especifica la ruta manualmente:")
        print("       python run_evaluation.py --r-path \"C:\\Program Files\\R\\R-4.4.3\\bin\\Rscript.exe\"")
        print()
        sys.exit(1)

    print(f"\n[INFO] Ejecutable R detectado: {rscript_exe}")

    check_r_packages(rscript_exe, auto_install=args.install_deps)
    run_evaluation(rscript_exe, args.script, models_csv=args.models_csv, config=config)


if __name__ == "__main__":
    main()
