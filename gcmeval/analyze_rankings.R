#!/usr/bin/env Rscript
# ==============================================================================
# Script: analyze_rankings.R
# Descripción: Realiza el análisis estadístico de los rankings (E0 a E8) en 
#              tres etapas:
#              Etapa 1: Estadísticas para las 41 variantes.
#              Etapa 2: Selección de la mejor variante por familia de GCM.
#              Etapa 3: Ranking final de las familias de GCMs.
# Autor: Antigravity AI
# ==============================================================================

library(gcmeval)

# 1. Cargar las funciones base para parsear nombres
global_file <- file.path("front-end", "global.R")
if (!file.exists(global_file)) {
  stop("Error: No se encontró el archivo 'front-end/global.R'.")
}
source(global_file)

# 2. Configurar rutas de archivos
results_dir <- "../results"
summary_file <- file.path(results_dir, "ranking_summary_all_experiments.csv")

if (!file.exists(summary_file)) {
  stop(paste("Error: No existe el archivo consolidado de rankings en:", summary_file))
}

# Leer la tabla de rankings consolidada
cat("Cargando base de datos consolidada de rankings desde:", summary_file, "\n")
rankings_data <- read.csv(summary_file, stringsAsFactors = FALSE)

# Identificar las columnas de ranking (Rank_E0, Rank_E1, ..., Rank_E8)
rank_cols <- grep("^Rank_E", names(rankings_data), value = TRUE)
cat("Columnas de ranking identificadas:", paste(rank_cols, collapse = ", "), "\n\n")

# ==============================================================================
# ETAPA 1: Análisis estadístico de las 41 variantes
# ==============================================================================
cat("--- ETAPA 1: Procesando estadísticas para las 41 variantes ---\n")

# Obtener nombres de familias (GCM) usando gcmlabel
labels <- gcmlabel(rankings_data$Modelo)
familias <- as.character(labels$gcm)

# Extraer solo las columnas de rango como matriz para los cálculos
rank_matrix <- as.matrix(rankings_data[, rank_cols])

# Calcular las métricas solicitadas
mean_ranks <- rowMeans(rank_matrix)
median_ranks <- apply(rank_matrix, 1, median)
sd_ranks <- apply(rank_matrix, 1, sd)
freq_top10 <- rowSums(rank_matrix <= 10)
freq_top20 <- rowSums(rank_matrix <= 20)

# Construir el DataFrame de la Etapa 1
stage1_df <- data.frame(
  Modelo = rankings_data$Modelo,
  Familia = familias,
  Mean_Rank = mean_ranks,
  Median_Rank = median_ranks,
  SD_Rank = sd_ranks,
  Freq_Top10 = freq_top10,
  Freq_Top20 = freq_top20,
  stringsAsFactors = FALSE
)

# Ordenar por Ranking Medio de forma ascendente (el mejor primero)
stage1_df <- stage1_df[order(stage1_df$Mean_Rank, stage1_df$SD_Rank), ]

# Exportar a CSV de la Etapa 1
stage1_file <- file.path(results_dir, "analysis_stage1_variants.csv")
write.csv(stage1_df, stage1_file, row.names = FALSE)
cat("  -> Guardado:", stage1_file, "\n\n")

# ==============================================================================
# ETAPA 2: Selección de la mejor variante por familia
# ==============================================================================
cat("--- ETAPA 2: Seleccionando la mejor variante por familia ---\n")

unique_families <- unique(stage1_df$Familia)
best_variants_list <- list()

for (fam in unique_families) {
  # Filtrar variantes pertenecientes a esta familia
  fam_df <- stage1_df[stage1_df$Familia == fam, ]
  
  # Criterio de Selección:
  # 1. Menor ranking promedio (Mean_Rank)
  # 2. Menor desviación estándar (SD_Rank) en caso de empate
  # 3. Primera aparición en caso de empate total
  fam_df_sorted <- fam_df[order(fam_df$Mean_Rank, fam_df$SD_Rank), ]
  best_variant <- fam_df_sorted[1, ]
  
  best_variants_list[[fam]] <- best_variant
}

# Unificar las mejores variantes en un solo DataFrame
stage2_df <- do.call(rbind, best_variants_list)
rownames(stage2_df) <- NULL

# Ordenar por Ranking Medio de forma ascendente (el mejor primero)
stage2_df <- stage2_df[order(stage2_df$Mean_Rank, stage2_df$SD_Rank), ]

# Exportar a CSV de la Etapa 2
stage2_file <- file.path(results_dir, "analysis_stage2_best_variants.csv")
write.csv(stage2_df, stage2_file, row.names = FALSE)
cat("  -> Guardado:", stage2_file, "\n\n")

# ==============================================================================
# ETAPA 3: Ranking de Familias
# ==============================================================================
cat("--- ETAPA 3: Construyendo el ranking de familias ---\n")

# El ranking de familias es simplemente el ranking de sus mejores representantes.
# Ya ordenamos stage2_df por el Mean_Rank de su mejor variante, así que el orden
# de las filas determina el puesto de la familia.
stage3_df <- data.frame(
  Rank_Familia = 1:nrow(stage2_df),
  Familia = stage2_df$Familia,
  Mejor_Variante = stage2_df$Modelo,
  Mean_Rank_Representante = stage2_df$Mean_Rank,
  SD_Rank_Representante = stage2_df$SD_Rank,
  Freq_Top10_Representante = stage2_df$Freq_Top10,
  Freq_Top20_Representante = stage2_df$Freq_Top20,
  stringsAsFactors = FALSE
)

# Exportar a CSV de la Etapa 3
stage3_file <- file.path(results_dir, "analysis_stage3_families.csv")
write.csv(stage3_df, stage3_file, row.names = FALSE)
cat("  -> Guardado:", stage3_file, "\n\n")

# ==============================================================================
# Imprimir resumen de resultados
# ==============================================================================
cat("======================================================================\n")
cat("RESUMEN GENERAL DEL ANÁLISIS DE RANKING DE FAMILIAS\n")
cat("======================================================================\n")
print(head(stage3_df[, c("Rank_Familia", "Familia", "Mejor_Variante", "Mean_Rank_Representante")], 10))
cat("======================================================================\n")
cat("Análisis estadístico completado con éxito.\n")
cat("======================================================================\n")
