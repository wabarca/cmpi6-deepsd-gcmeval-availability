#!/usr/bin/env bash
# ==============================================================================
# CMIP6 Automated Downloader & CDO Preprocessor (Pipelined & Remote Sync)
# ==============================================================================
#
# Descripción:
# ------------
# Pipeline de alto rendimiento para descarga y preprocesamiento de modelos CMIP6:
#
#   1. Arquitectura Pipelined (Productor-Consumidor):
#      - Tan pronto termina la descarga de la variable N, se lanza su procesamiento
#        con CDO y posterior transferencia remota en segundo plano.
#      - Al mismo tiempo, se inicia inmediatamente la descarga de la variable N+1
#        con aria2c, eliminando tiempos muertos y saturando red y CPU a la vez.
#   2. Optimización multi-núcleo de CPU:
#      - Detecta y utiliza automáticamente todos los núcleos disponibles ($(nproc)).
#   3. Transferencia Remota Automática a PC de Almacenamiento (SSH / rsync):
#      - Al finalizar el procesamiento CDO de cada archivo, se envía vía rsync/scp
#        a la PC de almacenamiento (192.168.4.27) en E:\CMIP6\CMIP6_GCMs_Processed.
#      - Recrea la estructura de carpetas por modelo en el destino remoto.
#      - Tras verificar la transferencia, elimina inmediatamente los archivos
#        locales (raw y procesados) para mantener el disco de la PC de descarga limpio.
#   4. Reanudación Inteligente (Resume):
#      - Verifica si el archivo ya existe en la máquina remota o local antes de descargar.
#   5. Ejecución persistente en segundo plano (vía ./run_background.sh o tmux).
#
# Requisitos:
# -----------
#   - cdo (Climate Data Operators)
#   - aria2c
#   - sha256sum (o shasum)
#   - rsync (o scp), ssh, awk, curl, tr
#
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# 1. Configuración General y Parámetros
# ------------------------------------------------------------------------------

# Archivo de manifiesto TSV (por defecto cmip6_manifest.tsv o cmip6_manifest_10_models.tsv)
if [ -z "${MANIFEST:-}" ]; then
    if [ -f "cmip6_manifest.tsv" ]; then
        MANIFEST="cmip6_manifest.tsv"
    elif [ -f "cmip6_manifest_10_models.tsv" ]; then
        MANIFEST="cmip6_manifest_10_models.tsv"
    else
        MANIFEST="cmip6_manifest.tsv"
    fi
fi

# Directorio temporal local de trabajo (se limpia automáticamente tras procesar)
TEMP_DIR="${TEMP_DIR:-./tmp_cmip6_pipeline}"

# Directorio local de salida (en caso de que la sincronización remota esté desactivada)
LOCAL_OUTPUT_DIR="${LOCAL_OUTPUT_DIR:-./CMIP6_GCMs_Processed}"

# ------------------------------------------------------------------------------
# Configuración Remota (PC de Almacenamiento con más espacio)
# ------------------------------------------------------------------------------
ENABLE_REMOTE_SYNC="${ENABLE_REMOTE_SYNC:-true}"
REMOTE_HOST="${REMOTE_HOST:-192.168.4.27}"
REMOTE_USER="${REMOTE_USER:-AMBIENTE\\wabarca}" # Dejar vacío si el usuario SSH coincide o está en ~/.ssh/config
REMOTE_DEST_DIR="${REMOTE_DEST_DIR:-E:/CMIP6/CMIP6_GCMs_Processed}"
REMOTE_SSH_PORT="${REMOTE_SSH_PORT:-22}"

# Eliminar archivo local procesado tras confirmarse la transferencia remota
CLEANUP_LOCAL_AFTER_SYNC="${CLEANUP_LOCAL_AFTER_SYNC:-true}"

# ------------------------------------------------------------------------------
# Tolerancia a Fallos y Reintentos Automáticos
# ------------------------------------------------------------------------------
MAX_DOWNLOAD_RETRIES="${MAX_DOWNLOAD_RETRIES:-3}"
FAILED_LOG="${FAILED_LOG:-failed_combinations.tsv}"

# ------------------------------------------------------------------------------
# Períodos de Interés Configurables (Personalizables según el proyecto)
# ------------------------------------------------------------------------------
HISTORICAL_START_YEAR="${HISTORICAL_START_YEAR:-1950}"
HISTORICAL_END_YEAR="${HISTORICAL_END_YEAR:-2014}"
SSP_START_YEAR="${SSP_START_YEAR:-2015}"
SSP_END_YEAR="${SSP_END_YEAR:-2100}"

# ------------------------------------------------------------------------------
# Parámetros de Recorte CDO y Rendimiento
# ------------------------------------------------------------------------------
# Coordenadas geográficas para recorte de Centroamérica (sellonlatbox)
LON_LEFT="${LON_LEFT:--120}"
LON_RIGHT="${LON_RIGHT:--40.5}"
LAT_DOWN="${LAT_DOWN:--18.5}"
LAT_UP="${LAT_UP:-43}"

# Detectar automáticamente todos los núcleos de CPU disponibles para CDO
CDO_THREADS="${CDO_THREADS:-$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 8)}"

# Conexiones simultáneas por descarga en aria2c
ARIA2_CONNECTIONS="${ARIA2_CONNECTIONS:-4}"
MAX_CONCURRENT_DOWNLOADS="${MAX_CONCURRENT_DOWNLOADS:-4}"

# Límite de ancho de banda (0 = libre / ilimitado al máximo)
MAX_DOWNLOAD_LIMIT="${MAX_DOWNLOAD_LIMIT:-0}"

# ------------------------------------------------------------------------------
# 2. Construir Identificador de Destino SSH
# ------------------------------------------------------------------------------
if [ -n "$REMOTE_USER" ]; then
    SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
else
    SSH_TARGET="${REMOTE_HOST}"
fi

# ------------------------------------------------------------------------------
# 3. Verificación de Dependencias
# ------------------------------------------------------------------------------

check_dependencies() {
    echo "======================================================================"
    echo " 1. VERIFICANDO DEPENDENCIAS DEL SISTEMA"
    echo "======================================================================"

    local missing=()
    for cmd in aria2c cdo awk curl tr ssh; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    # Comprobar utilidad de checksum (sha256sum o shasum)
    if ! command -v sha256sum &> /dev/null && ! command -v shasum &> /dev/null; then
        missing+=("sha256sum/shasum")
    fi

    # Comprobar rsync o scp para transferencia remota
    if [ "$ENABLE_REMOTE_SYNC" == "true" ]; then
        if ! command -v rsync &> /dev/null && ! command -v scp &> /dev/null; then
            missing+=("rsync/scp")
        fi
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
        echo "      mamba install -c conda-forge cdo aria2 curl rsync coreutils openssh -y"
        echo "  - Ubuntu / Debian Linux:"
        echo "      sudo apt-get update && sudo apt-get install -y cdo aria2 curl rsync coreutils openssh-client"
        echo "  - RedHat / CentOS / Rocky Linux:"
        echo "      sudo dnf install -y epel-release && sudo dnf install -y cdo aria2 curl rsync coreutils openssh-clients"
        echo "======================================================================"
        exit 1
    fi

    echo " [OK] Todas las herramientas requeridas están disponibles:"
    echo "      - cdo          : $(cdo -V 2>&1 | head -n 1)"
    echo "      - aria2c       : $(aria2c -v 2>&1 | head -n 1)"
    echo "      - ssh          : $(ssh -V 2>&1 | head -n 1)"
    echo "      - cdo threads  : $CDO_THREADS CPUs detectadas"
    echo "======================================================================"
    echo ""
}

# ------------------------------------------------------------------------------
# 4. Funciones de Transferencia Remota y Comprobación de Archivos
# ------------------------------------------------------------------------------

remote_file_exists() {
    local model="$1"
    local fname="$2"

    if [ "$ENABLE_REMOTE_SYNC" != "true" ]; then
        return 1
    fi

    # Comprobar en host remoto mediante SSH (compatible con Windows OpenSSH y Linux)
    if ssh -p "$REMOTE_SSH_PORT" -o ConnectTimeout=8 -o BatchMode=yes "$SSH_TARGET" \
       "cmd.exe /c if exist \"${REMOTE_DEST_DIR}\\${model}\\${fname}\" (exit 0) else (exit 1) >nul 2>&1 || powershell -NoProfile -Command \"if ((Get-Item -Path '${REMOTE_DEST_DIR}/${model}/${fname}' -ErrorAction SilentlyContinue).Length -gt 0) { exit 0 } else { exit 1 }\" >nul 2>&1 || test -s \"${REMOTE_DEST_DIR}/${model}/${fname}\" >/dev/null 2>&1" >/dev/null 2>&1; then
        return 0
    fi

    return 1
}

local_file_exists() {
    local model="$1"
    local fname="$2"
    local f_path="${LOCAL_OUTPUT_DIR}/${model}/${fname}"

    [ -f "$f_path" ] && [ -s "$f_path" ]
    return $?
}

transfer_and_cleanup() {
    local local_file="$1"
    local model="$2"
    local fname
    fname=$(basename "$local_file")

    if [ "$ENABLE_REMOTE_SYNC" == "true" ]; then
        echo " [TRANSFERENCIA] 🚀 Enviando $fname a ${SSH_TARGET}:${REMOTE_DEST_DIR}/${model}/ ..."

        # Crear carpeta remota de destino silenciosamente (compatible con Windows OpenSSH y Linux)
        ssh -p "$REMOTE_SSH_PORT" -o ConnectTimeout=10 "$SSH_TARGET" \
            "cmd.exe /c if not exist \"${REMOTE_DEST_DIR}\\${model}\" mkdir \"${REMOTE_DEST_DIR}\\${model}\" >nul 2>&1 || powershell -NoProfile -Command \"New-Item -ItemType Directory -Force -Path '${REMOTE_DEST_DIR}/${model}' | Out-Null\" >nul 2>&1 || mkdir -p \"${REMOTE_DEST_DIR}/${model}\" >/dev/null 2>&1" >/dev/null 2>&1 || true

        local transfer_success=false

        # 1. Transferencia nativa con scp (100% compatible con Windows OpenSSH sin requerir rsync en Windows)
        if command -v scp &>/dev/null; then
            if scp -P "$REMOTE_SSH_PORT" -o ConnectTimeout=30 -o BatchMode=yes "$local_file" "${SSH_TARGET}:\"${REMOTE_DEST_DIR}/${model}/${fname}\""; then
                transfer_success=true
            fi
        fi

        # 2. Fallback con rsync si scp no estuviera disponible
        if [ "$transfer_success" = false ] && command -v rsync &>/dev/null; then
            if rsync -avP --inplace -e "ssh -p $REMOTE_SSH_PORT -o ConnectTimeout=20" "$local_file" "${SSH_TARGET}:\"${REMOTE_DEST_DIR}/${model}/\"" >/dev/null 2>&1; then
                transfer_success=true
            fi
        fi

        if [ "$transfer_success" = true ]; then
            # Verificar que el archivo en el host remoto existe y es accesible
            local remote_valid=false
            if remote_file_exists "$model" "$fname"; then
                remote_valid=true
            fi

            if [ "$remote_valid" = true ]; then
                echo " [TRANSFERENCIA] ✅ Archivo $fname verificado en el almacenamiento remoto."
                # Limpiar archivo local procesado para liberar disco
                if [ "$CLEANUP_LOCAL_AFTER_SYNC" == "true" ]; then
                    rm -f "$local_file"
                    echo " [LIMPIEZA] 🗑️  Archivo local procesado eliminado ($fname)."
                fi
                return 0
            else
                echo " [ERROR TRANSFERENCIA] ⚠️ La transferencia reportó éxito pero el archivo remoto no se pudo verificar. Se conserva copia local."
                return 1
            fi
        else
            echo " [ERROR TRANSFERENCIA] ⚠️ No se pudo transferir $fname a ${SSH_TARGET}. Se conserva el archivo local en $local_file"
            return 1
        fi
    fi
}

# ------------------------------------------------------------------------------
# Validación de Integridad de Chunks NetCDF
# ------------------------------------------------------------------------------

validate_raw_chunks() {
    local raw_dir="$1"
    local expected_count="$2"

    local actual_files=("$raw_dir"/*.nc)
    if [ ! -e "${actual_files[0]}" ]; then
        return 1
    fi
    local actual_count=${#actual_files[@]}
    if [ "$actual_count" -ne "$expected_count" ]; then
        echo " [VALIDACIÓN ERROR] Se esperaban $expected_count chunks, pero solo hay $actual_count en $raw_dir."
        return 1
    fi

    # Comprobar que cada chunk sea un archivo NetCDF estructuralmente válido
    for r_file in "${actual_files[@]}"; do
        local f_sz
        f_sz=$(wc -c < "$r_file" 2>/dev/null || echo 0)
        if [ "$f_sz" -lt 1024 ]; then
            echo " [VALIDACIÓN ERROR] Archivo incompleto o vacío ($(basename "$r_file")): $f_sz bytes."
            return 1
        fi
        if ! cdo -s sinfo "$r_file" &>/dev/null; then
            echo " [VALIDACIÓN ERROR] Estructura NetCDF no válida o corrupta en $(basename "$r_file")."
            return 1
        fi
    done
    return 0
}

# ------------------------------------------------------------------------------
# 5. Worker de Procesamiento CDO (Se ejecuta en background mientras descarga el sig)
# ------------------------------------------------------------------------------

process_variable_worker() {
    local model="$1"
    local variant="$2"
    local exp="$3"
    local var="$4"
    local selyear_range="$5"
    local var_temp_dir="$6"
    local final_file="$7"

    local raw_dir="${var_temp_dir}/raw"
    local clipped_dir="${var_temp_dir}/clipped"
    local fname_final
    fname_final=$(basename "$final_file")

    echo " [CDO PROCESO] ⚙️  Iniciando CDO con $CDO_THREADS hilos para $model $exp $var..."

    # 1. Recorte espacial sellonlatbox y eliminación progresiva inmediata de brutos
    for r_file in "$raw_dir"/*.nc; do
        if [ -f "$r_file" ]; then
            fn=$(basename "$r_file")
            c_file="${clipped_dir}/${fn%.*}_clipped.nc"
            if ! cdo -P "$CDO_THREADS" -s sellonlatbox,"$LON_LEFT","$LON_RIGHT","$LAT_DOWN","$LAT_UP" "$r_file" "$c_file" 2>/dev/null; then
                echo " [CDO AVISO] Falló recorte con -P, reintentando modo estándar para $fn..."
                cdo -s sellonlatbox,"$LON_LEFT","$LON_RIGHT","$LAT_DOWN","$LAT_UP" "$r_file" "$c_file"
            fi
            # Eliminar el archivo bruto inmediatamente para no saturar disco
            rm -f "$r_file"
        fi
    done
    rm -rf "$raw_dir"

    # 2. Concatenación temporal (mergetime)
    local merged_temp="${var_temp_dir}/merged_all.nc"
    local clipped_files=("$clipped_dir"/*.nc)

    if [ ${#clipped_files[@]} -eq 1 ]; then
        mv "${clipped_files[0]}" "$merged_temp"
    else
        if ! cdo -P "$CDO_THREADS" -s mergetime "${clipped_dir}"/*.nc "$merged_temp" 2>/dev/null; then
            cdo -s mergetime "${clipped_dir}"/*.nc "$merged_temp"
        fi
    fi
    # Eliminar recortes individuales inmediatamente tras mergetime
    rm -rf "$clipped_dir"

    # 3. Selección de período (selyear)
    local temp_final="${var_temp_dir}/${fname_final}"
    if ! cdo -P "$CDO_THREADS" -s selyear,"$selyear_range" "$merged_temp" "$temp_final" 2>/dev/null; then
        cdo -s selyear,"$selyear_range" "$merged_temp" "$temp_final"
    fi
    # Eliminar merged_temp inmediatamente tras selyear
    rm -f "$merged_temp"

    # 4. Verificar que el NetCDF final sea válido
    if cdo -s sinfo "$temp_final" &>/dev/null; then
        mkdir -p "$(dirname "$final_file")"
        mv "$temp_final" "$final_file"
        local f_sz
        f_sz=$(du -h "$final_file" 2>/dev/null | cut -f1 || echo "OK")
        echo " [CDO PROCESO] ✅ CDO completado para $fname_final ($f_sz)"

        # Purgar carpeta temporal completa inmediatamente tras generar el archivo final
        rm -rf "$var_temp_dir"

        # Transferir a PC de almacenamiento
        transfer_and_cleanup "$final_file" "$model"
    else
        echo " [ERROR CRÍTICO] El archivo generado para $model $exp $var no es un NetCDF válido."
        rm -rf "$var_temp_dir"
        return 1
    fi
}

# ------------------------------------------------------------------------------
# 6. Pipeline Principal Pipelined (Descarga N+1 en paralelo con Procesamiento N)
# ------------------------------------------------------------------------------

main() {
    check_dependencies

    if [ ! -f "$MANIFEST" ]; then
        echo "[ERROR] No se encontró el archivo de manifiesto '$MANIFEST'."
        echo "Asegúrate de ejecutar primero: python generate_manifest_10.py"
        exit 1
    fi

    mkdir -p "$LOCAL_OUTPUT_DIR"
    mkdir -p "$TEMP_DIR"

    # Purgar temporales huérfanos de ejecuciones previas interrumpidas
    if [ -d "$TEMP_DIR" ]; then
        echo " [LIMPIEZA INICIAL] 🧹 Purgando archivos temporales residuales en $TEMP_DIR..."
        rm -rf "${TEMP_DIR:?}"/* 2>/dev/null || true
    fi

    echo "======================================================================"
    echo " PIPELINE CMIP6 PIPELINED: DESCARGA + CDO MULTI-CORE + SYNC REMOTO"
    echo "======================================================================"
    echo " Manifiesto           : $MANIFEST"
    echo " Hilos CDO (-P)       : $CDO_THREADS CPUs (Máximo rendimiento)"
    echo " Dominio sellonlatbox : [lon: $LON_LEFT a $LON_RIGHT, lat: $LAT_DOWN a $LAT_UP]"
    echo " Período Historical   : $HISTORICAL_START_YEAR a $HISTORICAL_END_YEAR"
    echo " Período Escenarios   : $SSP_START_YEAR a $SSP_END_YEAR"
    echo " Límite ancho banda   : $([ "$MAX_DOWNLOAD_LIMIT" == "0" ] && echo "Libre / Sin límite" || echo "$MAX_DOWNLOAD_LIMIT")"
    if [ "$ENABLE_REMOTE_SYNC" == "true" ]; then
        echo " Sincronización SSH   : ACTIVADA"
        echo " Destino remoto       : ${SSH_TARGET}:${REMOTE_DEST_DIR}"
    else
        echo " Sincronización SSH   : DESACTIVADA (Guardando localmente en $LOCAL_OUTPUT_DIR)"
    fi
    echo "======================================================================"
    echo ""

    # Extraer combinaciones únicas de (source_id, variant_label, experiment_id, variable_id)
    mapfile -t COMBOS < <(tail -n +2 "$MANIFEST" | tr -d '\r' | awk -F'\t' '{print $1"\t"$2"\t"$3"\t"$4}' | sort -u)

    total_combos=${#COMBOS[@]}
    current_idx=0
    skipped_count=0
    processed_count=0

    echo "Total de combinaciones dataset a procesar: $total_combos"
    echo ""

    # PID del worker de procesamiento en background
    BG_PROC_PID=""

    for combo in "${COMBOS[@]}"; do
        current_idx=$((current_idx + 1))
        IFS=$'\t' read -r model variant exp var <<< "$combo"

        model=$(echo "$model" | tr -d '\r')
        variant=$(echo "$variant" | tr -d '\r')
        exp=$(echo "$exp" | tr -d '\r')
        var=$(echo "$var" | tr -d '\r')

        if [ "$exp" == "historical" ]; then
            period_label="${HISTORICAL_START_YEAR}0101-${HISTORICAL_END_YEAR}1231"
            selyear_range="${HISTORICAL_START_YEAR}/${HISTORICAL_END_YEAR}"
        else
            period_label="${SSP_START_YEAR}0101-${SSP_END_YEAR}1231"
            selyear_range="${SSP_START_YEAR}/${SSP_END_YEAR}"
        fi

        final_fname="${var}_day_${model}_${exp}_${variant}_${period_label}.nc"
        final_file="${LOCAL_OUTPUT_DIR}/${model}/${final_fname}"

        echo "----------------------------------------------------------------------"
        echo "[$current_idx/$total_combos] Modelo: $model | Variante: $variant | Exp: $exp | Var: $var"

        # ----------------------------------------------------------------------
        # A. Comprobación de Reanudación y Sincronización de Pendientes
        # ----------------------------------------------------------------------
        # 1. Si ya existe en el servidor remoto, omitir completamente
        if remote_file_exists "$model" "$final_fname"; then
            echo " [OMITIDO] El archivo ya existe en el almacenamiento remoto:"
            echo "           $final_fname"
            # Si quedó una copia local residual, limpiarla para liberar espacio
            if [ "$CLEANUP_LOCAL_AFTER_SYNC" == "true" ] && [ -f "$final_file" ]; then
                rm -f "$final_file"
            fi
            skipped_count=$((skipped_count + 1))
            continue
        fi

        # 2. Si ya existe localmente pero NO en el remoto:
        if local_file_exists "$model" "$final_fname"; then
            if [ "$ENABLE_REMOTE_SYNC" == "true" ]; then
                echo " [SINCRONIZACIÓN PENDIENTE] 🔄 Archivo ya procesado localmente. Transfiriendo a servidor remoto..."
                if transfer_and_cleanup "$final_file" "$model"; then
                    processed_count=$((processed_count + 1))
                fi
                continue
            else
                echo " [OMITIDO] El archivo ya existe localmente:"
                echo "           $final_fname"
                skipped_count=$((skipped_count + 1))
                continue
            fi
        fi

        # ----------------------------------------------------------------------
        # B. Preparar Entorno Temporal para Descarga
        # ----------------------------------------------------------------------
        var_temp_dir="${TEMP_DIR}/${model}_${exp}_${var}_${current_idx}"
        raw_dir="${var_temp_dir}/raw"
        clipped_dir="${var_temp_dir}/clipped"

        mkdir -p "$raw_dir"
        mkdir -p "$clipped_dir"

        aria2_input="${var_temp_dir}/downloads.txt"
        > "$aria2_input"

        tail -n +2 "$MANIFEST" | tr -d '\r' | awk -F'\t' -v m="$model" -v v="$variant" -v e="$exp" -v va="$var" '
            $1 == m && $2 == v && $3 == e && $4 == va {
                print $7"\t"$8"\t"$9"\t"$10"\t"$11
            }
        ' | while IFS=$'\t' read -r fname url chk chk_type sz; do
            fname=$(echo "$fname" | tr -d '\r')
            url=$(echo "$url" | tr -d '\r')
            chk=$(echo "$chk" | tr -d '\r')
            chk_type=$(echo "$chk_type" | tr -d '\r')

            echo "$url" >> "$aria2_input"
            echo "  dir=$raw_dir" >> "$aria2_input"
            echo "  out=$fname" >> "$aria2_input"
            if [ -n "$chk" ] && [ "$chk" != "None" ] && [ "$chk_type" == "SHA256" ]; then
                echo "  checksum=sha-256=$chk" >> "$aria2_input"
            fi
        done

        num_chunks=$(grep -c "^http" "$aria2_input" || true)
        if [ "$num_chunks" -eq 0 ]; then
            echo " [AVISO] No se encontraron archivos para $model $exp $var en el manifiesto."
            rm -rf "$var_temp_dir"
            continue
        fi

        local download_ok=false
        for attempt in $(seq 1 "$MAX_DOWNLOAD_RETRIES"); do
            echo " [1/3 DESCARGA] 📥 Descargando $num_chunks chunks con aria2c (Intento $attempt/$MAX_DOWNLOAD_RETRIES)..."

            aria2c \
                --input-file="$aria2_input" \
                --max-concurrent-downloads="$MAX_CONCURRENT_DOWNLOADS" \
                --max-connection-per-server="$ARIA2_CONNECTIONS" \
                --split="$ARIA2_CONNECTIONS" \
                --min-split-size=1M \
                --max-download-limit="$MAX_DOWNLOAD_LIMIT" \
                --auto-file-renaming=false \
                --allow-overwrite=true \
                --conditional-get=true \
                --timeout=60 \
                --max-tries=5 \
                --retry-wait=3 \
                --console-log-level=warn \
                --summary-interval=10 || true

            # Validar integridad estructural y completitud de los chunks descargados
            if validate_raw_chunks "$raw_dir" "$num_chunks"; then
                download_ok=true
                echo " [VALIDACIÓN OK] ✅ Todos los $num_chunks chunks NetCDF son íntegros y válidos."
                break
            else
                echo " [ADVERTENCIA] Falló la validación de chunks en el intento $attempt/$MAX_DOWNLOAD_RETRIES."
                if [ "$attempt" -lt "$MAX_DOWNLOAD_RETRIES" ]; then
                    local backoff_sec=$((attempt * 10))
                    echo " [REINTENTO] ⏳ Esperando $backoff_sec segundos antes de reintentar descarga..."
                    sleep "$backoff_sec"
                fi
            fi
        done

        if [ "$download_ok" = false ]; then
            echo " [ERROR CRÍTICO] ❌ No se pudo descargar/validar $model $exp $var tras $MAX_DOWNLOAD_RETRIES intentos."
            echo -e "${model}\t${variant}\t${exp}\t${var}\tDescarga incompleta o corrupta tras $MAX_DOWNLOAD_RETRIES intentos\t$(date '+%Y-%m-%d %H:%M:%S')" >> "$FAILED_LOG"
            rm -rf "$var_temp_dir"
            continue
        fi

        # ----------------------------------------------------------------------
        # C. Esperar a que el worker de CDO previo termine antes de lanzar el nuevo
        # ----------------------------------------------------------------------
        if [ -n "$BG_PROC_PID" ]; then
            echo " [PIPELINE] ⏳ Esperando finalización del procesamiento/transferencia anterior (PID: $BG_PROC_PID)..."
            if ! wait "$BG_PROC_PID"; then
                echo " [ADVERTENCIA] El procesamiento/transferencia anterior (PID: $BG_PROC_PID) finalizó con advertencias o error. Continuando con la siguiente variable..."
            fi
            BG_PROC_PID=""
        fi

        # ----------------------------------------------------------------------
        # D. Lanzar Procesamiento CDO + Sync Remoto en Background
        # ----------------------------------------------------------------------
        echo " [2/3 PIPELINE] 🚀 Lanzando CDO + Transferencia remota para $var en segundo plano..."
        process_variable_worker "$model" "$variant" "$exp" "$var" "$selyear_range" "$var_temp_dir" "$final_file" &
        BG_PROC_PID=$!

        echo " [PIPELINE] Worker en ejecución (PID: $BG_PROC_PID). Continuando inmediatamente con la siguiente descarga..."
        processed_count=$((processed_count + 1))
    done

    # Esperar al último worker en segundo plano
    if [ -n "$BG_PROC_PID" ]; then
        echo ""
        echo " [PIPELINE] ⏳ Esperando que finalice el último bloque de procesamiento/transferencia (PID: $BG_PROC_PID)..."
        if ! wait "$BG_PROC_PID"; then
            echo " [ADVERTENCIA] El último proceso de procesamiento/transferencia finalizó con advertencias."
        fi
        echo " [PIPELINE] ✅ Todos los procesos en segundo plano han finalizado."
    fi

    # Limpiar directorio temporal global si quedó vacío
    rmdir "$TEMP_DIR" 2>/dev/null || true

    echo ""
    echo "======================================================================"
    echo " PIPELINE FINALIZADO"
    echo "======================================================================"
    echo " Total combinaciones evaluadas : $total_combos"
    echo " Procesadas en esta sesión     : $processed_count"
    echo " Omitidas (ya existentes)      : $skipped_count"
    if [ -f "$FAILED_LOG" ] && [ -s "$FAILED_LOG" ]; then
        local failed_count
        failed_count=$(wc -l < "$FAILED_LOG")
        echo " Combinaciones con fallos      : $failed_count (Registradas en $FAILED_LOG)"
    else
        echo " Combinaciones con fallos      : 0 (100% de éxito)"
    fi
    if [ "$ENABLE_REMOTE_SYNC" == "true" ]; then
        echo " Almacenamiento final remoto   : ${SSH_TARGET}:${REMOTE_DEST_DIR}"
    else
        echo " Almacenamiento final local    : $LOCAL_OUTPUT_DIR"
    fi
    echo "======================================================================"
    echo ""
}

main "$@"
