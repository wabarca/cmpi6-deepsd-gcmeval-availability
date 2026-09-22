#!/usr/bin/env bash
# ==============================================================================
# Helper para ejecución en segundo plano (Remote SSH / Background Runner)
# ==============================================================================
#
# Permite lanzar el pipeline de descarga y preprocesamiento en servidores remotos
# sin riesgo de interrupción al cerrar la sesión SSH.
#
# Uso:
#   ./run_background.sh start      # Inicia el proceso en segundo plano con nohup
#   ./run_background.sh status     # Muestra el estado del proceso y últimos logs
#   ./run_background.sh log        # Monitorea el log en tiempo real (tail -f)
#   ./run_background.sh stop       # Detiene el proceso de forma segura
# ==============================================================================

set -euo pipefail

LOG_FILE="${LOG_FILE:-cmip6_pipeline.log}"
SCRIPT="./download_preprocess_cmip6.sh"
PID_FILE=".cmip6_pipeline.pid"

case "${1:-status}" in
    start)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "[AVISO] El proceso ya está en ejecución (PID: $(cat "$PID_FILE"))."
            echo "Para ver el log en tiempo real: ./run_background.sh log"
            exit 0
        fi

        echo "Iniciando pipeline en segundo plano..."
        nohup "$SCRIPT" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "[OK] Proceso iniciado con PID: $(cat "$PID_FILE")"
        echo "Logs redirigidos a: $LOG_FILE"
        echo ""
        echo "Comandos útiles:"
        echo "  - Ver log en vivo : ./run_background.sh log"
        echo "  - Ver estado      : ./run_background.sh status"
        echo "  - Detener proceso : ./run_background.sh stop"
        ;;

    status)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            echo "🟢 ESTADO: Proceso en EJECUCIÓN (PID: $(cat "$PID_FILE"))"
            echo ""
            echo "--- Últimas 15 líneas de log ($LOG_FILE) ---"
            if [ -f "$LOG_FILE" ]; then
                tail -n 15 "$LOG_FILE"
            else
                echo "(Log no creado aún)"
            fi
        else
            echo "⚪ ESTADO: Proceso INACTIVO / DETENIDO"
            if [ -f "$LOG_FILE" ]; then
                echo ""
                echo "--- Últimas 10 líneas del log previo ($LOG_FILE) ---"
                tail -n 10 "$LOG_FILE"
            fi
        fi
        ;;

    log)
        if [ ! -f "$LOG_FILE" ]; then
            echo "[AVISO] El archivo de log '$LOG_FILE' no existe aún."
            exit 1
        fi
        echo "Monitoreando log en tiempo real (Presiona Ctrl+C para salir sin detener el proceso)..."
        tail -f "$LOG_FILE"
        ;;

    stop)
        if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
            pid=$(cat "$PID_FILE")
            echo "Deteniendo proceso (PID: $pid)..."
            kill "$pid"
            rm -f "$PID_FILE"
            echo "[OK] Proceso detenido."
        else
            echo "[AVISO] No hay proceso activo en ejecución."
            rm -f "$PID_FILE"
        fi
        ;;

    *)
        echo "Uso: $0 {start|status|log|stop}"
        exit 1
        ;;
esac
