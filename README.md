# Cadena Automatizada de Disponibilidad, Descarga y Preprocesamiento de Modelos CMIP6 (Centroamérica / DeepSD)

Este repositorio contiene las herramientas automatizadas para:
1. **Consultar la disponibilidad** de modelos climáticos globales CMIP6 en el índice distribuido de **ESGF MetaGrid** mediante la API Solr.
2. **Cruzar la disponibilidad** con el catálogo de modelos evaluados en **GCMEval**.
3. **Extraer URLs HTTPS directas** a nivel de archivo NetCDF (`type=File`), resolviendo réplicas y priorizando nodos de alta velocidad con soporte **Globus** (`*.data.globus.org`).
4. **Ejecutar un flujo automatizado de descarga y preprocesamiento con CDO**:
   - **Ejecución Simultánea (Descarga + Procesamiento)**: Descarga de la variable $N+1$ con `aria2c` en simultáneo con el procesamiento CDO de la variable $N$.
   - **Transferencia Remota Automática por SSH/rsync**: Envío directo de archivos procesados a una PC de almacenamiento remoto (`<IP_SERVIDOR>:<RUTA_DESTINO>/<MODELO>/`) preservando la jerarquía de directorios.
   - **Optimización de Espacio en Disco**: Eliminación inmediata de archivos temporales y locales tras confirmar la transferencia remota.
   - **Reanudación Automática (Resume)**: Detección inteligente de archivos ya procesados en destino local o remoto.
   - **Ejecución Persistente en Segundo Plano**: Soporte para servidores remotos y WSL2 sin interrupciones por cierre de sesión.

---

## 📋 Tabla de Contenidos

- [Estructura del Repositorio](#-estructura-del-repositorio)
- [Requisitos y Dependencias](#-requisitos-y-dependencias)
- [Modelos, Variables y Experimentos](#-modelos-variables-y-experimentos)
- [Evaluación Climatológica y Selección de Ensamble (GCMEval)](#evaluación-climatológica-y-selección-de-ensamble-gcmeval)
  - [Diseño y Justificación Climatológica de los 9 Experimentos (E0 a E8)](#diseño-y-justificación-climatológica-de-los-9-experimentos-e0-a-e8)
  - [Metodología de Selección en 3 Etapas](#metodología-de-selección-en-3-etapas)
  - [Anexo Técnico: Cálculo de Estadísticas GCMEval para Nuevos Modelos (CDO + R)](#anexo-técnico-cálculo-de-estadísticas-gcmeval-para-nuevos-modelos-cdo--r)
- [Flujo de Trabajo Paso a Paso](#-flujo-de-trabajo-paso-a-paso)
  - [Paso 1: Inventario Global y Extracción de URLs (`esgf-query.py`)](#paso-1-inventario-global-y-extracción-de-urls-esgf-querypy)
  - [Paso 2: Generación Dinámica del Manifiesto (`generate_manifest.py`)](#paso-2-generación-dinámica-del-manifiesto-generate_manifestpy)
  - [Paso 3: Descarga, Preprocesamiento y Transferencia Remota (`download_preprocess_cmip6.sh`)](#paso-3-descarga-preprocesamiento-y-transferencia-remota-download_preprocess_cmip6sh)
- [Configuración de Transferencia Remota (SSH sin contraseña)](#-configuración-de-transferencia-remota-ssh-sin-contraseña)
- [Ejecución en Servidores Remotos y Segundo Plano](#-ejecución-en-servidores-remotos-y-segundo-plano)
- [Ejecución en Windows con WSL2](#-ejecución-en-windows-con-wsl2-sin-que-se-corte-al-cerrar-la-ventana)
- [Estructura de Salida](#-estructura-de-salida)
- [Detalles Técnicos y Optimización](#-detalles-técnicos-y-optimización)
- [Autor](#-autor)

---

## 📂 Estructura del Repositorio

```text
.
├── esgf-query.py                  # Script principal: consulta ESGF Solr, genera inventario y extrae URLs
├── run_evaluation.py              # Orquestador Python de evaluación climatológica GCMEval en R
├── evaluation_config.yaml         # Configuración de regiones, observaciones, métricas y experimentos
├── generate_manifest.py           # Generador dinámico de manifiestos a partir de results/selected_models.csv
├── results_reporter.py            # Generador automático de reportes Markdown en results/etapas/
├── download_preprocess_cmip6.sh   # Script Bash: descarga aria2c + procesamiento CDO concurrente + rsync/scp remoto
├── run_background.sh              # Gestor de ejecución en segundo plano (start, status, log, stop)
├── gcmeval/                       # Módulo analítico y motor de evaluación de GCMEval
│   ├── run_cmip6_evaluation.R     # Script R principal: ejecuta experimentos, ranking 3 etapas y spread
│   ├── gcmeval_models.csv         # Catálogo de 120 modelos evaluables en GCMEval
│   ├── back-end/                  # Paquete R gcmeval, funciones estadísticas y datos (statistics.rda)
│   └── front-end/                 # Aplicación web interactiva Shiny
│
├── cache/                         # Caché local de consultas ESGF (no sincronizada con Git)
│   ├── esgf_raw_datasets.json     # Metadatos crudos de datasets ESGF
│   └── esgf_raw_files.json        # Metadatos crudos de archivos NetCDF ESGF
│
├── results/                       # Salidas generadas por fase (no sincronizadas con Git)
│   ├── README.md                  # Índice general de resultados por etapa
│   ├── etapas/                    # Reportes Markdown detallados por cada etapa del flujo de trabajo
│   │   ├── etapa1_inventario_esgf.md
│   │   ├── etapa2_evaluacion_gcmeval.md
│   │   ├── etapa3_manifiesto_descarga.md
│   │   └── etapa4_descarga_preprocesamiento.md
│   ├── cmip6_daily_inventory.xlsx / .csv
│   ├── cmip6_complete_models.csv  # Listado de realizaciones completas y validadas
│   ├── selected_models.csv        # Lista final seleccionada para generar manifiestos
│   ├── cmip6_manifest.tsv / cmip6_files.csv / cmip6_urls.txt
│   ├── ranking_E0.csv ... E8.csv  # Rankings individuales por cada experimento
│   ├── ranking_summary_all_experiments.csv
│   ├── analysis_stage1_variants.csv / stage2 / stage3
│   └── future_spread_<escenario>_<REGION>.png / .html
│
└── README.md                      # Documentación completa del flujo de trabajo
```

---

## ⚙️ Requisitos y Dependencias

El flujo de trabajo integra herramientas en **Python** (consultas ESGF, manifiestos, coordinación de pasos), **R** (evaluación y ranking estadístico GCMEval) y **utilidades del sistema** (CDO, aria2c, SSH).

### 1. Entorno Python (Recomendado vía Mamba / Conda)

Se recomienda utilizar **Mamba** (o **Conda**) en un entorno Python 3.11:

```bash
# 1. Crear y activar el entorno con todas las dependencias
mamba create -n climate python=3.11 r-base requests pandas openpyxl pyyaml urllib3 cdo aria2 curl rsync openssh coreutils -c conda-forge -y
mamba activate climate
```

### 2. Entorno R (Versión 4.4+) y Librerías de GCMEval

Para ejecutar el módulo de evaluación [`gcmeval/run_cmip6_evaluation.R`](gcmeval/run_cmip6_evaluation.R) y generar los gráficos interactivos:

- **R Base**: R >= 4.4.0 instalado (`Rscript`).
- **Paquetes de R necesarios**:
  ```R
  install.packages(c("shiny", "shinydashboard", "shinyjs", "DT", "plotrix", "fields", "sf", "plotly", "htmlwidgets", "ggplot2", "devtools"))
  
  # Instalar el paquete gcmeval local:
  devtools::install("gcmeval/back-end")
  ```

### 3. Utilidades del Sistema (Linux)

El proceso automatizado de descarga y recorte utiliza:
- **`cdo`** (Climate Data Operators con soporte multi-hilo OpenMP)
- **`aria2c`** (Gestor de descargas aceleradas multi-conexión y validación de hash)
- **`rsync`** o **`scp`** + **`ssh`** (Transferencia remota de archivos procesados)
- **`sha256sum`** o **`shasum`** (Verificación de integridad)

**Instalación nativa en Linux:**
```bash
# Ubuntu / Debian:
sudo apt-get update && sudo apt-get install -y cdo aria2 curl rsync openssh-client coreutils

# RedHat / CentOS / Rocky:
sudo dnf install -y epel-release && sudo dnf install -y cdo aria2 curl rsync openssh-clients coreutils
```

---

## 🌍 Modelos, Variables y Experimentos

### Embudo de Selección y Filtrado Metodológico (ESGF → Período → GCMEval)

El inventario aplica un embudo jerárquico de 3 niveles para garantizar que únicamente se descarguen y procesen realizaciones válidas tanto a nivel técnico en la infraestructura de datos de ESGF como a nivel metodológico en el marco de evaluación de GCMEval:

```mermaid
flowchart TD
    A["1. Universo ESGF y MetaGrid"] --> B["2. Filtro Técnico de Disponibilidad ESGF<br>(10 variables en 5 experimentos completos)"]
    B --> C["Realizaciones 100% Completas en ESGF"]
    
    D["Catálogo GCMEval<br>(gcmeval_models.csv)"] --> E{"Intersección Estricta"}
    C --> E
    
    E --> F["3. Realizaciones Candidatas Evaluables<br>(cmip6_complete_models.csv)"]
    F --> G["Fase 2: Evaluación GCMEval y Manifiesto de Descarga"]
```

1. **Nivel 1: Familias de Modelos y Realizaciones en ESGF:**
   * Detecta todas las familias de modelos (`source_id`) y corridas/miembros (`variant_label`) publicadas en los nodos federados de ESGF para la frecuencia diaria (`table_id=day`).
2. **Nivel 2: Criterio de Disponibilidad Técnica y Cobertura Temporal:**
   * Filtra las realizaciones que poseen publicadas **las 10 variables diarias en los 5 experimentos requeridos** (`historical` y los 4 SSPs), garantizando que cubran el **100% de los años requeridos** (`1950/1980-2014` para historical y `2015-2100` para SSPs).
3. **Nivel 3: Subconjunto Validado en GCMEval:**
   * Cruza la lista resultante contra el catálogo objetivo de **GCMEval** ([`gcmeval/gcmeval_models.csv`](gcmeval/gcmeval_models.csv)), seleccionando el subconjunto de realizaciones que cuentan con evaluación climática y respaldo metodológico.

> **Resultados obtenidos**: Consulta el detalle completo del inventario y las realizaciones seleccionadas en [`results/etapas/etapa1_inventario_esgf.md`](results/etapas/etapa1_inventario_esgf.md). La lista operativa final para descarga se gestiona en [`selected_models.csv`](selected_models.csv).

### 10 Variables Diarias (`table_id = day`)
- `ua`: Viento zonal (m/s)
- `va`: Viento meridional (m/s)
- `ta`: Temperatura del aire (K)
- `hur`: Humedad relativa (%)
- `hus`: Humedad específica (1)
- `zg`: Altura geopotencial (m)
- `psl`: Presión reducida a nivel del mar (Pa)
- `tasmax`: Temperatura máxima diaria del aire en superficie (K)
- `tasmin`: Temperatura mínima diaria del aire en superficie (K)
- `pr`: Precipitación diaria (kg m-2 s-1)

### 5 Experimentos y Períodos de Interés Configurables
- `historical`: `1950-2014` (Configurable en scripts vía `PERIOD_RANGES` o `HISTORICAL_START_YEAR` / `HISTORICAL_END_YEAR`)
- `ssp126`, `ssp245`, `ssp370`, `ssp585`: `2015-2100` (Configurable vía `SSP_START_YEAR` / `SSP_END_YEAR`)

---

## 📊 Evaluación Climatológica y Selección de Ensamble (GCMEval)

Para garantizar la representatividad y robustez climática de los modelos globales (GCM) seleccionados para el downscaling estadístico (*DeepSD*), se integró el motor analítico de **GCMEval** ([Brunner et al., 2020](https://doi.org/10.5194/esd-11-995-2020)).

Por defecto, la evaluación se configura sobre la región IPCC **`"Central America/Mexico [CAM:6]"`** como dominio primario y mantiene la **región secundaria desactivada (`weight: 0.0`)** para no influir en el cálculo. Es posible seleccionar cualquiera de las **34 regiones preestablecidas de GCMEval** (y activar opcionalmente una región secundaria ponderada) desde [`evaluation_config.yaml`](evaluation_config.yaml), el asistente interactivo (`--wizard`) o los parámetros CLI de [`run_evaluation.py`](run_evaluation.py). Los datos observacionales de referencia globales soportados son:
- **Temperatura (`tas`)**: Reanálisis **ERA5** (ECMWF) — también soporta `NCEP`, `CRU`.
- **Precipitación (`pr`)**: Producto observacional satelital y de estaciones **GPCP v2.3** — también soporta `CHIRPS`, `MSWEP`.

> **Resultados de la evaluación**: Todos los rankings por experimento (`E0` a `E8`), la matriz consolidada, el ranking final ganador de familias/ensamble y los gráficos de dispersión futura ($\Delta T$ vs $\Delta P$) se encuentran documentados en [`results/etapas/etapa2_evaluacion_gcmeval.md`](results/etapas/etapa2_evaluacion_gcmeval.md).

---

---

### Diseño y Justificación Climatológica de los 9 Experimentos (E0 a E8)

En el motor analítico y la interfaz de **GCMEval**, cada parámetro se calibra mediante pesos enteros discretos:
- **`0` = No considerado** (peso nulo).
- **`1` = Importante** (peso estándar de primer orden).
- **`2` = Muy importante** (máxima prioridad / peso doble).

#### 🎛️ Matriz de Pesos Asignados por Experimento en GCMEval

| Exp | Nombre del Experimento | $w_{tas}$ | $w_{pr}$ | $w_{ann}$ | $w_{djf}$ | $w_{mam}$ | $w_{jja}$ | $w_{son}$ | $w_{bias}$ | $w_{sd}$ | $w_{sc}$ | $w_{rmse}$ |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **E0** | **Control / Balance General** | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **E1** | **Énfasis en Temperatura** | **2** | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **E2** | **Énfasis en Precipitación** | 1 | **2** | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **E3** | **Época Seca (Estiaje DJF+MAM)** | 1 | 1 | 1 | **2** | **2** | 0 | 0 | 1 | 1 | 1 | 1 |
| **E4** | **Época Lluviosa (MAM+JJA+SON)** | 1 | 1 | 1 | 0 | **2** | **2** | **2** | 1 | 1 | 1 | 1 |
| **E5** | **Temperatura en Época Seca** | **2** | 1 | 1 | **2** | **2** | 0 | 0 | 1 | 1 | 1 | 1 |
| **E6** | **Precipitación en Época Lluviosa** | 1 | **2** | 1 | 0 | **2** | **2** | **2** | 1 | 1 | 1 | 1 |
| **E7** | **Termodinámica Pura (Solo Temp)** | **2** | 0 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| **E8** | **Hidrología Pura (Solo Lluvia)** | 0 | **2** | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

#### 📚 Sustento Científico y Referencias Meteorológicas para Centroamérica

| Proceso Meteorológico Regional | Justificación Física y Relevancia en el Istmo | Referencias Científicas |
|:---|:---|:---|
| **Canícula / Veranillo (Mid-Summer Drought - MSD)** | Disminución de lluvias en julio-agosto dentro de la época lluviosa, modulada por la aceleración del Chorro del Caribe y divergencia de humedad. | *Magaña et al. (1999); Maldonado et al. (2016); Hidalgo et al. (2017)* |
| **Chorro de Bajo Nivel del Caribe (CLLJ)** | Flujo de vientos alisios que transporta humedad del Atlántico e interactúa con la cordillera generando contraste vertiente Caribe vs Pacífica. | *Amador (1998, 2008); Muñoz et al. (2008); Cook & Vizy (2010)* |
| **Teleconexiones ENOS / OAM** | Forzamiento del Pacífico ecuatorial que induce sequías severas en el Corredor Seco (El Niño) o excesos hídricos (La Niña). | *Enfield & Alfaro (1999); Alfaro (2007); Taylor et al. (2012)* |
| **Evaluación Multicriterio CMIP6** | Marco formal para ponderar modelos por desempeño y evitar sesgos por promedio simple o redundancia de código. | *Brunner et al. (2020); Parding et al. (2020); Almazroui et al. (2021)* |

---

### Criterios de Selección y Desduplicación de Candidatos

Para definir el ensamble final a partir del ranking se aplican tres criterios metodológicos:
1. **Desduplicación Intra-Familia (Condiciones Iniciales)**: Se evalúan todas las variantes disponibles por modelo, reteniendo únicamente el miembro con menor *Mean Rank* y mayor estabilidad.
2. **Discriminación por Resolución Espacial en la Misma Familia**: Cuando coexisten versiones de alta/estándar resolución y baja resolución (`MM` vs `LM`, `Veg` vs `Veg-LR`, `LR` vs `HR`), se prioriza la variante con mejor desempeño y consistencia regional.
3. **Exclusión por Sesgos Extremos o Sensibilidad No Física**: Se descartan los modelos en las posiciones inferiores del ranking que presentan sesgos sistemáticos severos o sensibilidad climática anómala respecto al consenso físico.

---

### Metodología de Selección en 3 Etapas

Para estructurar un ensamble multi-modelo robusto e independiente (evitando la sobre-representación de centros climáticos que publicaron decenas de variantes del mismo código fuente), se aplica el siguiente protocolo:

1. **Etapa 1 (Estadística de Realizaciones)**: Cálculo de posición media (*Mean Rank*), desviación estándar (*SD Rank*) y frecuencia de permanencia en el Top 10 (*Freq Top 10*) para las realizaciones evaluadas a través de los 9 experimentos.
2. **Etapa 2 (Selección Intra-Familia)**: Identificación de la **mejor variante representativa** dentro de cada familia (aquella con el menor *Mean Rank* y mayor estabilidad).
3. **Etapa 3 (Ranking Inter-Familias y Spread Futuro)**: Ordenamiento final de las familias globales representadas por su mejor miembro, junto con el cálculo de la señal de cambio climático proyectado ($\Delta T$ vs $\Delta P$) y la exportación de gráficos estáticos (`.png`) e interactivos (`.html`).

> Los resultados completos de las 3 etapas, el ranking por experimento y el ensamble ganador están disponibles en [`results/etapas/etapa2_evaluacion_gcmeval.md`](results/etapas/etapa2_evaluacion_gcmeval.md).

---

### Anexo Técnico: Cálculo de Estadísticas GCMEval para Nuevos Modelos (CDO + R)

Si se desea incorporar al ranking un nuevo modelo CMIP6 disponible en ESGF que no figure actualmente en el archivo precomputado `statistics.rda` de GCMEval (por ejemplo, `ACCESS-CM2` o `ACCESS-ESM1-5`):

#### 1. Diagnóstico del Paquete `gcmeval`
El paquete `gcmeval` utiliza un archivo interno de datos comprimido `data/statistics.rda` que almacena un objeto `list` indexado por:
- Variable: `tas`, `pr`, `psl`, etc.
- Experimento / Escenario: `historical`, `ssp126`, `ssp245`, `ssp370`, `ssp585`.
- Período: `period.1981_2010`, `period.2071_2100`, etc.
- Región: `CAM:6`, `GL:0`, `WNA:1`, etc.
- Métricas: Climatología mensual (12 meses), sesgo medio (*Bias*), correlación de Pearson espacial/temporal (*r*), error cuadrático medio (*RMSE*), desviación estándar (*SD*), etc., calculadas respecto a las grillas comunes de referencia (ERA5 a $1^\circ \times 1^\circ$ y GPCP a $2.5^\circ \times 2.5^\circ$).

#### 2. Proceso de Preprocesamiento con CDO para Nuevos Modelos
Para cada nuevo modelo `MODEL` y variante `VAR`:

```bash
# Paso A: Remapeo a la grilla estándar de ERA5 / GPCP
cdo -O remapbil,r360x180 tas_day_${MODEL}_historical_${VAR}_19810101-20101231.nc tas_1x1_hist.nc
cdo -O remapbil,r360x180 tas_day_${MODEL}_ssp585_${VAR}_20710101-21001231.nc tas_1x1_ssp585.nc

# Paso B: Cálculo de medias mensuales y ciclo anual climatológico
cdo -O monmean tas_1x1_hist.nc tas_mon_hist.nc
cdo -O ymonmean tas_mon_hist.nc tas_ymon_hist.nc          # 12 pasos temporales (ciclo anual)
cdo -O timmean tas_mon_hist.nc tas_climatology_hist.nc    # Media climatológica 1981-2010

# Paso C: Repetir para precipitación (pr) convirtiendo unidades (kg m-2 s-1 a mm/día)
cdo -O -mulc,86400 -remapbil,r144x72 pr_day_${MODEL}_historical_${VAR}_19810101-20101231.nc pr_2.5x2.5_hist.nc
cdo -O -mulc,86400 -remapbil,r144x72 pr_day_${MODEL}_ssp585_${VAR}_20710101-21001231.nc pr_2.5x2.5_ssp585.nc
cdo -O ymonmean -monmean pr_2.5x2.5_hist.nc pr_ymon_hist.nc
```

#### 3. Script R para Actualizar `statistics.rda`
Con las capas mensuales y anuales recortadas por las máscaras poligonales de IPCC WGI (Región 6 - CAM), se ejecutan las funciones del script complementario `calculate_statistics.R` del paquete:

```R
# 1. Cargar estadísticas existentes
load("gcmeval/data/statistics.rda")

# 2. Agregar el nuevo modelo al slot correspondiente
new_gcm_id <- "CMIP6.ACCESS_CM2.r4i1p1f1"
statistics[["tas"]][["historical"]][["period.1981_2010"]][["ERA5"]][[new_gcm_id]] <- tas_stats_access
statistics[["pr"]][["historical"]][["period.1981_2010"]][["GPCP"]][[new_gcm_id]]  <- pr_stats_access
statistics[["tas"]][["ssp585"]][["period.2071_2100"]][[new_gcm_id]]               <- tas_future_access
statistics[["pr"]][["ssp585"]][["period.2071_2100"]][[new_gcm_id]]                <- pr_future_access

# 3. Guardar el archivo actualizado
save(statistics, file = "gcmeval/data/statistics.rda", compress = "xz")
```

Una vez actualizado `statistics.rda`, el script `run_cmip6_evaluation.R` detectará y evaluará automáticamente los nuevos modelos incorporados.

---

## 🚀 Flujo de Trabajo Paso a Paso

```mermaid
flowchart TD
    subgraph PC1["PC de Descarga y Procesamiento"]
        A["1. esgf-query.py"] -->|Consulta ESGF y Cruce GCMEval| B["Inventario Excel / CSV<br>cmip6_complete_models.csv"]
        B -->|Realizaciones Candidatas| C["2. run_evaluation.py<br>(Evaluación R GCMEval)"]
        C -->|Rankings E0-E8 + Spread| D["Selección de Familias<br>selected_models.csv"]
        D --> E["3. generate_manifest.py"]
        E -->|cmip6_manifest.tsv| F["4. download_preprocess_cmip6.sh"]
        F --> G["Descarga Variable N con aria2c"]
        G -->|Fin descarga N| H["Procesamiento CDO Variable N en background"]
        G -.->|En paralelo| I["Descarga Variable N+1 con aria2c"]
        H -->|sellonlatbox + mergetime + selyear| J["Archivo NetCDF Final"]
    end
    
    subgraph PC2["PC de Almacenamiento Remoto"]
        J -->|Transferencia SSH scp / rsync| K["<RUTA_DESTINO>/MODELO/"]
    end
    
    K -->|Confirmacion de Transferencia| L["Limpieza Automatica de Disco en PC1"]
```

---

### Paso 1: Inventario Global y Extracción de URLs (`esgf-query.py`)

Este script realiza la búsqueda en el índice de MetaGrid (`https://metagrid.esgf-west.org/proxy/search`):
- **Fase 1**: Evalúa la disponibilidad a nivel de dataset para las 10 variables y 5 experimentos, consolida el resumen por modelo y realiza el cruce con `gcmeval_models.csv`.
- **Fase 2**: Para los modelos seleccionados, consulta a nivel de archivo (`type=File`), resuelve réplicas priorizando URLs Globus HTTPS (`*.data.globus.org`) y extrae los enlaces directos y hashes SHA256.

**Ejecución:**
```bash
python esgf-query.py
```

**Salidas generadas en `results/`:**
- `results/cmip6_daily_inventory.xlsx`: Libro Excel con 4 hojas formateadas condicionalmente (`inventory`, `summary`, `selected`, `files`).
- `results/cmip6_complete_models.csv`: Lista plana (`NOMBRE.variante`, sin encabezado) de realizaciones 100% completas en período y validadas en GCMEval.
- `results/selected_models.csv`: Lista base para alimentar `generate_manifest.py` (si no existe aún).
- `results/cmip6_daily_inventory.csv`: Inventario general tabular.
- `results/cmip6_files.csv`: Catálogo plano de archivos NetCDF.
- `cache/esgf_raw_datasets.json`: Caché local de metadatos crudos Solr para consultas sin conexión (separada de `results/` para conservarla o limpiarla de forma independiente).
- Reporte de resultados: [`results/etapas/etapa1_inventario_esgf.md`](results/etapas/etapa1_inventario_esgf.md)

---

### Paso 2: Evaluación Climatológica y Selección de Ensamble (`run_evaluation.py`)

Orquesta desde Python la ejecución del motor de evaluación climatológica de GCMEval en R ([`gcmeval/run_cmip6_evaluation.R`](gcmeval/run_cmip6_evaluation.R)). Detecta automáticamente el ejecutable de R, valida las librerías necesarias y ejecuta los experimentos de sensibilidad configurados (por defecto `E0` a `E8` sobre Centroamérica `CAM:6`, con soporte para cambiar la región primaria o añadir una región secundaria):

**Ejecución desde Python:**
```bash
python run_evaluation.py
```

**Opciones disponibles:**
```bash
# Ejecutar evaluación con la configuración por defecto (Centroamérica CAM:6, región secundaria con peso 0.0)
python run_evaluation.py

# Listar todas las regiones preestablecidas disponibles en GCMEval
python run_evaluation.py --list-regions

# Evaluar otra región primaria por CLI (ej. Amazonía)
python run_evaluation.py --region "Amazon [AMZ:7]" -y

# Combinar región primaria y secundaria con pesos personalizados
python run_evaluation.py --region "CAM" --secondary-region "small islands regions Caribbean" --secondary-weight 0.3 -y

# Instalar automáticamente paquetes de R faltantes
python run_evaluation.py --install-deps

# Especificar ruta personalizada a Rscript
python run_evaluation.py --r-path "C:\Program Files\R\R-4.4.3\bin\Rscript.exe"

# Evaluar una lista alternativa de modelos
python run_evaluation.py --models-csv mi_lista_modelos.csv
```

**Salidas generadas en el directorio `results/`:**
- `ranking_E0.csv` a `ranking_E8.csv`: Rankings individuales de los 9 experimentos de sensibilidad.
- `ranking_summary_all_experiments.csv`: Matriz consolidada de posiciones por experimento.
- `analysis_stage1_variants.csv`: Estadística descriptiva de todas las variantes evaluadas.
- `analysis_stage2_best_variants.csv`: Selección de la mejor corrida representativa por familia.
- `analysis_stage3_families.csv`: Clasificación general de las familias de modelos.
- `future_spread_<escenario>_<REGION>.html`: Gráfico interactivo Plotly (por defecto `future_spread_ssp585_CAM.html`) con ventanas emergentes de estadísticas al hacer clic en cada modelo.
- `future_spread_<escenario>_<REGION>.png`: Gráfico estático de dispersión ($\Delta T$ vs $\Delta P$) en alta resolución (300 DPI).
- Reporte de resultados: [`results/etapas/etapa2_evaluacion_gcmeval.md`](results/etapas/etapa2_evaluacion_gcmeval.md)

---

### Paso 3: Generación Dinámica del Manifiesto (`generate_manifest.py`)

Genera el catálogo y manifiesto estructurado leyendo la lista de modelos seleccionados desde `results/selected_models.csv` (o un archivo alternativo como `results/cmip6_complete_models.csv`):

**Ejecución básica (usa `results/selected_models.csv` por defecto):**
```bash
python generate_manifest.py
```

**Ejecución personalizada con otro archivo o parámetros:**
```bash
# Usando la lista de todos los modelos completos generados por esgf-query
python generate_manifest.py -i results/cmip6_complete_models.csv -o results/cmip6_manifest.tsv --workers 8

# Especificando períodos temporales personalizados
python generate_manifest.py -i results/selected_models.csv --hist-start 1950 --hist-end 2014 --ssp-start 2015 --ssp-end 2100
```

**Salidas generadas en `results/`:**
- `results/cmip6_manifest.tsv`: Manifiesto delimitado por tabuladores (TSV) con URLs, checksums SHA256, tamaños de archivo y metadatos.
- `results/cmip6_files.csv`: Catálogo CSV detallado de los modelos procesados.
- `results/cmip6_urls.txt`: Lista plana de URLs directas para descarga.
- Reporte de resultados: [`results/etapas/etapa3_manifiesto_descarga.md`](results/etapas/etapa3_manifiesto_descarga.md) (y [`results/etapas/etapa4_descarga_preprocesamiento.md`](results/etapas/etapa4_descarga_preprocesamiento.md) para el Paso 4).

---

### Paso 4: Descarga, Preprocesamiento y Transferencia Remota (`download_preprocess_cmip6.sh`)

El script Bash ejecuta el flujo automatizado de alto rendimiento:

1. **Reanudación Inteligente (Resume)**: Verifica si el archivo procesado ya existe en la máquina remota (o local) antes de descargar.
2. **Descarga Acelerada (`aria2c`)**: Descarga los segmentos temporales de la variable actual con validación SHA256.
3. **Procesamiento Simultáneo en Segundo Plano**:
   - Inicia el procesamiento CDO de la variable descargada en segundo plano (`process_variable_worker &`).
   - Inicia inmediatamente la descarga con `aria2c` de la siguiente variable, eliminando tiempos muertos de red.
4. **Recorte Espacial con CDO**: Aplica `sellonlatbox,-120,-40.5,-18.5,43` (Centroamérica ampliada) a cada chunk con multi-hilo OpenMP (`CDO_THREADS=$(nproc)`).
5. **Concatenación y Selección Temporal**: Une los chunks con `mergetime` y filtra los años según el experimento:
   - `historical`: `1950/2014`
   - Escenarios SSP (`ssp126`, `ssp245`, `ssp370`, `ssp585`): `2015/2100`
6. **Transferencia Remota Automática**: Envía el archivo resultante vía `rsync` (o `scp`) a `<USUARIO>@<IP_SERVIDOR>:<RUTA_DESTINO>/<MODELO>/`.
7. **Limpieza Inmediata de Disco**: Tras confirmar la transferencia, elimina los archivos brutos y procesados locales, manteniendo la PC de descarga siempre con espacio libre.

**Ejecución estándar:**
```bash
# Dar permisos de ejecución
chmod +x download_preprocess_cmip6.sh

# Ejecutar flujo de descarga y procesamiento
./download_preprocess_cmip6.sh
```

**Personalización de variables de entorno:**
```bash
# Ejemplo: cambiar host remoto, usuario, hilos de CDO o ancho de banda
REMOTE_HOST="<IP_SERVIDOR>" \
REMOTE_USER="<USUARIO>" \
REMOTE_DEST_DIR="/ruta/CMIP6_GCMs_Processed" \
CDO_THREADS=16 \
MAX_DOWNLOAD_LIMIT=0 \
./download_preprocess_cmip6.sh
```

---

## 🔑 Configuración de Transferencia Remota (`.env` y SSH sin contraseña)

1. **Configurar el archivo local de secretos (`.env`)**:
   Copia la plantilla [`.env.example`](.env.example) como `.env` (este archivo está ignorado en `.gitignore` y nunca se sincroniza con Git) y completa tus datos:
   ```bash
   cp .env.example .env
   ```
   ```ini
   ENABLE_REMOTE_SYNC=true
   REMOTE_HOST=<IP_SERVIDOR>
   REMOTE_USER=<USUARIO>
   REMOTE_DEST_DIR=/ruta/CMIP6_GCMs_Processed
   ```

Para que el script pueda transferir automáticamente los archivos a la PC de almacenamiento remoto (`<IP_SERVIDOR>`) con el usuario correspondiente (`<USUARIO>`) sin pedir contraseña en cada variable:

1. **Configurar el cliente SSH en la PC de descarga (`~/.ssh/config`):**
   Agrega las siguientes líneas a tu archivo `~/.ssh/config`:
   ```text
   Host <IP_SERVIDOR>
       User <USUARIO>
       Port 22
   ```

2. **Generar clave SSH en la PC de descarga (si no existe):**
   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
   ```

3. **Copiar la clave pública a la PC de almacenamiento Windows:**
   - La clave pública (`~/.ssh/id_ed25519.pub`) debe agregarse al archivo:
     - Si el usuario es estándar: `C:\Users\<USUARIO>\.ssh\authorized_keys`
     - Si el usuario pertenece al grupo Administradores: `C:\ProgramData\ssh\administrators_authorized_keys` (con permisos de lectura exclusivos para SYSTEM y Administrators).

4. **Verificar la conexión:**
   ```bash
   ssh "<USUARIO>@<IP_SERVIDOR>" "echo Conexión exitosa"
   ```

---

## 🖥️ Ejecución en Servidores Remotos y Segundo Plano

Cuando se ejecuta el proceso en un servidor remoto a través de SSH, es fundamental evitar que el proceso se detenga si la sesión se desconecta:

### Opción 1: Helper Automatizado `run_background.sh` (Recomendado)

```bash
# Dar permisos de ejecución
chmod +x run_background.sh

# 1. Iniciar el proceso en segundo plano
./run_background.sh start

# 2. Consultar el estado del proceso
./run_background.sh status

# 3. Monitorear los logs en tiempo real (Ctrl + C para salir sin detener el proceso)
./run_background.sh log

# 4. Detener el proceso si es necesario
./run_background.sh stop
```

---

### Opción 2: Usando `tmux` (Sesión Interactiva Persistente)

```bash
# 1. Crear e ingresar a una nueva sesión de tmux
tmux new -s cmip6_job

# 2. Iniciar el script
./download_preprocess_cmip6.sh

# 3. Desconectar la sesión sin detener el proceso (Detach):
#    Presiona Ctrl + b, luego suelta y presiona d

# 4. (Seguro desconectar SSH) Para volver a ver el proceso:
tmux attach -t cmip6_job
```

---

### Opción 3: Usando `screen`

```bash
# Iniciar sesión screen
screen -S cmip6_job
./download_preprocess_cmip6.sh

# Desconectar: Presiona Ctrl + a, luego d
# Reconectar:
screen -r cmip6_job
```

---

## 🪟 Ejecución en Windows con WSL2 (Sin que se corte al cerrar la ventana)

En **WSL2**, si se cierra la ventana de la terminal, Windows puede suspender la máquina virtual si no está configurada adecuadamente. Para evitar que el proceso se corte:

### 1. Activar `systemd` en WSL2 (Windows 11)

1. Edita el archivo `/etc/wsl.conf` dentro de WSL2:
   ```bash
   sudo nano /etc/wsl.conf
   ```
2. Agrega:
   ```ini
   [boot]
   systemd=true
   ```
3. Reinicia WSL2 desde PowerShell de Windows:
   ```powershell
   wsl --shutdown
   ```

### 2. Lanzar en segundo plano desde PowerShell de Windows

Puedes lanzar el proceso directamente desde Windows sin mantener ninguna ventana de WSL abierta:

```powershell
# Iniciar en segundo plano:
wsl -d Ubuntu --exec bash -c "cd /ruta/de/tu/proyecto && ./run_background.sh start"

# Consultar el estado en cualquier momento:
wsl -d Ubuntu --exec bash -c "cd /ruta/de/tu/proyecto && ./run_background.sh status"
```

---

## 📁 Estructura de Salida

En la PC de almacenamiento remoto (`<RUTA_DESTINO>`), los archivos procesados se organizan en subcarpetas por cada modelo:

```text
<RUTA_DESTINO>/
├── ACCESS-CM2\
│   ├── hur_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── hur_day_ACCESS-CM2_ssp126_r1i1p1f1_20150101-21001231.nc
│   ├── pr_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── psl_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── ta_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── tasmax_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── tasmin_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── ua_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   ├── va_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
│   └── zg_day_ACCESS-CM2_historical_r1i1p1f1_19500101-20141231.nc
├── EC-Earth3\
├── INM-CM4-8\
├── IPSL-CM6A-LR\
├── KACE-1-0-G\
├── MPI-ESM1-2-LR\
├── MRI-ESM2-0\
├── NorESM2-MM\
├── TaiESM1\
└── UKESM1-0-LL\
```

---

## 💡 Detalles Técnicos y Optimización

### 1. Nodos Globus y URLs HTTPS
En ESGF, los nodos integrados con la infraestructura de Globus (como **Argonne ALCF** `eagle.alcf.anl.gov` y **LLNL**) exponen el servicio `HTTPServer` a través de URLs directas en el dominio `https://*.data.globus.org/`. El script prioriza automáticamente estas URLs por ofrecer altas tasas de transferencia y disponibilidad directa vía HTTPS estándar (código HTTP 200).

### 2. Deduplicación Inteligente de Réplicas
Cuando un archivo existe replicado en varios nodos (`data_node`), el algoritmo clasifica y selecciona la mejor réplica:
1. **Prioridad 1 (Máxima)**: URLs HTTPS de Globus (`*.data.globus.org` o nodos con soporte Globus).
2. **Prioridad 2**: URLs HTTPS seguras de THREDDS (`https://.../thredds/fileServer/...`).
3. **Prioridad 3**: URLs HTTP estándar de THREDDS (`http://.../thredds/fileServer/...`).

### 3. Procesamiento Simultáneo en Segundo Plano
Para maximizar la utilización del ancho de banda y la capacidad de cómputo:
- El cuello de botella de red y de CPU se desacoplan.
- Mientras `cdo` procesa los archivos de la variable $N$, `aria2c` descarga los de la variable $N+1$.
- Al concluir el procesamiento y la transferencia remota, los archivos locales se eliminan inmediatamente, manteniendo el uso de disco acotado a solo 1 o 2 variables concurrentes.

---

## 👤 Autor

- **Will Abarca**
- Ministerio de Medio Ambiente y Recursos Naturales (MARN), El Salvador.
