#!/usr/bin/env Rscript
# ==============================================================================
# Script: run_experiments.R
# Descripción: Automatiza la evaluación y el ranking de un subconjunto selecto
#              de 41 modelos CMIP6 para la región de Centroamérica bajo 9 experimentos
#              de pesos (E0 a E8). Exporta archivos CSV individuales y consolidados.
# Autor: Antigravity AI
# ==============================================================================

library(gcmeval)

# 1. Cargar las funciones base de la interfaz Shiny
global_file <- file.path("front-end", "global.R")
if (!file.exists(global_file)) {
  stop("Error: No se encontró el archivo 'front-end/global.R'. Asegúrate de ejecutar el script desde el directorio raíz de 'gcmeval'.")
}
source(global_file)

# 2. Configurar rutas de archivos
csv_path <- "../gcmeval_ensemble_models.csv"
results_dir <- "../results"

if (!file.exists(csv_path)) {
  stop(paste("Error: No se encontró el archivo de modelos seleccionados en:", csv_path))
}

# Crear directorio de resultados si no existe
if (!dir.exists(results_dir)) {
  dir.create(results_dir, recursive = TRUE)
  cat("Directorio creado:", results_dir, "\n")
}

# 3. Leer y limpiar nombres de modelos desde el CSV
cat("Cargando listado de modelos desde:", csv_path, "\n")
csv_data <- read.csv(csv_path, header = FALSE, stringsAsFactors = FALSE)
csv_names <- as.character(csv_data$V1)
cat("Modelos especificados en el CSV:", length(csv_names), "\n")

# Obtener modelos disponibles (ya filtrados y cargados al hacer source de global.R)
modelos_disponibles <- gcmnames

# Mapear nombres del CSV a los nombres oficiales en la base de datos
clean_name <- function(x) gsub("[[:punct:]]|[[:space:]]", "", tolower(x))
clean_db <- sapply(modelos_disponibles, function(name) {
  clean_val <- clean_name(name)
  # Quitar prefijo de cmip (cmip5 / cmip6) para coincidir
  sub("^cmip[0-9]", "", clean_val)
})
clean_csv <- sapply(csv_names, clean_name)

matches <- match(clean_csv, clean_db)
matched_db_names <- modelos_disponibles[matches]

# Reportar coincidencias fallidas
missing_matches <- csv_names[is.na(matches)]
if (length(missing_matches) > 0) {
  cat("\nADVERTENCIA: No se encontraron coincidencias para los siguientes modelos del CSV:\n")
  print(missing_matches)
  # Filtrar los valores nulos para continuar con los que sí coincidieron
  matched_db_names <- matched_db_names[!is.na(matched_db_names)]
}

cat("Modelos validados y mapeados con éxito en la base de datos:", length(matched_db_names), "\n\n")

# 4. Definir las combinaciones de pesos para los 9 experimentos (E0 a E8)
experiments <- list(
  E0 = list(
    name = "Control (equilibrado)",
    w_var = c(tas = 1, pr = 1),
    w_season = c(ann = 1, djf = 1, mam = 1, jja = 1, son = 1),
    desc = "Evaluación equilibrada de temperatura y precipitación en todas las estaciones."
  ),
  E1 = list(
    name = "Énfasis en temperatura",
    w_var = c(tas = 2, pr = 1),
    w_season = c(ann = 1, djf = 1, mam = 1, jja = 1, son = 1),
    desc = "Favorece modelos que representen mejor los patrones térmicos."
  ),
  E2 = list(
    name = "Énfasis en precipitación",
    w_var = c(tas = 1, pr = 2),
    w_season = c(ann = 1, djf = 1, mam = 1, jja = 1, son = 1),
    desc = "Favorece modelos que representen mejor los patrones de lluvia."
  ),
  E3 = list(
    name = "Temporada seca",
    w_var = c(tas = 1, pr = 1),
    w_season = c(ann = 1, djf = 2, mam = 2, jja = 0, son = 0),
    desc = "Desempeño durante la época seca (DJF y MAM duplicados, JJA y SON omitidos)."
  ),
  E4 = list(
    name = "Temporada lluviosa",
    w_var = c(tas = 1, pr = 1),
    w_season = c(ann = 1, djf = 0, mam = 2, jja = 2, son = 2),
    desc = "Representación de la época lluviosa (DJF omitida, MAM/JJA/SON con peso 2)."
  ),
  E5 = list(
    name = "Temperatura + temporada seca",
    w_var = c(tas = 2, pr = 1),
    w_season = c(ann = 1, djf = 2, mam = 2, jja = 0, son = 0),
    desc = "Prioriza la representación térmica durante la estación seca."
  ),
  E6 = list(
    name = "Precipitación + temporada lluviosa",
    w_var = c(tas = 1, pr = 2),
    w_season = c(ann = 1, djf = 0, mam = 2, jja = 2, son = 2),
    desc = "Prioriza la representación de lluvia durante la estación lluviosa."
  ),
  E7 = list(
    name = "Temperatura extrema",
    w_var = c(tas = 2, pr = 0),
    w_season = c(ann = 1, djf = 1, mam = 1, jja = 1, son = 1),
    desc = "Comportamiento de rankings cuando sólo importa la temperatura."
  ),
  E8 = list(
    name = "Precipitación extrema",
    w_var = c(tas = 0, pr = 2),
    w_season = c(ann = 1, djf = 1, mam = 1, jja = 1, son = 1),
    desc = "Comportamiento de rankings cuando sólo importa la precipitación."
  )
)

# Parámetros globales constantes
region_selected <- "Central America/Mexico [CAM:6]"
ref_tas <- "ERA5"
ref_pr <- "GPCP"
rcp_selected <- "ssp585"
w_metric <- c(bias = 1, sd = 1, corr = 1, rmse = 1) # Peso base equilibrado para las 4 métricas de error

# 5. Calcular los rankings base multidimensionales (una sola vez por eficiencia)
cat("Calculando rangos espaciales base para Temperatura (tas) contra", ref_tas, "... ")
tas_ranks <- ranking.all(varid = "tas", ref = ref_tas, rcp = rcp_selected, Regions = list(region_selected), im = matched_db_names)
cat("Listo.\n")

cat("Calculando rangos espaciales base para Precipitación (pr) contra", ref_pr, "... ")
pr_ranks  <- ranking.all(varid = "pr", ref = ref_pr, rcp = rcp_selected, Regions = list(region_selected), im = matched_db_names)
cat("Listo.\n\n")

# Estructura para almacenar resultados de todos los experimentos
exp_results <- list()

# 6. Ejecutar en bucle los 9 experimentos (E0 a E8)
for (exp_id in names(experiments)) {
  exp <- experiments[[exp_id]]
  cat("Ejecutando:", exp_id, "-", exp$name, "\n")
  
  # Peso de variables
  var_weighted <- exp$w_var["tas"] * tas_ranks + exp$w_var["pr"] * pr_ranks
  
  # Peso de regiones (solo 1 región, peso unitario)
  w_region <- 1
  
  # Peso de estaciones
  w_season <- exp$w_season
  
  # Colapsar estaciones y regiones
  consolidated_metrics <- array(NA, c(nrow(var_weighted), 4))
  for (i in 1:nrow(var_weighted)) {
    for (j in 1:4) {
      slice <- var_weighted[i, , j, , drop = FALSE]
      slice_2d <- slice[1, , 1, , drop = FALSE] # Matriz [5 estaciones x 1 región]
      consolidated_metrics[i, j] <- as.numeric(t(w_season) %*% slice_2d %*% w_region)
    }
  }
  
  # Aplicar pesos de métricas
  final_scores <- consolidated_metrics %*% as.numeric(w_metric)
  
  # Generar ranking final con resolución de duplicados
  gcm_labels <- gcmlabel(rownames(tas_ranks))
  gcm_keys <- paste(gcm_labels$cmip, gcm_labels$gcm, gcm_labels$rip, sep = ".")
  
  ranks_final <- rep(0, length(final_scores))
  ranks_final[!duplicated(gcm_keys)] <- rank(final_scores[!duplicated(gcm_keys)])
  for(gcm in gcm_keys[duplicated(gcm_keys)]) {
    ranks_final[gcm_keys == gcm] <- ranks_final[gcm_keys == gcm][1]
  }
  names(ranks_final) <- rownames(tas_ranks)
  
  # Crear DataFrame y ordenar
  res_df <- data.frame(
    Modelo = rownames(tas_ranks),
    Score = as.vector(final_scores),
    Rank = ranks_final,
    stringsAsFactors = FALSE
  )
  res_df <- res_df[order(res_df$Rank), ]
  
  # Guardar resultado del experimento individual
  exp_results[[exp_id]] <- res_df
  
  # Exportar a CSV individual
  output_file <- file.path(results_dir, paste0("ranking_", exp_id, ".csv"))
  write.csv(res_df, output_file, row.names = FALSE)
  cat("  -> Guardado:", output_file, "\n")
}

# 7. Generar y exportar tabla comparativa consolidada
cat("\nGenerando tabla consolidada global... ")
summary_df <- data.frame(Modelo = rownames(tas_ranks), stringsAsFactors = FALSE)

for (exp_id in names(experiments)) {
  exp_res <- exp_results[[exp_id]]
  # Alinear el orden de filas al DataFrame de resumen
  idx <- match(summary_df$Modelo, exp_res$Modelo)
  summary_df[[paste0("Rank_", exp_id)]] <- exp_res$Rank[idx]
  summary_df[[paste0("Score_", exp_id)]] <- exp_res$Score[idx]
}

# Ordenar por el ranking de control E0 por defecto
summary_df <- summary_df[order(summary_df$Rank_E0), ]

summary_file <- file.path(results_dir, "ranking_summary_all_experiments.csv")
write.csv(summary_df, summary_file, row.names = FALSE)
cat("Listo. Guardado en:", summary_file, "\n")

cat("\n======================================================================\n")
cat("¡PROCESAMIENTO COMPLETADO CON ÉXITO!\n")
cat("Todos los reportes están disponibles en la carpeta:", normalizePath(results_dir), "\n")
cat("======================================================================\n")
