# ==============================================================================
# CMIP6 Multi-Criteria Evaluation & Ranking for Central America (CAM:6)
# GCMEval Framework - Automated Experiments E0 to E8 and Future Spread Analysis
# ==============================================================================

suppressPackageStartupMessages({
  library(gcmeval)
  library(sp)
  library(fields)
  library(ggplot2)
})

# 1. Rutas y configuración
workspace_dir <- getwd()
gcmeval_dir <- if (dir.exists("gcmeval")) "gcmeval" else "."
results_dir <- file.path(gcmeval_dir, "..", "results")
if (!dir.exists(results_dir)) dir.create(results_dir, recursive = TRUE, showWarnings = FALSE)

models_csv <- file.path(gcmeval_dir, "cmip6_complete_models.csv")
if (!file.exists(models_csv)) {
  models_csv <- file.path("cmip6_complete_models.csv")
}

# 2. Cargar funciones base de GCMEval
source(file.path(gcmeval_dir, "front-end", "global.R"))

# 3. Leer lista de modelos seleccionados de ESGF MetaGrid
target_models_raw <- readLines(models_csv)
target_models_raw <- trimws(target_models_raw)
target_models_raw <- target_models_raw[target_models_raw != "" & !grepl("^#", target_models_raw)]

cat(sprintf("=======================================================================\n"))
cat(sprintf("  EVALUACIÓN CLIMATOLÓGICA Y RANKINGS GCMEVAL PARA CENTROAMÉRICA (CAM) \n"))
cat(sprintf("=======================================================================\n"))
cat(sprintf("Modelos candidatos cargados desde '%s': %d\n", models_csv, length(target_models_raw)))

# 4. Parámetros de evaluación
rcp_selected <- "ssp585"
ref_tas <- "ERA5"
ref_pr  <- "GPCP"
region_cam <- "Central America/Mexico [CAM:6]"
regiones <- list(region_cam)
w_region <- c(1)

# Obtener catálogo de GCMs en statistics
stats_all <- dataPrep(rcp = rcp_selected)
gcmnames_all <- unique(unlist(attr(stats_all, "gcmnames")))

# Mapear modelos de CSV a identificadores de statistics
clean_id <- function(x) gsub("[[:punct:]]|[[:space:]]", "", tolower(x))

map_model_name <- function(raw_name, pool) {
  parts <- strsplit(raw_name, "\\.")[[1]]
  s_id <- parts[1]
  v_lbl <- if (length(parts) > 1) parts[2] else ""
  
  c_s_id <- clean_id(s_id)
  c_v_lbl <- clean_id(v_lbl)
  
  matches <- pool[sapply(pool, function(p) {
    cp <- clean_id(p)
    grepl(c_s_id, cp) && grepl(c_v_lbl, cp)
  })]
  
  if (length(matches) > 0) {
    return(matches[1])
  }
  return(NA)
}

mapped_models <- list()
for (m in target_models_raw) {
  mapped <- map_model_name(m, gcmnames_all)
  if (!is.na(mapped)) {
    mapped_models[[m]] <- mapped
  } else {
    cat(sprintf("[AVISO] No se encontró coincidencia directa en statistics.rda para: %s\n", m))
  }
}

cat(sprintf("Modelos mapeados con éxito en GCMEval: %d de %d\n\n", length(mapped_models), length(target_models_raw)))

eval_pool <- unname(unlist(mapped_models))

# 5. Obtener matrices de ranking multidimensionales (varid x season x metric x region)
tas_ranks <- ranking.all(varid = "tas", ref = ref_tas, rcp = rcp_selected, Regions = regiones, im = eval_pool)
pr_ranks  <- ranking.all(varid = "pr",  ref = ref_pr,  rcp = rcp_selected, Regions = regiones, im = eval_pool)

# Alinear nombres de filas
common_models <- intersect(rownames(tas_ranks), rownames(pr_ranks))
tas_ranks <- tas_ranks[common_models, , , , drop = FALSE]
pr_ranks  <- pr_ranks[common_models, , , , drop = FALSE]

# 6. Definición de la matriz de 9 experimentos de sensibilidad (E0 a E8)
experiments_def <- list(
  E0 = list(name = "E0_Control_Equilibrado",       wt = 1, wp = 1, seas = c(1, 1, 1, 1, 1), desc = "Control / Balance General"),
  E1 = list(name = "E1_Enfasis_Temperatura",      wt = 2, wp = 1, seas = c(1, 1, 1, 1, 1), desc = "Énfasis en Temperatura"),
  E2 = list(name = "E2_Enfasis_Precipitacion",     wt = 1, wp = 2, seas = c(1, 1, 1, 1, 1), desc = "Énfasis en Precipitación"),
  E3 = list(name = "E3_Epoca_Seca",               wt = 1, wp = 1, seas = c(1, 2, 2, 0, 0), desc = "Época Seca (Estiaje DJF+MAM)"),
  E4 = list(name = "E4_Epoca_Lluviosa",           wt = 1, wp = 1, seas = c(1, 0, 2, 2, 2), desc = "Época Lluviosa (MAM+JJA+SON)"),
  E5 = list(name = "E5_Temperatura_Epoca_Seca",   wt = 2, wp = 1, seas = c(1, 2, 2, 0, 0), desc = "Temperatura en Época Seca"),
  E6 = list(name = "E6_Precipitacion_Lluviosa",   wt = 1, wp = 2, seas = c(1, 0, 2, 2, 2), desc = "Precipitación en Época Lluviosa"),
  E7 = list(name = "E7_Solo_Temperatura",         wt = 2, wp = 0, seas = c(1, 1, 1, 1, 1), desc = "Termodinámica Pura (Solo Temp)"),
  E8 = list(name = "E8_Solo_Precipitacion",        wt = 0, wp = 2, seas = c(1, 1, 1, 1, 1), desc = "Hidrología Pura (Solo Lluvia)")
)

w_metric <- c(1, 1, 1, 1) # bias=1, sd=1, corr=1, rmse=1

# Mapeo inverso exacto y robusto hacia los nombres de modelos en ESGF
map_df <- data.frame(
  raw_esgf = names(mapped_models),
  mapped_id = as.character(unname(unlist(mapped_models))),
  clean_key = sub("^[a-z0-9]+\\.", "", as.character(unname(unlist(mapped_models)))),
  stringsAsFactors = FALSE
)
clean_common <- sub("^[a-z0-9]+\\.", "", common_models)
esgf_model_names <- map_df$raw_esgf[match(clean_common, map_df$clean_key)]

# Extracción precisa de etiquetas de modelo
labels_info <- gcmlabel(common_models)
clean_model_names <- paste0(gsub("_", "-", labels_info$gcm), ".", labels_info$rip)
clean_families    <- gsub("_", "-", labels_info$gcm)
clean_variants    <- labels_info$rip

experiment_results <- list()
rank_matrix <- matrix(NA, nrow = length(common_models), ncol = length(experiments_def),
                      dimnames = list(common_models, names(experiments_def)))
score_matrix <- matrix(NA, nrow = length(common_models), ncol = length(experiments_def),
                       dimnames = list(common_models, names(experiments_def)))

cat("--- EJECUTANDO LOS 9 EXPERIMENTOS DE SENSIBILIDAD (E0 a E8) ---\n")
for (exp_id in names(experiments_def)) {
  exp <- experiments_def[[exp_id]]
  
  # Ponderación de variables
  var_weighted <- exp$wt * tas_ranks + exp$wp * pr_ranks
  
  # Ponderación estacional y regional
  consolidated <- array(NA, c(nrow(var_weighted), 4))
  for (i in 1:nrow(var_weighted)) {
    for (j in 1:4) {
      consolidated[i, j] <- exp$seas %*% var_weighted[i, , j, ] %*% w_region
    }
  }
  
  # Ponderación de métricas de error
  scores <- as.vector(consolidated %*% w_metric)
  ranks  <- rank(scores)
  
  df_exp <- data.frame(
    Modelo = clean_model_names,
    Familia = clean_families,
    Variante = clean_variants,
    ID_Interno = common_models,
    Rank = ranks,
    Score = round(scores, 4),
    Experimento = exp_id,
    Descripcion = exp$desc,
    stringsAsFactors = FALSE
  )
  df_exp <- df_exp[order(df_exp$Rank), ]
  rownames(df_exp) <- NULL
  
  experiment_results[[exp_id]] <- df_exp
  rank_matrix[common_models, exp_id] <- ranks
  score_matrix[common_models, exp_id] <- scores
  
  # Exportar CSV de cada experimento
  out_csv <- file.path(results_dir, sprintf("ranking_%s.csv", exp_id))
  write.csv(df_exp, out_csv, row.names = FALSE)
  cat(sprintf("   [OK] %-2s (%-30s): Guardado en %s (Top 1: %s)\n",
              exp_id, exp$desc, basename(out_csv), df_exp$Modelo[1]))
}

# 7. Tabla resumen consolidada de todos los experimentos
summary_all <- data.frame(
  Modelo = clean_model_names,
  Familia = clean_families,
  Variante = clean_variants,
  ID_Interno = common_models,
  stringsAsFactors = FALSE
)

for (exp_id in names(experiments_def)) {
  summary_all[[paste0("Rank_", exp_id)]] <- rank_matrix[common_models, exp_id]
  summary_all[[paste0("Score_", exp_id)]] <- round(score_matrix[common_models, exp_id], 4)
}

summary_csv <- file.path(results_dir, "ranking_summary_all_experiments.csv")
write.csv(summary_all, summary_csv, row.names = FALSE)
cat(sprintf("\n[OK] Tabla consolidada de experimentos guardada: %s\n", summary_csv))

# 8. ETAPA 1: Análisis estadístico de las 36 variantes
stage1 <- data.frame(
  Modelo = clean_model_names,
  Modelo_ESGF = esgf_model_names,
  Familia = clean_families,
  Variante = clean_variants,
  ID_Interno = common_models,
  Mean_Rank = round(rowMeans(rank_matrix), 2),
  Median_Rank = round(apply(rank_matrix, 1, median), 2),
  SD_Rank = round(apply(rank_matrix, 1, sd), 2),
  Min_Rank = apply(rank_matrix, 1, min),
  Max_Rank = apply(rank_matrix, 1, max),
  Freq_Top5 = rowSums(rank_matrix <= 5),
  Freq_Top10 = rowSums(rank_matrix <= 10),
  stringsAsFactors = FALSE
)
stage1 <- stage1[order(stage1$Mean_Rank, stage1$SD_Rank), ]
rownames(stage1) <- NULL

stage1_csv <- file.path(results_dir, "analysis_stage1_variants.csv")
write.csv(stage1, stage1_csv, row.names = FALSE)
cat(sprintf("[OK] Etapa 1 (Estadística de 36 variantes) guardada: %s\n", stage1_csv))

# 9. ETAPA 2: Selección de la mejor variante por familia
families <- unique(stage1$Familia)
stage2_list <- list()

for (fam in families) {
  subset_fam <- stage1[stage1$Familia == fam, ]
  # Criterio: menor Mean_Rank, luego menor SD_Rank, luego mayor Freq_Top10
  subset_fam <- subset_fam[order(subset_fam$Mean_Rank, subset_fam$SD_Rank, -subset_fam$Freq_Top10), ]
  best_variant <- subset_fam[1, ]
  best_variant$Total_Variantes_Evaluadas <- nrow(subset_fam)
  stage2_list[[fam]] <- best_variant
}

stage2 <- do.call(rbind, stage2_list)
stage2 <- stage2[order(stage2$Mean_Rank, stage2$SD_Rank), ]
rownames(stage2) <- NULL

stage2_csv <- file.path(results_dir, "analysis_stage2_best_variants.csv")
write.csv(stage2, stage2_csv, row.names = FALSE)
cat(sprintf("[OK] Etapa 2 (Mejor variante por familia, 16 familias) guardada: %s\n", stage2_csv))

# 10. ETAPA 3: Ranking de Familias
stage3 <- data.frame(
  Rank_Familia = seq_len(nrow(stage2)),
  Familia = stage2$Familia,
  Mejor_Variante = stage2$Modelo,
  Modelo_ESGF = stage2$Modelo_ESGF,
  ID_Interno = stage2$ID_Interno,
  Mean_Rank = stage2$Mean_Rank,
  SD_Rank = stage2$SD_Rank,
  Freq_Top10 = sprintf("%d / 9", stage2$Freq_Top10),
  Total_Variantes_Familia = stage2$Total_Variantes_Evaluadas,
  stringsAsFactors = FALSE
)

stage3_csv <- file.path(results_dir, "analysis_stage3_families.csv")
write.csv(stage3, stage3_csv, row.names = FALSE)
cat(sprintf("[OK] Etapa 3 (Ranking consolidado de 16 familias) guardado: %s\n", stage3_csv))

# 11. CÁLCULO DE LA SEÑAL DE CAMBIO CLIMÁTICO Y SPREAD FUTURO (SSP5-8.5, 2071-2100 vs 1981-2010)
cat("\n--- CALCULANDO SEÑAL DE CAMBIO CLIMÁTICO Y SPREAD FUTURO (CAM:6) ---\n")
p_present <- "period.1981_2010"
p_future  <- "period.2071_2100"
reg_lbl   <- "CAM"

spread_rows <- list()
for (i in seq_along(common_models)) {
  m_id <- common_models[i]
  m_clean <- clean_model_names[i]
  fam <- clean_families[i]
  gcm_key <- sub("^[a-z0-9]+\\.", "", m_id)
  
  # Temperatura
  tas_pres <- stats_all[["tas"]][["ssp585"]][[p_present]][[gcm_key]][[reg_lbl]][["mean"]][["ann"]]
  tas_fut  <- stats_all[["tas"]][["ssp585"]][[p_future]][[gcm_key]][[reg_lbl]][["mean"]][["ann"]]
  delta_tas <- if (!is.null(tas_fut) && !is.null(tas_pres)) tas_fut - tas_pres else NA
  
  # Precipitación
  pr_pres <- stats_all[["pr"]][["ssp585"]][[p_present]][[gcm_key]][[reg_lbl]][["mean"]][["ann"]]
  pr_fut  <- stats_all[["pr"]][["ssp585"]][[p_future]][[gcm_key]][[reg_lbl]][["mean"]][["ann"]]
  delta_pr_mm_day <- if (!is.null(pr_fut) && !is.null(pr_pres)) (pr_fut - pr_pres) * 86400 else NA
  delta_pr_pct    <- if (!is.null(pr_fut) && !is.null(pr_pres) && pr_pres > 0) ((pr_fut - pr_pres) / pr_pres) * 100 else NA
  
  fam_match <- which(stage3$Mejor_Variante == m_clean)
  fam_rank <- if (length(fam_match) > 0) stage3$Rank_Familia[fam_match[1]] else as.integer(NA)
  is_best_family <- (length(fam_match) > 0)

  m_match <- which(stage1$ID_Interno == m_id)
  m_mean_rank <- if (length(m_match) > 0) stage1$Mean_Rank[m_match[1]] else NA
  m_sd_rank   <- if (length(m_match) > 0) stage1$SD_Rank[m_match[1]] else NA
  m_top10     <- if (length(m_match) > 0) stage1$Freq_Top10[m_match[1]] else 0
  var_str <- as.character(clean_variants[i])
  if (length(var_str) == 0) var_str <- ""

  spread_rows[[i]] <- data.frame(
    Modelo = as.character(m_clean),
    Familia = as.character(fam),
    Variante = as.character(var_str),
    ID_Interno = as.character(m_id),
    Mean_Rank = as.numeric(m_mean_rank),
    SD_Rank = as.numeric(m_sd_rank),
    Freq_Top10 = sprintf("%d / 9", as.integer(m_top10)),
    Rank_Familia = as.integer(fam_rank),
    Es_Mejor_Familia = as.logical(is_best_family),
    Delta_Tas_C = round(as.numeric(delta_tas), 3),
    Delta_Pr_mm_day = round(as.numeric(delta_pr_mm_day), 3),
    Delta_Pr_pct = round(as.numeric(delta_pr_pct), 2),
    stringsAsFactors = FALSE
  )
}

spread_df <- do.call(rbind, spread_rows)
spread_df <- spread_df[order(spread_df$Mean_Rank), ]
rownames(spread_df) <- NULL

spread_csv <- file.path(results_dir, "future_spread_data.csv")
write.csv(spread_df, spread_csv, row.names = FALSE)
cat(sprintf("[OK] Datos de Spread Futuro guardados: %s\n", spread_csv))

# 12. GENERACIÓN DEL GRÁFICO DE SPREAD (ΔT vs ΔP) CON GGPLOT2
# 12. GENERACIÓN DEL GRÁFICO DE SPREAD (ΔT vs ΔP) ESTILO GCMEVAL
spread_plot_png  <- file.path(results_dir, "future_spread_ssp585_CAM.png")
spread_plot_html <- file.path(results_dir, "future_spread_ssp585_CAM.html")

# Paleta oficial de GCMEval (de rosa/magenta = menor desempeño a verde oscuro = mejor desempeño)
# rev(c("#d01c8b","#d196ba","#d7d7d7","#98c166","#4dac26"))
gcmeval_ramp <- colorRampPalette(c("#4dac26", "#98c166", "#d7d7d7", "#d196ba", "#d01c8b"))
max_rank <- max(spread_df$Mean_Rank, na.rm = TRUE)
spread_df$Color_Hex <- gcmeval_ramp(100)[pmin(100, pmax(1, round((spread_df$Mean_Rank / max_rank) * 100)))]

# Preparar contenido para ventana emergente interactiva al hacer clic en cada punto
spread_df$ModalContent <- sprintf(
  "<div style='border-bottom: 2px solid #2b6616; padding-bottom: 8px; margin-bottom: 12px;'>
     <h3 style='margin:0; color:#1b4332;'>%s</h3>
     <span style='display:inline-block; margin-top:4px; padding:2px 8px; font-size:12px; font-weight:bold; border-radius:4px; background:%s; color:%s;'>%s</span>
   </div>
   <table style='width:100%%; font-size:13px; border-collapse:collapse; line-height:1.6;'>
     <tr><td style='color:#555; font-weight:bold;'>Familia:</td><td>%s</td></tr>
     <tr><td style='color:#555; font-weight:bold;'>Variante / Miembro:</td><td>%s</td></tr>
     <tr><td style='color:#555; font-weight:bold;'>Ranking Medio (E0-E8):</td><td><b>%.2f</b> (Desv. Est.: %.2f)</td></tr>
     <tr><td style='color:#555; font-weight:bold;'>Frecuencia en Top 10:</td><td>%s de 9 experimentos</td></tr>
     <tr style='border-top:1px solid #eee;'><td style='color:#555; font-weight:bold; padding-top:6px;'>ΔT (SSP5-8.5 2071-2100):</td><td style='padding-top:6px; color:#b7094c; font-weight:bold;'>+%.2f °C</td></tr>
     <tr><td style='color:#555; font-weight:bold;'>ΔP (SSP5-8.5 2071-2100):</td><td style='color:#0077b6; font-weight:bold;'>%.2f mm/día (%.1f%%)</td></tr>
   </table>",
  spread_df$Modelo,
  ifelse(spread_df$Es_Mejor_Familia, "#d8f3dc", "#edf2f4"),
  ifelse(spread_df$Es_Mejor_Familia, "#2d6a4f", "#495057"),
  ifelse(spread_df$Es_Mejor_Familia, sprintf("Mejor Representante de Familia (#%d)", spread_df$Rank_Familia), "Variante Adicional"),
  spread_df$Familia,
  spread_df$Variante,
  spread_df$Mean_Rank, spread_df$SD_Rank,
  spread_df$Freq_Top10,
  spread_df$Delta_Tas_C, spread_df$Delta_Pr_mm_day, spread_df$Delta_Pr_pct
)

best_df  <- spread_df[spread_df$Es_Mejor_Familia, ]
other_df <- spread_df[!spread_df$Es_Mejor_Familia, ]

# A) Versión Estática PNG de Alta Calidad (ggplot2 con estética GCMEval)
p <- ggplot(spread_df, aes(x = Delta_Tas_C, y = Delta_Pr_pct)) +
  geom_hline(yintercept = 0, linetype = "dashed", color = "grey60", linewidth = 0.5) +
  geom_vline(xintercept = mean(spread_df$Delta_Tas_C, na.rm=TRUE), linetype = "dotted", color = "grey70", linewidth = 0.5) +
  geom_point(aes(color = Mean_Rank, size = Es_Mejor_Familia, shape = Es_Mejor_Familia), alpha = 0.9) +
  scale_color_gradientn(
    colors = c("#4dac26", "#98c166", "#d7d7d7", "#d196ba", "#d01c8b"),
    name = "Ranking Medio\n(Verde=Mejor,\nRosa=Inferior)"
  ) +
  scale_size_manual(values = c("TRUE" = 4.5, "FALSE" = 2.2), name = "Representante", labels = c("Otras Variantes", "Mejor por Familia")) +
  scale_shape_manual(values = c("TRUE" = 18, "FALSE" = 1), name = "Representante", labels = c("Otras Variantes", "Mejor por Familia")) +
  geom_text(data = best_df, aes(label = sprintf("%s (#%d)", Familia, Rank_Familia)),
            vjust = -0.9, hjust = 0.5, size = 3.3, fontface = "bold", color = "#1a1a1a", check_overlap = FALSE) +
  coord_cartesian(xlim = c(2.2, 5.3), ylim = c(-35, 10)) +
  labs(
    title = "Annual Climate Change in Central America / Mexico (CAM:6)",
    subtitle = "Present day (1981-2010) to Far Future (2071-2100) | SSP5-8.5\nGCMEval Framework: ERA5 (tas) & GPCP (pr) Reference | 16 CMIP6 Families",
    x = "Temperature change (°C)",
    y = "Precipitation change (%)",
    caption = "GCMEval Multi-criteria Evaluation | MARN El Salvador"
  ) +
  theme_minimal(base_size = 12) +
  theme(
    plot.title = element_text(face = "bold", size = 13, hjust = 0.5),
    plot.subtitle = element_text(size = 9.5, hjust = 0.5, color = "grey30", margin = margin(b = 12)),
    legend.position = "right",
    panel.grid.minor = element_blank(),
    panel.border = element_rect(color = "grey80", fill = NA, linewidth = 0.7)
  )

ggsave(spread_plot_png, plot = p, width = 11, height = 7.5, dpi = 300)
cat(sprintf("[OK] Gráfico de Spread Futuro (PNG) guardado: %s\n", spread_plot_png))

# B) Versión Interactiva HTML con Plotly (Replicando la Interfaz Web Shiny de GCMEval)
if (requireNamespace("plotly", quietly = TRUE) && requireNamespace("htmlwidgets", quietly = TRUE)) {
  library(plotly)
  
  # Scatter principal con etiquetas limpias y customdata para ventana emergente
  p_scatter <- plot_ly() %>%
    add_trace(
      data = other_df,
      x = ~Delta_Tas_C, y = ~Delta_Pr_pct,
      type = "scatter", mode = "markers",
      marker = list(
        color = ~Color_Hex,
        size = 8,
        symbol = "circle",
        line = list(color = "grey40", width = 0.8)
      ),
      text = ~Modelo,
      customdata = ~ModalContent,
      hoverinfo = "text",
      name = "Otras Variantes"
    ) %>%
    add_trace(
      data = best_df,
      x = ~Delta_Tas_C, y = ~Delta_Pr_pct,
      type = "scatter", mode = "markers+text",
      text = ~Familia,
      textposition = "top center",
      textfont = list(family = "Arial", size = 11, color = "#111111"),
      hovertext = ~Modelo,
      customdata = ~ModalContent,
      hoverinfo = "text",
      marker = list(
        color = ~Color_Hex,
        size = 14,
        symbol = "diamond",
        line = list(color = "black", width = 1.8)
      ),
      name = "Mejor Variante por Familia"
    ) %>%
    layout(
      xaxis = list(title = "Temperature change (°C)", zerolinecolor = "#bdbdbd", zerolinewidth = 1),
      yaxis = list(title = "Precipitation change (%)", zerolinecolor = "#bdbdbd", zerolinewidth = 1),
      title = list(text = "<b>Climate Change Spread in Central America/Mexico (CAM:6)</b><br><sup>SSP5-8.5 (2071-2100 vs 1981-2010) - Haz clic en un modelo para ver sus estadísticas detalladas</sup>"),
      legend = list(orientation = "h", xanchor = "center", x = 0.5, y = -0.15)
    )
  
  # Distribuciones marginales (dos boxplots por eje como en Shiny GCMEval: Ensamble Total vs Seleccionados)
  # Eje X (Arriba): ΔT Spread
  px <- plot_ly(
    x = spread_df$Delta_Tas_C, type = "box", name = "Ensamble Total (36)",
    color = I("#98c166"), line = list(color = "#444444"),
    boxmean = TRUE, showlegend = FALSE
  ) %>%
    add_trace(
      x = best_df$Delta_Tas_C, type = "box", name = "Seleccionados (16)",
      color = I("#4dac26"), line = list(color = "#1b4332", width = 1.8),
      boxmean = TRUE, showlegend = FALSE
    )
  
  # Eje Y (Derecha): ΔP Spread
  py <- plot_ly(
    y = spread_df$Delta_Pr_pct, type = "box", name = "Ensamble Total (36)",
    color = I("#d196ba"), line = list(color = "#444444"),
    boxmean = TRUE, showlegend = FALSE
  ) %>%
    add_trace(
      y = best_df$Delta_Pr_pct, type = "box", name = "Seleccionados (16)",
      color = I("#d01c8b"), line = list(color = "#800e54", width = 1.8),
      boxmean = TRUE, showlegend = FALSE
    )
  
  p_composite <- subplot(
    px, plotly_empty(type = "scatter", mode = "markers"),
    p_scatter, py,
    nrows = 2, heights = c(0.14, 0.86), widths = c(0.86, 0.14), margin = 0.01,
    shareX = TRUE, shareY = TRUE, titleX = TRUE, titleY = TRUE
  )
  
  # Inyectar manejador de evento de clic para desplegar ventana modal emergente
  p_interactive <- htmlwidgets::onRender(
    p_composite,
    "function(el, x) {
      var modalId = 'plotly-model-modal';
      var backdropId = 'plotly-modal-backdrop';
      var modal = document.getElementById(modalId);
      var backdrop = document.getElementById(backdropId);
      
      if (!modal) {
        backdrop = document.createElement('div');
        backdrop.id = backdropId;
        backdrop.style.position = 'fixed';
        backdrop.style.top = '0';
        backdrop.style.left = '0';
        backdrop.style.width = '100vw';
        backdrop.style.height = '100vh';
        backdrop.style.backgroundColor = 'rgba(0,0,0,0.45)';
        backdrop.style.zIndex = '99998';
        backdrop.style.display = 'none';
        backdrop.style.backdropFilter = 'blur(2px)';
        backdrop.onclick = function() {
          modal.style.display = 'none';
          backdrop.style.display = 'none';
        };
        
        modal = document.createElement('div');
        modal.id = modalId;
        modal.style.position = 'fixed';
        modal.style.top = '50%';
        modal.style.left = '50%';
        modal.style.transform = 'translate(-50%, -50%)';
        modal.style.backgroundColor = '#ffffff';
        modal.style.padding = '22px 26px';
        modal.style.borderRadius = '12px';
        modal.style.boxShadow = '0 12px 36px rgba(0,0,0,0.3)';
        modal.style.zIndex = '99999';
        modal.style.display = 'none';
        modal.style.maxWidth = '460px';
        modal.style.width = '90%';
        modal.style.fontFamily = 'system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif';
        modal.style.border = '1px solid #e2e8f0';
        
        document.body.appendChild(backdrop);
        document.body.appendChild(modal);
      }
      
      el.on('plotly_click', function(data) {
        if (data.points && data.points.length > 0) {
          var pt = data.points[0];
          var content = pt.customdata;
          if (content) {
            modal.innerHTML = content + 
              '<div style=\"margin-top:18px; text-align:right;\">' +
              '<button id=\"close-modal-btn\" style=\"background:#1b4332; color:white; border:none; padding:8px 20px; font-size:13px; font-weight:bold; border-radius:6px; cursor:pointer;\">Cerrar</button>' +
              '</div>';
            modal.style.display = 'block';
            backdrop.style.display = 'block';
            
            document.getElementById('close-modal-btn').onclick = function() {
              modal.style.display = 'none';
              backdrop.style.display = 'none';
            };
          }
        }
      });
    }"
  )
  
  htmlwidgets::saveWidget(p_interactive, file = spread_plot_html, selfcontained = TRUE)
  cat(sprintf("[OK] Gráfico Interactivo HTML estilo GCMEval Shiny guardado: %s\n", spread_plot_html))
}

# 13. Mostrar resultados finales de todas las familias evaluadas
cat("\n" , paste(rep("=", 85), collapse=""), "\n")
cat("            RANKING GENERAL DE LAS 16 FAMILIAS EVALUADAS (CENTROAMÉRICA)\n")
cat(paste(rep("=", 85), collapse=""), "\n")
cat(sprintf("%-4s %-16s %-22s %-10s %-8s %-10s %-8s %-10s\n",
            "Rank", "Familia", "Mejor Variante", "Mean Rank", "SD Rank", "Top 10", "ΔT (°C)", "ΔP (%)"))
cat(paste(rep("-", 85), collapse=""), "\n")
for (i in seq_len(nrow(stage3))) {
  r <- stage3[i, ]
  sp_r <- spread_df[spread_df$Modelo == r$Mejor_Variante, ]
  cat(sprintf("%-4d %-16s %-22s %-10.2f %-8.2f %-10s %+6.2f°C %+6.1f%%\n",
              r$Rank_Familia, r$Familia, r$Mejor_Variante, r$Mean_Rank, r$SD_Rank, r$Freq_Top10,
              sp_r$Delta_Tas_C[1], sp_r$Delta_Pr_pct[1]))
}
cat(paste(rep("=", 85), collapse=""), "\n\n")

# 14. SELECCIÓN DEL ENSAMBLE FINAL DE 10 MODELOS (Deduplicación por Resolución y Desempeño)
# Criterios de deduplicación institucional:
# - NorESM2: NorESM2-MM (Rank 1, ~100 km) retenido frente a NorESM2-LM (Rank 11, ~250 km).
# - EC-Earth3: EC-Earth3-Veg (Rank 2, ~100 km) retenido frente a EC-Earth3-Veg-LR (Rank 5, ~250 km).
# - MPI-ESM1-2: MPI-ESM1-2-LR (Rank 4, mayor consistencia 8/9 Top 10) retenido frente a MPI-ESM1-2-HR (Rank 6).
# - INM: INM-CM4-8 (Rank 10) retenido frente a INM-CM5-0 (Rank 13).
# Descarte por menor desempeño / sesgos extremos en Centroamérica: FGOALS-g3 (Rank 15) y CanESM5 (Rank 16).

discarded_redundant <- c("EC-Earth3-Veg-LR", "MPI-ESM1-2-HR", "NorESM2-LM", "INM-CM5-0", "FGOALS-g3", "CanESM5")
final_ensemble_df <- stage3[!stage3$Familia %in% discarded_redundant, ]
final_ensemble_df$Rank_Ensamble <- seq_len(nrow(final_ensemble_df))

# Guardar lista final en selected_models.csv (en raíz y en results/)
root_selected_csv <- file.path(workspace_dir, "selected_models.csv")
results_selected_csv <- file.path(results_dir, "selected_models.csv")
results_selected_full_csv <- file.path(results_dir, "final_selected_ensemble_10models.csv")

writeLines(final_ensemble_df$Modelo_ESGF, root_selected_csv)
writeLines(final_ensemble_df$Modelo_ESGF, results_selected_csv)
write.csv(final_ensemble_df, results_selected_full_csv, row.names = FALSE)

cat(paste(rep("=", 85), collapse=""), "\n")
cat("      ENSAMBLE FINAL SELECCIONADO PARA EL MANIFIESTO Y DESCARGA (10 MODELOS)\n")
cat(paste(rep("=", 85), collapse=""), "\n")
cat(sprintf("%-4s %-16s %-24s %-10s %-8s %-10s\n",
            "N°", "Familia", "Realización (source.var)", "Mean Rank", "SD Rank", "Top 10 Freq"))
cat(paste(rep("-", 85), collapse=""), "\n")
for (i in seq_len(nrow(final_ensemble_df))) {
  r <- final_ensemble_df[i, ]
  cat(sprintf("%-4d %-16s %-24s %-10.2f %-8.2f %-10s\n",
              r$Rank_Ensamble, r$Familia, r$Modelo_ESGF, r$Mean_Rank, r$SD_Rank, r$Freq_Top10))
}
cat(paste(rep("=", 85), collapse=""), "\n")
cat(sprintf("[OK] Lista final de %d modelos guardada en: %s\n", nrow(final_ensemble_df), root_selected_csv))
cat(sprintf("[OK] Manifiesto listo para generarse ejecutando: python generate_manifest.py\n\n"))
