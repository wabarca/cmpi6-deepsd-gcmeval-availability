#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generador automático de reportes Markdown en `results/` y `results/etapas/`.
Cada paso del pipeline (Etapas 1 a 4) invoca este módulo al finalizar para
mantener actualizados los reportes con los resultados de la ejecución más reciente.
"""

import csv
import argparse
from datetime import datetime
from pathlib import Path
from collections import defaultdict


def _read_csv_dicts(path):
    p = Path(path)
    if not p.is_file():
        return []
    with open(p, "r", encoding="utf-8", errors="replace", newline="") as f:
        return list(csv.DictReader(f))


def _ensure_dirs(repo_root):
    root = Path(repo_root)
    results_dir = root / "results"
    etapas_dir = results_dir / "etapas"
    etapas_dir.mkdir(parents=True, exist_ok=True)
    return root, results_dir, etapas_dir


def update_results_index(repo_root):
    """Regenera results/README.md con enlaces a todos los reportes y artefactos actuales."""
    _, results_dir, _ = _ensure_dirs(repo_root)
    spread_pngs = sorted(results_dir.glob("future_spread_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    spread_htmls = sorted(results_dir.glob("future_spread_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    png_name = spread_pngs[0].name if spread_pngs else "future_spread_ssp585_CAM.png"
    html_name = spread_htmls[0].name if spread_htmls else "future_spread_ssp585_CAM.html"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# Resultados del Pipeline CMIP6

> Última actualización automática: `{now_str}`

Este directorio centraliza todas las salidas numéricas, gráficas y reportes en Markdown generados por el flujo de trabajo de selección, evaluación, descarga y preprocesamiento de modelos CMIP6.

## 📑 Índice de Resultados por Etapa

| Etapa | Script Principal | Reporte Markdown | Artefactos Clave |
|:---|:---|:---|:---|
| **Etapa 1: Inventario y Disponibilidad ESGF** | `esgf-query.py` | [etapa1_inventario_esgf.md](etapas/etapa1_inventario_esgf.md) | `cmip6_daily_inventory.xlsx`, `cmip6_daily_inventory.csv`, `cmip6_complete_models.csv` |
| **Etapa 2: Evaluación Climatológica y Ranking (GCMEval)** | `run_evaluation.py` / `gcmeval/run_cmip6_evaluation.R` | [etapa2_evaluacion_gcmeval.md](etapas/etapa2_evaluacion_gcmeval.md) | `ranking_E0.csv`–`ranking_E8.csv`, `ranking_summary_all_experiments.csv`, `analysis_stage1_variants.csv`, `analysis_stage2_best_variants.csv`, `analysis_stage3_families.csv`, `final_selected_ensemble_10models.csv`, `{png_name}`, `{html_name}` |
| **Etapa 3: Generación de Manifiesto de Descarga** | `generate_manifest.py` | [etapa3_manifiesto_descarga.md](etapas/etapa3_manifiesto_descarga.md) | `cmip6_manifest.tsv`, `cmip6_files.csv`, `cmip6_urls.txt` |
| **Etapa 4: Descarga, Preprocesamiento CDO y Sincronización** | `download_preprocess_cmip6.sh` | [etapa4_descarga_preprocesamiento.md](etapas/etapa4_descarga_preprocesamiento.md) | Archivos NetCDF recortados y concatenados por modelo en destino remoto/local |
"""
    (results_dir / "README.md").write_text(content, encoding="utf-8")


def update_step1_report(repo_root, variables=None, experiments=None):
    """Actualiza results/etapas/etapa1_inventario_esgf.md a partir de los CSV generados."""
    root, _, etapas_dir = _ensure_dirs(repo_root)
    inv_rows = _read_csv_dicts(root / "cmip6_daily_inventory.csv")
    complete_path = root / "cmip6_complete_models.csv"
    complete_models = []
    if complete_path.is_file():
        complete_models = [
            ln.strip() for ln in complete_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    by_family = defaultdict(list)
    for item in complete_models:
        if "." in item:
            fam, var = item.split(".", 1)
        else:
            fam, var = item, ""
        by_family[fam].append(var)

    vars_str = ", ".join(f"`{v}`" for v in variables) if variables else "10 variables diarias"
    exps_str = ", ".join(f"`{e}`" for e in experiments) if experiments else "5 experimentos (`historical`, `ssp126`, `ssp245`, `ssp370`, `ssp585`)"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Etapa 1: Inventario Global y Disponibilidad en ESGF (`esgf-query.py`)",
        "",
        f"> Actualizado automáticamente: `{now_str}`",
        "",
        f"Consulta federada de disponibilidad para {vars_str} en {exps_str}, con cruce estricto contra el catálogo de **GCMEval** (`gcmeval_models.csv`).",
        "",
        "---",
        "",
        "## 📊 Resumen Cuantitativo del Inventario",
        "",
        "| Indicador | Valor Registrado | Archivo de Respaldo |",
        "|:---|---:|:---|",
        f"| Combinaciones totales inventariadas en ESGF | **{len(inv_rows):,}** | [`cmip6_daily_inventory.csv`](../../cmip6_daily_inventory.csv) |",
        f"| Realizaciones 100% completas y validadas en GCMEval | **{len(complete_models):,}** | [`cmip6_complete_models.csv`](../../cmip6_complete_models.csv) |",
        f"| Familias de modelos únicas representadas | **{len(by_family):,}** | — |",
        "| Libro Excel consolidado | 4 hojas (`inventory`, `summary`, `selected`, `files`) | [`cmip6_daily_inventory.xlsx`](../../cmip6_daily_inventory.xlsx) |",
        "",
        "---",
        "",
        f"## 🌍 {len(complete_models)} Realizaciones Completas Candidatas ({len(by_family)} Familias Únicas)",
        "",
        "| Familia GCM | Total Variantes | Realizaciones (`variant_label`) |",
        "|:---|:---:|:---|",
    ]
    for fam in sorted(by_family):
        variants_fmt = ", ".join(f"`{v}`" for v in by_family[fam])
        lines.append(f"| `{fam}` | {len(by_family[fam])} | {variants_fmt} |")

    (etapas_dir / "etapa1_inventario_esgf.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_results_index(root)


def update_step2_report(repo_root, config=None):
    """Actualiza results/etapas/etapa2_evaluacion_gcmeval.md con experimentos, rankings y ganador."""
    root, results_dir, etapas_dir = _ensure_dirs(repo_root)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Metadatos de configuración activa
    scen = (config or {}).get("scenario", "ssp585")
    obs = (config or {}).get("observations", {})
    obs_t = obs.get("temperature", "ERA5")
    obs_p = obs.get("precipitation", "GPCP")
    regs = (config or {}).get("regions", {})
    p_reg = regs.get("primary", {}).get("name", "Central America/Mexico [CAM:6]")
    p_w = float(regs.get("primary", {}).get("weight", 1.0))
    s_cfg = regs.get("secondary", {})
    s_enabled = bool(s_cfg.get("enabled", False))
    s_w = float(s_cfg.get("weight", 0.0)) if s_enabled else 0.0
    s_desc = f"`{s_cfg.get('name', '')}` (peso {s_w:.2f})" if (s_enabled and s_w > 0) else "Desactivada (peso `0.0`)"

    summary_rows = _read_csv_dicts(results_dir / "ranking_summary_all_experiments.csv")
    stage1_rows = _read_csv_dicts(results_dir / "analysis_stage1_variants.csv")
    stage3_rows = _read_csv_dicts(results_dir / "analysis_stage3_families.csv")
    ensemble_rows = _read_csv_dicts(results_dir / "final_selected_ensemble_10models.csv")
    spread_rows = _read_csv_dicts(results_dir / "future_spread_data.csv")

    spread_by_model = {r.get("Modelo", ""): r for r in spread_rows}
    ensemble_rank_by_fam = {r.get("Familia", ""): r.get("Rank_Ensamble", "") for r in ensemble_rows}
    summary_by_id = {r.get("ID_Interno", r.get("Modelo", "")): r for r in summary_rows}

    # Detectar experimentos presentes en ranking_summary_all_experiments.csv
    exp_ids = []
    if summary_rows:
        for k in summary_rows[0].keys():
            if k.startswith("Rank_"):
                exp_ids.append(k[len("Rank_"):])

    # Detectar gráficos más recientes
    spread_pngs = sorted(results_dir.glob("future_spread_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    spread_htmls = sorted(results_dir.glob("future_spread_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    png_name = spread_pngs[0].name if spread_pngs else "future_spread_ssp585_CAM.png"
    html_name = spread_htmls[0].name if spread_htmls else "future_spread_ssp585_CAM.html"

    lines = [
        "# Etapa 2: Evaluación Climatológica y Selección de Ensamble (GCMEval)",
        "",
        f"> Actualizado automáticamente: `{now_str}`",
        "",
        f"- **Región Primaria**: `{p_reg}` (peso `{p_w:.2f}`)",
        f"- **Región Secundaria**: {s_desc}",
        f"- **Escenario**: `{scen}` | **Referencias**: `{obs_t}` (`tas`), `{obs_p}` (`pr`)",
        f"- **Universo evaluado**: **{len(stage1_rows)}** realizaciones en **{len(stage3_rows)}** familias únicas",
        "",
        "---",
        "",
        f"## 1. Resultados por Experimento ({len(exp_ids)} Experimentos)",
        "",
        "| Exp | Enfoque | Puesto #1 (Score) | Puesto #2 (Score) | Puesto #3 (Score) | Archivo CSV |",
        "|:---:|:---|:---|:---|:---|:---|",
    ]

    for exp_id in exp_ids:
        exp_csv = results_dir / f"ranking_{exp_id}.csv"
        exp_rows = _read_csv_dicts(exp_csv)
        desc = exp_rows[0].get("Descripcion", exp_id) if exp_rows else exp_id
        top_cells = []
        for idx in range(3):
            if idx < len(exp_rows):
                r = exp_rows[idx]
                top_cells.append(f"`{r['Modelo']}` ({r['Score']})")
            else:
                top_cells.append("—")
        lines.append(
            f"| **{exp_id}** | {desc} | {top_cells[0]} | {top_cells[1]} | {top_cells[2]} | [`ranking_{exp_id}.csv`](../ranking_{exp_id}.csv) |"
        )

    lines.extend([
        "",
        "---",
        "",
        f"## 2. Ranking Consolidado por Experimento ({len(stage1_rows)} Realizaciones)",
        "",
        "Ordenado por **Ranking Medio** ([`ranking_summary_all_experiments.csv`](../ranking_summary_all_experiments.csv) y [`analysis_stage1_variants.csv`](../analysis_stage1_variants.csv)):",
        "",
    ])

    exp_headers = " | ".join(exp_ids)
    exp_align = " | ".join([":---:"] * len(exp_ids))
    lines.append(f"| Modelo | {exp_headers} | Mean Rank | SD | Top 10 |")
    lines.append(f"|:---|{exp_align}|:---:|:---:|:---:|")
    for s1 in stage1_rows:
        key = s1.get("ID_Interno", s1.get("Modelo", ""))
        sr = summary_by_id.get(key, {})
        exp_vals = " | ".join(
            f"{sr.get(f'Rank_{e}', '—')} ({sr.get(f'Score_{e}', '—')})" for e in exp_ids
        )
        lines.append(
            f"| `{s1.get('Modelo', '')}` | {exp_vals} | **{s1.get('Mean_Rank', '')}** | {s1.get('SD_Rank', '')} | {s1.get('Freq_Top10', '')}/{len(exp_ids)} |"
        )

    lines.extend([
        "",
        "---",
        "",
        f"## 3. Ranking Final de Familias ({len(stage3_rows)} Familias)",
        "",
        "| Rank | Familia GCM | Variante Óptima | Modelo ESGF | Ranking Medio (SD) | Frec. Top 10 | Variantes | ΔT (°C) | ΔP (%) | Estado en Ensamble |",
        "|:---:|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---|",
    ])
    for r in stage3_rows:
        fam = r.get("Familia", "")
        best_m = r.get("Mejor_Variante", "")
        var_name = best_m.split(".", 1)[1] if "." in best_m else best_m
        sp = spread_by_model.get(best_m, {})
        dt = sp.get("Delta_Tas_C", "NA")
        dp = sp.get("Delta_Pr_pct", "NA")
        dt_str = f"{float(dt):+.2f}" if dt not in ("", "NA", None) else "NA"
        dp_str = f"{float(dp):+.2f}%" if dp not in ("", "NA", None) else "NA"
        ens_rank = ensemble_rank_by_fam.get(fam, "")
        estado = f"✅ Seleccionado (#{ens_rank})" if ens_rank else "❌ Descartado"
        lines.append(
            f"| **{r.get('Rank_Familia', '')}** | `{fam}` | `{var_name}` | `{r.get('Modelo_ESGF', '')}` | "
            f"**{r.get('Mean_Rank', '')}** (±{r.get('SD_Rank', '')}) | {r.get('Freq_Top10', '')} | "
            f"{r.get('Total_Variantes_Familia', '')} | {dt_str} | {dp_str} | {estado} |"
        )

    lines.extend([
        "",
        "---",
        "",
        f"## 4. Ranking Final Ganador: Ensamble Seleccionado ({len(ensemble_rows)} Modelos)",
        "",
        "Exportado a [`final_selected_ensemble_10models.csv`](../final_selected_ensemble_10models.csv) y [`selected_models.csv`](../../selected_models.csv):",
        "",
        "| Posición Ensamble | Rank Familia | Familia | Realización (`NOMBRE.variante` ESGF) | Mean Rank | SD Rank | Frec. Top 10 |",
        "|:---:|:---:|:---|:---|---:|---:|:---:|",
    ])
    for r in ensemble_rows:
        lines.append(
            f"| **{r.get('Rank_Ensamble', '')}** | {r.get('Rank_Familia', '')} | `{r.get('Familia', '')}` | "
            f"`{r.get('Modelo_ESGF', '')}` | {r.get('Mean_Rank', '')} | {r.get('SD_Rank', '')} | {r.get('Freq_Top10', '')} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 5. Espacio de Incertidumbre y Spread Futuro (ΔT vs ΔP)",
        "",
        f"![Dispersión de Cambio Climático Futuro](../{png_name})",
        "",
        f"- **Gráfico interactivo (HTML / Plotly)**: [`{html_name}`](../{html_name})",
        "- **Datos tabulares del spread**: [`future_spread_data.csv`](../future_spread_data.csv)",
    ])

    (etapas_dir / "etapa2_evaluacion_gcmeval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_results_index(root)


def update_step3_report(repo_root, manifest_path="cmip6_manifest.tsv", input_csv="selected_models.csv", period_ranges=None):
    """Actualiza results/etapas/etapa3_manifiesto_descarga.md a partir del manifiesto TSV generado."""
    root, _, etapas_dir = _ensure_dirs(repo_root)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    m_path = root / manifest_path if not Path(manifest_path).is_absolute() else Path(manifest_path)

    total_files = 0
    combos = set()
    models = set()
    exps = set()
    vars_set = set()
    if m_path.is_file():
        with open(m_path, "r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                total_files += 1
                m = row.get("source_id", "")
                v = row.get("variant_label", "")
                e = row.get("experiment_id", "")
                va = row.get("variable_id", "")
                models.add(f"{m}.{v}" if v else m)
                exps.add(e)
                vars_set.add(va)
                combos.add((m, v, e, va))

    lines = [
        "# Etapa 3: Generación del Manifiesto de Descarga (`generate_manifest.py`)",
        "",
        f"> Actualizado automáticamente: `{now_str}`",
        "",
        f"Manifiesto generado a partir de [`{Path(input_csv).name}`](../../{Path(input_csv).name}).",
        "",
        "---",
        "",
        "## 📦 Resumen de Artefactos Generados",
        "",
        "| Artefacto | Contenido | Total de Registros | Archivo |",
        "|:---|:---|---:|:---|",
        f"| Manifiesto técnico TSV | Metadatos, `replica_urls`, checksums SHA-256 y tamaños | **{total_files:,}** archivos NetCDF | [`{m_path.name}`](../../{m_path.name}) |",
        f"| Catálogo CSV de archivos | Detalle tabular de archivos NetCDF | **{total_files:,}** archivos NetCDF | [`cmip6_files.csv`](../../cmip6_files.csv) |",
        f"| Lista plana de URLs | Enlaces directos HTTPS para descarga | **{total_files:,}** URLs | [`cmip6_urls.txt`](../../cmip6_urls.txt) |",
        "",
        "---",
        "",
        "## 🧩 Cobertura del Manifiesto",
        "",
        f"- **Modelos incluidos ({len(models)})**: {', '.join(f'`{m}`' for m in sorted(models))}",
        f"- **Experimentos ({len(exps)})**: {', '.join(f'`{e}`' for e in sorted(exps))}",
        f"- **Variables diarias ({len(vars_set)})**: {', '.join(f'`{v}`' for v in sorted(vars_set))}",
        f"- **Total de combinaciones dataset (`modelo × experimento × variable`)**: **{len(combos):,}**",
    ]
    if period_ranges:
        lines.append("- **Períodos configurados**: " + ", ".join(f"`{k}` ({v[0]}–{v[1]})" for k, v in period_ranges.items()))

    (etapas_dir / "etapa3_manifiesto_descarga.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_results_index(root)


def update_step4_report(repo_root, total_combos=0, processed=0, skipped=0, failed=0,
                        lon_box="", lat_box="", hist_period="", ssp_period="", dest=""):
    """Actualiza results/etapas/etapa4_descarga_preprocesamiento.md con el resumen de ejecución."""
    root, _, etapas_dir = _ensure_dirs(repo_root)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "# Etapa 4: Descarga, Preprocesamiento CDO y Sincronización (`download_preprocess_cmip6.sh`)",
        "",
        f"> Actualizado automáticamente: `{now_str}`",
        "",
        "## 📊 Resumen de la Última Ejecución",
        "",
        "| Métrica | Valor |",
        "|:---|---:|",
        f"| Total combinaciones evaluadas | **{total_combos}** |",
        f"| Procesadas en la sesión | **{processed}** |",
        f"| Omitidas (ya existentes en destino) | **{skipped}** |",
        f"| Combinaciones con fallos | **{failed}** |",
        "",
        "## ⚙️ Parámetros Aplicados",
        "",
        "| Parámetro | Valor |",
        "|:---|:---|",
        f"| Dominio espacial (`sellonlatbox`) | Longitud `{lon_box}`, Latitud `{lat_box}` |",
        f"| Período `historical` (`selyear`) | `{hist_period}` |",
        f"| Período escenarios SSP (`selyear`) | `{ssp_period}` |",
        f"| Destino final | `{dest}` |",
    ]
    (etapas_dir / "etapa4_descarga_preprocesamiento.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    update_results_index(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Actualiza reportes Markdown por etapa.")
    parser.add_argument("--step", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--total", type=int, default=0)
    parser.add_argument("--processed", type=int, default=0)
    parser.add_argument("--skipped", type=int, default=0)
    parser.add_argument("--failed", type=int, default=0)
    parser.add_argument("--lon-box", default="")
    parser.add_argument("--lat-box", default="")
    parser.add_argument("--hist-period", default="")
    parser.add_argument("--ssp-period", default="")
    parser.add_argument("--dest", default="")
    args = parser.parse_args()

    if args.step == 1:
        update_step1_report(args.repo_root)
    elif args.step == 2:
        update_step2_report(args.repo_root)
    elif args.step == 3:
        update_step3_report(args.repo_root)
    elif args.step == 4:
        update_step4_report(
            args.repo_root,
            total_combos=args.total,
            processed=args.processed,
            skipped=args.skipped,
            failed=args.failed,
            lon_box=args.lon_box,
            lat_box=args.lat_box,
            hist_period=args.hist_period,
            ssp_period=args.ssp_period,
            dest=args.dest,
        )
