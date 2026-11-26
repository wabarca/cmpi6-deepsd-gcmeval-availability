#!/usr/bin/env Rscript
# ==============================================================================
# Actualización segura de meta.rda y statistics.rda en gcmeval/back-end/data/
# Incluye respaldo automático con marca de tiempo, cálculo en carpeta temporal
# y reinstalación del paquete local gcmeval.
# ==============================================================================

args <- commandArgs(trailingOnly = TRUE)

get_arg <- function(flag, default = NULL) {
  idx <- which(args == flag)
  if (length(idx) > 0 && idx[1] < length(args)) {
    return(args[idx[1] + 1])
  }
  return(default)
}

has_flag <- function(flag) {
  return(flag %in% args)
}

gcmeval_dir <- if (dir.exists("gcmeval")) "gcmeval" else "."
backend_dir <- file.path(gcmeval_dir, "back-end")
data_dir    <- file.path(backend_dir, "data")
backup_root <- file.path(data_dir, "backups")
file_shape  <- file.path(backend_dir, "inst", "extdata", "SREX_regions", "referenceRegions.shp")

staging_dir <- get_arg("--staging-dir", file.path("cache", "gcmeval_staging", "CMIP6"))
ref_dir     <- get_arg("--ref-dir", file.path("cache", "ref"))
restore_req <- has_flag("--restore-backup")

reinstall_gcmeval <- function() {
  cat("[INFO] Reinstalando paquete local 'gcmeval' desde", backend_dir, "...\n")
  install.packages(backend_dir, repos = NULL, type = "source", quiet = FALSE)
}

# Modo restauración desde el último respaldo
if (restore_req) {
  if (!dir.exists(backup_root)) {
    stop("No existe el directorio de respaldos: ", backup_root)
  }
  b_dirs <- sort(list.dirs(backup_root, full.names = TRUE, recursive = FALSE), decreasing = TRUE)
  if (length(b_dirs) == 0) {
    stop("No se encontraron respaldos en: ", backup_root)
  }
  latest_b <- b_dirs[1]
  cat("[RESTORE] Restaurando desde respaldo:", latest_b, "\n")
  for (fn in c("meta.rda", "statistics.rda")) {
    src <- file.path(latest_b, fn)
    dst <- file.path(data_dir, fn)
    if (!file.exists(src)) stop("Falta archivo en respaldo: ", src)
    file.copy(src, dst, overwrite = TRUE)
  }
  reinstall_gcmeval()
  cat("[OK] Base de datos GCMEval restaurada y paquete reinstalado.\n")
  quit(save = "no", status = 0)
}

# Verificar paquete gcmeval
if (!requireNamespace("gcmeval", quietly = TRUE)) {
  reinstall_gcmeval()
}
suppressPackageStartupMessages(library(gcmeval))

if (!dir.exists(staging_dir)) {
  stop("No existe el directorio de modelos preparados: ", staging_dir)
}
files_gcm <- list.files(path = staging_dir, pattern = "\\.nc$", full.names = TRUE, recursive = TRUE)
if (length(files_gcm) == 0) {
  stop("No se encontraron archivos .nc preparados en: ", staging_dir)
}

# Verificar archivos de referencia observacional (ERA5 y GPCP)
era5_tas_file <- file.path(ref_dir, "era5_monthly_1979-2018_tas.2.5deg.nc")
gpcp_pr_file  <- file.path(ref_dir, "gpcp.nc")
if (!file.exists(era5_tas_file)) stop("Falta archivo de referencia ERA5: ", era5_tas_file)
if (!file.exists(gpcp_pr_file))  stop("Falta archivo de referencia GPCP: ", gpcp_pr_file)

files_ref <- list(
  "era5.tas" = basename(era5_tas_file),
  "gpcp"     = basename(gpcp_pr_file)
)

# 1. Respaldo automático previo
dir.create(backup_root, recursive = TRUE, showWarnings = FALSE)
ts_label <- format(Sys.time(), "%Y%m%d_%H%M%S")
backup_dir <- file.path(backup_root, ts_label)
dir.create(backup_dir, recursive = TRUE, showWarnings = FALSE)

for (fn in c("meta.rda", "statistics.rda")) {
  src <- file.path(data_dir, fn)
  if (!file.exists(src)) stop("No se encontró archivo base: ", src)
  ok <- file.copy(src, file.path(backup_dir, fn), overwrite = TRUE)
  if (!ok) stop("No se pudo respaldar: ", src)
}
cat("[BACKUP] Respaldo previo creado en:", backup_dir, "\n")

# 2. Trabajo en carpeta temporal para no corromper data/ si ocurre un error
work_dir <- file.path("cache", "gcmeval_staging", "work")
dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)
file.copy(file.path(data_dir, "meta.rda"), file.path(work_dir, "meta.rda"), overwrite = TRUE)
file.copy(file.path(data_dir, "statistics.rda"), file.path(work_dir, "statistics.rda"), overwrite = TRUE)

cat("[1/3] Extrayendo metadatos (metaextract) para", length(files_gcm), "archivos NetCDF...\n")
meta <- metaextract(
  files_gcm,
  file.out = "meta.rda",
  path.out = work_dir,
  add = TRUE,
  force = FALSE,
  verbose = TRUE
)

cat("[2/3] Calculando estadísticas futuras (2021-2050 y 2071-2100)...\n")
for (it in list(c(2071, 2100), c(2021, 2050))) {
  calculate.statistics(
    files_gcm,
    meta = meta,
    file.out = "statistics.rda",
    path.out = work_dir,
    file.shape = file_shape,
    ref = NULL,
    period = it,
    stats = c("mean.gcm", "spatial.sd.gcm"),
    add = TRUE,
    force = FALSE,
    verbose = TRUE
  )
}

cat("[3/3] Calculando estadísticas históricas (1981-2010) contra ERA5 y GPCP...\n")
tas_files <- files_gcm[grepl("^tas_", basename(files_gcm))]
pr_files  <- files_gcm[grepl("^pr_", basename(files_gcm))]

if (length(tas_files) > 0) {
  calculate.statistics(
    tas_files,
    meta = meta,
    file.out = "statistics.rda",
    path.out = work_dir,
    file.shape = file_shape,
    ref = "era5",
    path.ref = ref_dir,
    files.ref = files_ref,
    period = c(1981, 2010),
    stats = c("mean.gcm", "spatial.sd.gcm", "mean.ref", "spatial.sd.ref", "corr", "rmse", "cmpi"),
    add = TRUE,
    force = FALSE,
    verbose = TRUE
  )
}

if (length(pr_files) > 0) {
  calculate.statistics(
    pr_files,
    meta = meta,
    file.out = "statistics.rda",
    path.out = work_dir,
    file.shape = file_shape,
    ref = "gpcp",
    path.ref = ref_dir,
    files.ref = files_ref,
    period = c(1981, 2010),
    stats = c("mean.gcm", "spatial.sd.gcm", "mean.ref", "spatial.sd.ref", "corr", "rmse", "cmpi"),
    add = TRUE,
    force = FALSE,
    verbose = TRUE
  )
}

# 3. Promover archivos validados a gcmeval/back-end/data/ y reinstalar paquete
file.copy(file.path(work_dir, "meta.rda"), file.path(data_dir, "meta.rda"), overwrite = TRUE)
file.copy(file.path(work_dir, "statistics.rda"), file.path(data_dir, "statistics.rda"), overwrite = TRUE)
cat("[OK] Archivos meta.rda y statistics.rda actualizados en:", data_dir, "\n")

reinstall_gcmeval()
cat("[OK] Actualización de GCMEval completada exitosamente.\n")
