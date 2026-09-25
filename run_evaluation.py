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
import shutil
import argparse
import subprocess
from pathlib import Path

# Configurar salida estándar en UTF-8 para evitar errores de codificación en consola de Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


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


def run_evaluation(rscript_exe, script_path, models_csv=None, output_dir=None):
    """
    Ejecuta el script de evaluación R con streaming de salida en tiempo real.
    """
    repo_root = Path(__file__).parent.resolve()
    target_script = Path(script_path)
    if not target_script.is_absolute():
        target_script = (repo_root / target_script).resolve()

    if not target_script.is_file():
        raise FileNotFoundError(f"No se encontró el script de evaluación R: '{target_script}'")

    cmd = [rscript_exe, str(target_script)]
    
    # Argumentos opcionales
    if models_csv:
        cmd.extend(["--models", str(models_csv)])
    if output_dir:
        cmd.extend(["--output-dir", str(output_dir)])

    print("=" * 75)
    print("INICIANDO EVALUACIÓN CLIMATOLÓGICA CON GCMEVAL (ORQUESTADOR PYTHON)")
    print("=" * 75)
    print(f"Ejecutable Rscript : {rscript_exe}")
    print(f"Script R           : {target_script}")
    print(f"Directorio base    : {repo_root}")
    print("=" * 75)
    print()

    # Ejecutar con streaming de salida en vivo (UTF-8 con reemplazo de caracteres no válidos)
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

    print(f"[INFO] Ejecutable R detectado: {rscript_exe}")

    check_r_packages(rscript_exe, auto_install=args.install_deps)
    run_evaluation(rscript_exe, args.script, models_csv=args.models_csv)


if __name__ == "__main__":
    main()
