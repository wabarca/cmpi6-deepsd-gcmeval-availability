#!/usr/bin/env bash
# ==============================================================================
# CMIP6 Automated Downloader & CDO Preprocessor (Storage-Optimized)
# ==============================================================================
#
# Descripción:
# ------------
# Descarga y preprocesa los modelos CMIP6 seleccionados para el dominio de
# Centroamérica aplicando una estrategia de uso eficiente de espacio en disco:
#
#   1. Procesa de manera atómica cada combinación (Modelo, Experimento, Variable).
#   2. Descarga con aria2c únicamente los archivos temporales de esa variable.
#   3. Aplica recorte espacial (sellonlatbox), concatenación temporal (mergetime)
#      y selección del período temporal requerido (selyear).
#   4. Guarda el archivo consolidado y recortado en la carpeta del modelo.
#   5. Elimina INMEDIATAMENTE los archivos brutos y temporales, liberando el
#      espacio en disco antes de pasar a la siguiente variable.
#   6. Soporta reanudación automática (Resume): Si se interrumpe, continúa
#      exactamente donde se quedó omitiendo los archivos ya finalizados y válidos.
#
# Requisitos:
# -----------
#   - cdo (Climate Data Operators)
#   - aria2c
#   - sha256sum (o shasum)
#   - awk, curl
#
# Uso:
# ----
#   ./download_preprocess_cmip6.sh
#
#   O personalizando variables de entorno:
#   OUTPUT_DIR="/ruta/almacenamiento" CDO_THREADS=16 ./download_preprocess_cmip6.sh
#
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 1. Configuración General y Parámetros
# ------------------------------------------------------------------------------

# Archivo de manifiesto TSV generado con URLs y metadatos de los 12 modelos
MANIFEST="${MANIFEST:-cmip6_manifest_12_models.tsv}"

# Directorio final de almacenamiento de modelos procesados
OUTPUT_DIR="${OUTPUT_DIR:-./CMIP6_GCMs_Processed}"

# Directorio temporal de trabajo (se limpia automáticamente tras cada variable)
TEMP_DIR="${TEMP_DIR:-./tmp_cmip6_processing}"

# Coordenadas geográficas para recorte de Centroamérica (sellonlatbox)
LON_LEFT="${LON_LEFT:--120}"
LON_RIGHT="${LON_RIGHT:--40.5}"
LAT_DOWN="${LAT_DOWN:--18.5}"
LAT_UP="${LAT_UP:-43}"

# Hilos de procesamiento CDO (OpenMP)
CDO_THREADS="${CDO_THREADS:-8}"

# Conexiones simultáneas por descarga en aria2c
ARIA2_CONNECTIONS="${ARIA2_CONNECTIONS:-4}"

# Habilitar o deshabilitar limpieza inmediata de archivos raw temporales
CLEANUP_TEMP="${CLEANUP_TEMP:-true}"

# ------------------------------------------------------------------------------
# 2. Verificación de Dependencias
# ------------------------------------------------------------------------------

check_dependencies() {
    echo "======================================================================"
    echo " 1. VERIFICANDO DEPENDENCIAS DEL SISTEMA"
    echo "======================================================================"

    local missing=()
    for cmd in aria2c cdo awk curl; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    # Comprobar utilidad de checksum (sha256sum o shasum)
    if ! command -v sha256sum &> /dev/null && ! command -v shasum &> /dev/null; then
        missing+=("sha256sum/shasum")
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        echo ""
        echo "[ERROR CRÍTICO] Faltan herramientas necesarias para ejecutar el pipeline:"
        echo ""
        for tool in "${missing[@]}"; do
            echo "   ❌ $tool"
        done
        echo ""
        echo "Instrucciones de instalación recomendadas:"
        echo "  - Entorno Conda / Mamba (Recomendado):"
        echo "      conda install -c conda-forge cdo aria2 curl coreutils"
        echo "  - Ubuntu / Debian Linux:"
        echo "      sudo apt-get update && sudo apt-get install -y cdo aria2 curl coreutils"
        echo "  - RedHat / CentOS / Rocky Linux:"
        echo "      sudo dnf install -y epel-release && sudo dnf install -y cdo aria2 curl coreutils"
        echo "======================================================================"
        exit 1
    fi

    echo " [OK] Todas las herramientas requeridas están disponibles:"
    echo "      - cdo      : $(cdo -V 2>&1 | head -n 1)"
    echo "      - aria2c   : $(aria2c -v 2>&1 | head -n 1)"
    echo "      - curl     : $(curl --version 2>&1 | head -n 1)"
    echo "======================================================================"
    echo ""
}

# ------------------------------------------------------------------------------
# 3. Función Auxiliar de Cálculo de Checksum
# ------------------------------------------------------------------------------

compute_sha256() {
    local file="$1"
    if command -v sha256sum &> /dev/null; then
        sha256sum "$file" | awk '{print $1}'
    else
        shasum -a 256 "$file" | awk '{print $1}'
    fi
}

# ------------------------------------------------------------------------------
# 4. Pipeline Principal de Descarga y Preprocesamiento
# ------------------------------------------------------------------------------

main() {
    check_dependencies

    if [ ! -f "$MANIFEST" ]; then
        echo "[ERROR] No se encontró el archivo de manifiesto '$MANIFEST'."
        echo "Asegúrate de ejecutar primero el script de generación de manifiesto:"
        echo "  python generate_manifest_12.py"
        exit 1
    fi

    mkdir -p "$OUTPUT_DIR"
    mkdir -p "$TEMP_DIR"

    echo "======================================================================"
    echo " PIPELINE CMIP6: DESCARGA + PREPROCESAMIENTO CDO (DOMINIO CA)"
    echo "======================================================================"
    echo " Manifiesto           : $MANIFEST"
    echo " Carpeta de salida    : $OUTPUT_DIR"
    echo " Carpeta temporal     : $TEMP_DIR"
    echo " Dominio sellonlatbox : [lon: $LON_LEFT a $LON_RIGHT, lat: $LAT_DOWN a $LAT_UP]"
    echo " Hilos CDO (-P)       : $CDO_THREADS"
    echo " Conexiones aria2c    : $ARIA2_CONNECTIONS"
    echo "======================================================================"
    echo ""

    # Extraer combinaciones únicas de (source_id, variant_label, experiment_id, variable_id)
    # Columnas TSV: 1:source_id, 2:variant_label, 3:experiment_id, 4:variable_id, 5:file_name, 6:https_url, 7:checksum, 8:checksum_type, 9:file_size_mb, 10:data_node
    mapfile -t COMBOS < <(tail -n +2 "$MANIFEST" | awk -F'\t' '{print $1"\t"$2"\t"$3"\t"$4}' | sort -u)

    total_combos=${#COMBOS[@]}
    current_idx=0
    skipped_count=0
    processed_count=0

    echo "Total de combinaciones dataset a procesar: $total_combos"
    echo ""

    for combo in "${COMBOS[@]}"; do
        ((current_idx++))
        IFS=$'\t' read -r model variant exp var <<< "$combo"

        # Determinar el rango temporal esperado según el experimento
        if [ "$exp" == "historical" ]; then
            period_label="19500101-20141231"
            selyear_range="1950/2014"
        else
            period_label="20150101-21001231"
            selyear_range="2015/2100"
        fi

        # Directorio del modelo de salida
        model_out_dir="${OUTPUT_DIR}/${model}"
        mkdir -p "$model_out_dir"

        final_file="${model_out_dir}/${var}_day_${model}_${exp}_${variant}_${period_label}.nc"

        echo "----------------------------------------------------------------------"
        echo "[$current_idx/$total_combos] Modelo: $model | Variante: $variant | Exp: $exp | Var: $var"

        # ----------------------------------------------------------------------
        # A. Comprobación de Reanudación (Resume / Idempotencia)
        # ----------------------------------------------------------------------
        if [ -f "$final_file" ] && [ -s "$final_file" ]; then
            # Verificar si el archivo es un NetCDF válido
            if cdo -s sinfo "$final_file" &> /dev/null; then
                file_size_h=$(du -h "$final_file" | cut -f1)
                echo " [OMITIDO] El archivo final ya existe y es válido ($file_size_h):"
                echo "           $final_file"
                ((skipped_count++))
                continue
            else
                echo " [AVISO] Archivo existente corrupto o incompleto. Se reprocesará:"
                echo "         $final_file"
                rm -f "$final_file"
            fi
        fi

        # ----------------------------------------------------------------------
        # B. Preparar Entorno Temporal para la Variable Actual
        # ----------------------------------------------------------------------
        var_temp_dir="${TEMP_DIR}/${model}/${exp}/${var}"
        raw_dir="${var_temp_dir}/raw"
        clipped_dir="${var_temp_dir}/clipped"

        rm -rf "$var_temp_dir"
        mkdir -p "$raw_dir"
        mkdir -p "$clipped_dir"

        # Generar lista de descargas para aria2c
        aria2_input="${var_temp_dir}/downloads.txt"
        > "$aria2_input"

        # Filtrar los archivos de esta combinación desde el manifiesto TSV
        tail -n +2 "$MANIFEST" | awk -F'\t' -v m="$model" -v v="$variant" -v e="$exp" -v va="$var" '
            $1 == m && $2 == v && $3 == e && $4 == va {
                print $5"\t"$6"\t"$7"\t"$8"\t"$9
            }
        ' | while IFS=$'\t' read -r fname url chk chk_type sz; do
            echo "$url" >> "$aria2_input"
            echo "  dir=$raw_dir" >> "$aria2_input"
            echo "  out=$fname" >> "$aria2_input"
            if [ -n "$chk" ] && [ "$chk" != "None" ] && [ "$chk_type" == "SHA256" ]; then
                echo "  checksum=sha-256=$chk" >> "$aria2_input"
            fi
        done

        num_chunks=$(grep -c "^http" "$aria2_input" || true)
        if [ "$num_chunks" -eq 0 ]; then
            echo " [ERROR] No se encontraron archivos en el manifiesto para $model $exp $var."
            continue
        fi

        echo " [1/4 DESCARGA] Descargando $num_chunks archivos NetCDF con aria2c..."

        aria2c \
            --input-file="$aria2_input" \
            --max-concurrent-downloads=4 \
            --max-connection-per-server="$ARIA2_CONNECTIONS" \
            --split="$ARIA2_CONNECTIONS" \
            --min-split-size=1M \
            --auto-file-renaming=false \
            --allow-overwrite=true \
            --conditional-get=true \
            --timeout=60 \
            --max-tries=5 \
            --retry-wait=3 \
            --console-log-level=warn \
            --summary-interval=10

        # ----------------------------------------------------------------------
        # C. Recorte Espacial (sellonlatbox) por cada Chunk
        # ----------------------------------------------------------------------
        echo " [2/4 RECORTE] Aplicando sellonlatbox [$LON_LEFT,$LON_RIGHT,$LAT_DOWN,$LAT_UP]..."
        raw_files=("$raw_dir"/*.nc)

        if [ ! -e "${raw_files[0]}" ]; then
            echo " [ERROR] No se encontraron archivos descargados en $raw_dir."
            continue
        fi

        for r_file in "${raw_files[@]}"; do
            fname=$(basename "$r_file")
            c_file="${clipped_dir}/${fname%.*}_clipped.nc"
            cdo -P "$CDO_THREADS" -s sellonlatbox,"$LON_LEFT","$LON_RIGHT","$LAT_DOWN","$LAT_UP" "$r_file" "$c_file"
        done

        # ----------------------------------------------------------------------
        # D. Concatenación Temporal (mergetime) y Selección de Período (selyear)
        # ----------------------------------------------------------------------
        echo " [3/4 MERGE & FECHAS] Concatenando series temporales y seleccionando años $selyear_range..."
        merged_temp="${var_temp_dir}/merged_all.nc"

        clipped_files=("$clipped_dir"/*.nc)
        if [ ${#clipped_files[@]} -eq 1 ]; then
            # Si solo hay un archivo, no requiere mergetime
            cp "${clipped_files[0]}" "$merged_temp"
        else
            cdo -P "$CDO_THREADS" -s mergetime "${clipped_dir}"/*.nc "$merged_temp"
        fi

        # Filtrar los años requeridos (1950-2014 para historical, 2015-2100 para SSPs)
        temp_final="${var_temp_dir}/final_processed.nc"
        cdo -P "$CDO_THREADS" -s selyear,"$selyear_range" "$merged_temp" "$temp_final"

        # Mover al destino final
        mv "$temp_final" "$final_file"

        # ----------------------------------------------------------------------
        # E. Limpieza Inmediata de Temporales (Ahorro de Espacio)
        # ----------------------------------------------------------------------
        if [ "$CLEANUP_TEMP" == "true" ]; then
            rm -rf "$var_temp_dir"
        fi

        file_size_final=$(du -h "$final_file" | cut -f1)
        echo " [4/4 COMPLETADO] ✅ Guardado exitosamente: $final_file ($file_size_final)"
        ((processed_count++))
    done

    # Limpiar directorio temporal global si quedó vacío
    rmdir "$TEMP_DIR" 2>/dev/null || true

    echo ""
    echo "======================================================================"
    echo " PROCESAMIENTO FINALIZADO EXITOSAMENTE"
    echo "======================================================================"
    echo " Total combinaciones evaluadas : $total_combos"
    echo " Nuevas procesadas             : $processed_count"
    echo " Omitidas (ya existentes)      : $skipped_count"
    echo " Directorio de salida          : $OUTPUT_DIR"
    echo "======================================================================"
    echo ""
}

main "$@"
