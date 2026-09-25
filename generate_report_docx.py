import os
import sys
import pandas as pd
import docx
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

def set_cell_background(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_cell_margins(cell, top=80, bottom=80, left=100, right=100):
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = parse_xml(f'<w:tcMar {nsdecls("w")}><w:top w:w="{top}" w:type="dxa"/><w:bottom w:w="{bottom}" w:type="dxa"/><w:left w:w="{left}" w:type="dxa"/><w:right w:w="{right}" w:type="dxa"/></w:tcMar>')
    tcPr.append(tcMar)

def add_callout(doc, text, title="NOTA IMPORTANTE", color_hex="1B365D", fill_hex="F0F4F8"):
    tbl = doc.add_table(rows=1, cols=1)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    cell = tbl.cell(0, 0)
    set_cell_background(cell, fill_hex)
    set_cell_margins(cell, top=120, bottom=120, left=160, right=160)
    
    tcPr = cell._tc.get_or_add_tcPr()
    borders = parse_xml(f'<w:tcBorders {nsdecls("w")}><w:left w:val="single" w:sz="24" w:space="0" w:color="{color_hex}"/><w:top w:val="none"/><w:right w:val="none"/><w:bottom w:val="none"/></w:tcBorders>')
    tcPr.append(borders)
    
    p = cell.paragraphs[0]
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(2)
    r_title = p.add_run(f"📌 {title}: ")
    r_title.bold = True
    r_title.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    r_title.font.size = Pt(10)
    
    r_text = p.add_run(text)
    r_text.font.size = Pt(9.5)
    r_text.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    doc.add_paragraph()

def build_comprehensive_word_document(output_path):
    doc = Document()
    
    # Page setup
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
        
        # Header & Footer
        header = section.header
        hp = header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        hrun = hp.add_run("MARN El Salvador | Evaluación, Ranking y Selección CMIP6 (Centroamérica)")
        hrun.font.size = Pt(8.5)
        hrun.font.color.rgb = RGBColor(0x88, 0x88, 0x88)
        
        footer = section.footer
        fp = footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        frun = fp.add_run("Proyecto DeepSD Downscaling - Fase 3 | Escenarios de Cambio Climático")
        frun.font.size = Pt(8.5)
        frun.font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    # Styles
    normal_style = doc.styles['Normal']
    normal_style.font.name = 'Calibri'
    normal_style.font.size = Pt(11)
    normal_style.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
    normal_style.paragraph_format.line_spacing = 1.15
    normal_style.paragraph_format.space_after = Pt(6)

    # Title
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(0)
    title_p.paragraph_format.space_after = Pt(4)
    r = title_p.add_run("METODOLOGÍA DE EVALUACIÓN CLIMATOLÓGICA, RANKING Y SELECCIÓN DE MODELOS GLOBALES CMIP6 PARA CENTROAMÉRICA")
    r.bold = True
    r.font.size = Pt(17)
    r.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(16)
    r_sub = sub_p.add_run("Marco de Evaluación Multicriterio (GCMEval), Batería de Sensibilidad Meteorológica, Criterios de Remoción y Selección de Ensamble para Downscaling Estadístico (DeepSD)")
    r_sub.font.size = Pt(11.5)
    r_sub.font.color.rgb = RGBColor(0x4A, 0x60, 0x7A)
    r_sub.italic = True

    # Metadata
    meta_p = doc.add_paragraph()
    meta_p.paragraph_format.space_after = Pt(14)
    r_meta = meta_p.add_run("Ministerio de Medio Ambiente y Recursos Naturales (MARN), El Salvador\nDirección General del Observatorio de Amenazas y Recursos Naturales (DOA)\nAutor: Will Abarca (wabarca@ambiente.gob.sv)\nFecha: Septiembre 2026")
    r_meta.font.size = Pt(9.5)
    r_meta.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    # 1. Resumen Ejecutivo
    doc.add_heading("1. Resumen Ejecutivo", level=1)
    doc.add_paragraph(
        "El presente informe establece la base científica y metodológica para la selección rigurosa de Modelos Climáticos "
        "Globales (GCM) de la 6ª fase del Proyecto de Intercomparación de Modelos Acoplados (CMIP6), destinados a forzar "
        "la cadena automatizada de reducción de escala estadística (DeepSD) en la región de Centroamérica y México (Región IPCC SREX CAM:6)."
    )
    doc.add_paragraph(
        "A partir de un universo inicial de 62 familias de modelos y 2,335 combinaciones en ESGF MetaGrid, se aplicó un filtro "
        "técnico estricto de completitud (10 variables diarias simultáneas, 5 experimentos climáticos y cobertura temporal 1950–2100). "
        "Las 36 realizaciones resultantes (pertenecientes a 16 familias únicas) fueron evaluadas en el motor analítico de GCMEval "
        "frente a reanálisis ERA5 (temperatura) y satélite GPCP v2.3 (precipitación) a través de 9 experimentos de sensibilidad ponderada."
    )

    add_callout(
        doc,
        "La evaluación unánime posicionó a NorESM2-MM (Rank #1.00 en los 9 experimentos) y EC-Earth3-Veg (Rank #2.22) como las "
        "familias de mayor fidelidad física y estabilidad regional, seguidas de UKESM1-0-LL (#5.28) y MPI-ESM1-2-LR (#6.11). "
        "Se aplicaron criterios rigurosos de desduplicación genealógica y discriminación por resolución espacial para seleccionar "
        "exactamente el mejor miembro por familia.",
        title="SÍNTESIS DE RESULTADOS"
    )

    # 2. Marco Teórico, Climatología Dinámica Regional y Referencias Observacionales
    doc.add_heading("2. Marco Teórico, Climatología Dinámica Regional y Referencias de Evaluación", level=1)
    doc.add_paragraph(
        "La evaluación y selección de Modelos Climáticos Globales (GCM) en América Central (dominio IPCC SREX CAM:6) "
        "no puede fundamentarse en promedios globales o anuales simplificados. Centroamérica es reconocida en el "
        "Sexto Informe de Evaluación del IPCC (AR6 WGI, Cap. 10 y Atlas Regional) como uno de los 'Hotspots' más vulnerables "
        "y complejos del planeta debido a su fisiografía estrecha y a la confluencia de forzamientos oceánico-atmosféricos duales "
        "(Océano Pacífico Tropical Oriental y Mar Caribe / Océano Atlántico Tropical Norte)."
    )

    doc.add_heading("2.1 Procesos Físicos y Climatología Regional de Centroamérica", level=2)
    doc.add_paragraph(
        "Para garantizar que los modelos seleccionados posean alta fidelidad física, el diseño de la evaluación incorpora "
        "los procesos meteorológicos descritos en la literatura científica peer-reviewed:"
    )

    fundamentos = [
        ("Complejidad Topográfica y Efecto Barrera Orográfico",
         "La Cordillera Central Centroamericana actúa como una barrera orográfica que divide al istmo en dos vertientes climáticas "
         "contrastantes: la vertiente del Caribe, con precipitaciones abundantes durante casi todo el año producto del ascenso forzado "
         "de los vientos alisios del noreste, y la vertiente del Pacífico, caracterizada por una marcada estación seca y lluviosa "
         "(Giorgi et al., 2014; Hidalgo et al., 2017). Los modelos globales deben capturar este marcado gradiente transversal."),
        
        ("El Chorro de Bajos Niveles del Caribe (CLLJ - Caribbean Low-Level Jet)",
         "Amador (1998, 2008) y Muñoz et al. (2008) documentaron que el CLLJ es la principal corriente de transporte de vapor de agua "
         "hacia Centroamérica. Su aceleración estacional en julio-agosto y en invierno modula la divergencia de humedad y controla "
         "directamente la intensidad de la precipitación sobre el istmo (Cook & Vizy, 2010; Durán-Quesada et al., 2010)."),
        
        ("Ciclo Anual Bimodal y la Canícula o Veranillo (Mid-Summer Drought - MSD)",
         "La vertiente Pacífica exhibe un régimen bimodal con dos máximos de precipitación (mayo-junio y septiembre-octubre) separados "
         "por una disminución relativa de las lluvias en julio-agosto conocida como Canícula o Veranillo (Magaña et al., 1999). "
         "Maldonado et al. (2016) demostraron que la Canícula resulta de la interacción del CLLJ con anomalías de temperatura superficial "
         "del mar (TSM). Simular adecuadamente la Canícula es vital para la agricultura de subsistencia y los recursos hídricos."),
        
        ("Migración de la Zona de Convergencia Intertropical (ZCIT)",
         "El desplazamiento meridional de la ZCIT define el inicio (mayo) y la finalización (noviembre) de la temporada lluviosa "
         "en el Pacífico mesoamericano, alcanzando su posición más septentrional en septiembre-octubre durante el pico de actividad "
         "de ondas del este y ciclones tropicales (Taylor et al., 2012; Vichot-Llano et al., 2021)."),
        
        ("Teleconexiones ENOS y Dipolo Térmico de TSM",
         "Enfield & Alfaro (1999) y Alfaro (2007) establecieron que las fases de El Niño / Oscilación del Sur (ENOS) intensifican "
         "las sequías en el Corredor Seco Centroamericano, mientras que La Niña produce eventos hidrometeorológicos extremos. "
         "La evaluación de la variabilidad interanual mide la respuesta de los GCM a estas teleconexiones.")
    ]

    for tit, desc in fundamentos:
        p_f = doc.add_paragraph()
        p_f.paragraph_format.left_indent = Inches(0.2)
        p_f.paragraph_format.space_after = Pt(4)
        r_t = p_f.add_run(f"• {tit}: ")
        r_t.bold = True
        r_t.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
        p_f.add_run(desc)

    doc.add_heading("2.2 Referencias Climatológicas Históricas de Evaluación (1981–2010)", level=2)
    doc.add_paragraph(
        "Para evaluar cuantitativamente el desempeño de los modelos en el período histórico común 1981–2010, GCMEval "
        "utiliza como 'verdad del terreno' (ground truth) los dos conjuntos de datos observacionales de mayor consenso internacional:"
    )

    p_ref1 = doc.add_paragraph()
    p_ref1.paragraph_format.left_indent = Inches(0.2)
    p_ref1.paragraph_format.space_after = Pt(4)
    r_r1 = p_ref1.add_run("1. Temperatura (`tas`) — ERA5 Reanalysis (ECMWF, Hersbach et al., 2020): ")
    r_r1.bold = True
    r_r1.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    p_ref1.add_run(
        "Reanálisis atmosférico global de 5ª generación con resolución horizontal de ~31 km (0.25°). "
        "Asimila billones de observaciones satelitales, sondeos y estaciones de superficie, resolviendo con gran precisión "
        "el balance de radiación, los gradientes térmicos costa-montaña y los ciclos diurnos sobre el relieve centroamericano."
    )

    p_ref2 = doc.add_paragraph()
    p_ref2.paragraph_format.left_indent = Inches(0.2)
    p_ref2.paragraph_format.space_after = Pt(6)
    r_r2 = p_ref2.add_run("2. Precipitación (`pr`) — GPCP v2.3 (Global Precipitation Climatology Project, Adler et al., 2018): ")
    r_r2.bold = True
    r_r2.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
    p_ref2.add_run(
        "Producto global mensual (2.5°) que combina radiometría satelital infrarroja y de microondas con más de 6,500 estaciones "
        "pluviométricas de superficie. Es el estándar de oro de la OMM y del IPCC para evaluar la precipitación tropical continua "
        "tanto sobre tierra firme como en los océanos adyacentes (Pacífico Este y Mar Caribe)."
    )

    doc.add_paragraph(
        "Contra estas referencias, GCMEval computa cuatro métricas estadísticas fundamentales para 5 períodos estacionales "
        "(Media Anual [ANN], Invierno [DJF], Primavera [MAM], Verano [JJA] y Otoño [SON]):\n"
        "  a) Sesgo Medio Climatológico (Bias): Mide la sobre/subestimación sistemática regional.\n"
        "  b) Correlación Espacial de Pearson (r): Mide la fidelidad en la ubicación de los patrones espaciales y centros de acción.\n"
        "  c) Ratio de Variabilidad Espacial (σ_GCM / σ_Ref): Evalúa si el modelo reproduce la amplitud real de los gradientes sin aplanarlos.\n"
        "  d) Error Cuadrático Medio Centrado (CRMSE): Cuantifica la magnitud neta del error espacial libre de sesgo."
    )

    # 3. Interpretación de Pesos en GCMEval y Diseño de los 9 Experimentos
    doc.add_heading("3. Justificación Científica y Diseño de los 9 Experimentos de Sensibilidad", level=1)
    doc.add_paragraph(
        "Para evitar que un modelo sea seleccionado por una 'compensación artificial de errores' (por ejemplo, simular una temperatura "
        "excelente pero una precipitación completamente deficiente, o acertar en el promedio anual ocultando fallos severos en la época seca), "
        "se diseñó una batería de 9 experimentos de sensibilidad (E0 a E8). Cada experimento modula los pesos relativos de variables y "
        "estaciones climáticas según prioridades físicas y sectoriales:"
    )

    # Table of weights
    table_w = doc.add_table(rows=1, cols=12)
    table_w.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_w.autofit = False

    w_headers = ["Exp", "Nombre", "w_tas", "w_pr", "w_ann", "w_djf", "w_mam", "w_jja", "w_son", "w_bias", "w_sd", "w_sc/rmse"]
    w_widths = [Inches(0.4), Inches(1.8), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.45), Inches(0.65)]

    hdr_row = table_w.rows[0]
    for idx, text in enumerate(w_headers):
        cell = hdr_row.cells[idx]
        cell.width = w_widths[idx]
        set_cell_background(cell, "1B365D")
        set_cell_margins(cell, top=60, bottom=60, left=40, right=40)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(8.0)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    weights_data = [
        ("E0", "Control / Balance General", "1", "1", "1", "1", "1", "1", "1", "1", "1", "1 / 1"),
        ("E1", "Énfasis en Temperatura", "2", "1", "1", "1", "1", "1", "1", "1", "1", "1 / 1"),
        ("E2", "Énfasis en Precipitación", "1", "2", "1", "1", "1", "1", "1", "1", "1", "1 / 1"),
        ("E3", "Época Seca (DJF+MAM)", "1", "1", "1", "2", "2", "0", "0", "1", "1", "1 / 1"),
        ("E4", "Época Lluviosa (MAM+JJA+SON)", "1", "1", "1", "0", "2", "2", "2", "1", "1", "1 / 1"),
        ("E5", "Temperatura en Época Seca", "2", "1", "1", "2", "2", "0", "0", "1", "1", "1 / 1"),
        ("E6", "Precipitación en Época Lluviosa", "1", "2", "1", "0", "2", "2", "2", "1", "1", "1 / 1"),
        ("E7", "Termodinámica Pura (Solo Temp)", "2", "0", "1", "1", "1", "1", "1", "1", "1", "1 / 1"),
        ("E8", "Hidrología Pura (Solo Lluvia)", "0", "2", "1", "1", "1", "1", "1", "1", "1", "1 / 1")
    ]

    for r_idx, row_vals in enumerate(weights_data):
        row = table_w.add_row()
        bg_col = "F9FBFD" if r_idx % 2 == 0 else "FFFFFF"
        for c_idx, val in enumerate(row_vals):
            cell = row.cells[c_idx]
            cell.width = w_widths[c_idx]
            set_cell_background(cell, bg_col)
            set_cell_margins(cell, top=50, bottom=50, left=40, right=40)
            p = cell.paragraphs[0]
            if c_idx in [0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(val)
            if c_idx == 0:
                r.bold = True
            r.font.size = Pt(8.0)

    doc.add_paragraph()

    doc.add_heading("3.1 Descripción Climatológica y Aplicación de Cada Experimento", level=2)
    exp_descriptions = [
        ("E0 — Control / Balance General (ERA5 50% + GPCP 50%)",
         "Evaluación basal equilibrada. Mide el balance de energía y masa anual promedio en el istmo, sirviendo de referencia sin sesgos hacia ninguna estación o variable."),
        
        ("E1 — Énfasis en Temperatura (ERA5 67% + GPCP 33%)",
         "Prioriza el balance radiativo de onda corta y larga y los gradientes térmicos superficie-mar (TSM Caribe vs Pacífico), motor térmico del gradiente de presión que modula el CLLJ."),
        
        ("E2 — Énfasis en Precipitación (ERA5 33% + GPCP 67%)",
         "Prioriza la física convectiva tropical profunda y la interacción de la masa de aire húmedo con la topografía, esencial para cuencas hidrográficas y agricultura."),
        
        ("E3 — Época Seca y Estiaje (Énfasis en DJF + MAM)",
         "Evalúa el comportamiento de los modelos durante el período de vientos alisios acelerados y frentes fríos ('Nortes'). Crítico para modelar la severidad de sequías, caudales mínimos en ríos y el Corredor Seco."),
        
        ("E4 — Época Lluviosa y Monzón (Énfasis en MAM + JJA + SON)",
         "Evalúa la temporada de desarrollo de ondas tropicales, ciclones y la dinámica de la Canícula (MSD). Indispensable para la gestión de riesgos de inundación y recarga de acuíferos."),
        
        ("E5 — Temperatura en Época Seca (Temp doble en DJF + MAM)",
         "Analiza el período de máxima insolación y menor nubosidad (marzo-abril-mayo), crucial para evaluar olas de calor, riesgo de incendios forestales y estrés hídrico por evapotranspiración máxima."),
        
        ("E6 — Precipitación en Época Lluviosa (Lluvia doble en MAM + JJA + SON)",
         "Pone a prueba la capacidad de reproducir la estructura bimodal de la lluvia y la intensidad de eventos de precipitación extrema en los meses más activos (septiembre-octubre)."),
        
        ("E7 — Termodinámica Pura (100% ERA5, Peso Lluvia = 0)",
         "Aislamiento térmico absoluto. Evalúa la dinámica atmosférica de gran escala y temperatura eliminando la alta incertidumbre espacial asociada a la parametrización de nubes convectivas."),
        
        ("E8 — Hidrología Pura (100% GPCP, Peso Temp = 0)",
         "Aislamiento pluviométrico absoluto. Somete a los modelos al escrutinio estricto de la lluvia frente a observaciones satelitales, evaluando el ciclo hidrológico sin auxilio del campo térmico.")
    ]

    for e_tit, e_desc in exp_descriptions:
        p_ed = doc.add_paragraph()
        p_ed.paragraph_format.left_indent = Inches(0.2)
        p_ed.paragraph_format.space_after = Pt(3)
        r_et = p_ed.add_run(f"• {e_tit}: ")
        r_et.bold = True
        r_et.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
        p_ed.add_run(e_desc)

    # 4. Tabla de Resultados Detallados de los 36 Modelos en los 9 Experimentos
    doc.add_heading("4. Ranking y Puntajes de las 36 Realizaciones en los 9 Experimentos", level=1)
    doc.add_paragraph(
        "La siguiente tabla consolida las posiciones individuales obtenidas por las 36 realizaciones candidatas evaluadas "
        "a través de los 9 experimentos (E0 a E8), ordenadas por su Ranking Medio final (*Mean Rank*):"
    )

    # Load summary CSV and stage 1 statistics
    summary_csv = os.path.abspath(os.path.join(os.path.dirname(__file__), "results", "ranking_summary_all_experiments.csv"))
    stage1_csv  = os.path.abspath(os.path.join(os.path.dirname(__file__), "results", "analysis_stage1_variants.csv"))
    
    if os.path.exists(summary_csv) and os.path.exists(stage1_csv):
        df_sum = pd.read_csv(summary_csv)
        df_st1 = pd.read_csv(stage1_csv)
        df_merged = pd.merge(df_st1, df_sum[["Modelo", "Rank_E0", "Score_E0", "Rank_E1", "Score_E1", "Rank_E2", "Score_E2", "Rank_E3", "Score_E3", "Rank_E4", "Score_E4", "Rank_E5", "Score_E5", "Rank_E6", "Score_E6", "Rank_E7", "Score_E7", "Rank_E8", "Score_E8"]], on="Modelo")
        df_merged = df_merged.sort_values(by=["Mean_Rank", "SD_Rank"]).reset_index(drop=True)
        
        table_all = doc.add_table(rows=1, cols=13)
        table_all.alignment = WD_TABLE_ALIGNMENT.CENTER
        table_all.autofit = False
        
        cols_hdr = ["#", "Modelo / Variante", "E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "Mean", "SD"]
        w_cols = [Inches(0.3), Inches(1.8), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.38), Inches(0.5), Inches(0.45)]
        
        hdr_row = table_all.rows[0]
        for idx, text in enumerate(cols_hdr):
            cell = hdr_row.cells[idx]
            cell.width = w_cols[idx]
            set_cell_background(cell, "1B365D")
            set_cell_margins(cell, top=50, bottom=50, left=30, right=30)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(7.5)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

        for r_idx, r_data in df_merged.iterrows():
            row = table_all.add_row()
            bg_col = "E5F9E5" if r_data["Mean_Rank"] <= 5 else ("F0F8FF" if r_data["Mean_Rank"] <= 10 else ("FFFFFF" if r_data["Mean_Rank"] <= 20 else "FFF0F0"))
            
            vals = [
                str(r_idx + 1),
                str(r_data["Modelo"]),
                f"{r_data['Rank_E0']:.0f}",
                f"{r_data['Rank_E1']:.0f}",
                f"{r_data['Rank_E2']:.0f}",
                f"{r_data['Rank_E3']:.0f}",
                f"{r_data['Rank_E4']:.0f}",
                f"{r_data['Rank_E5']:.0f}",
                f"{r_data['Rank_E6']:.0f}",
                f"{r_data['Rank_E7']:.0f}",
                f"{r_data['Rank_E8']:.0f}",
                f"{r_data['Mean_Rank']:.2f}",
                f"{r_data['SD_Rank']:.2f}"
            ]
            
            for c_idx, val in enumerate(vals):
                cell = row.cells[c_idx]
                cell.width = w_cols[c_idx]
                set_cell_background(cell, bg_col)
                set_cell_margins(cell, top=40, bottom=40, left=30, right=30)
                p = cell.paragraphs[0]
                if c_idx != 1:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(val)
                if c_idx in [0, 1, 11]:
                    r.bold = True
                r.font.size = Pt(7.5)

    doc.add_paragraph()

    # 5. Criterios de Selección, Desduplicación y Remoción de Modelos
    doc.add_heading("5. Criterios de Selección, Desduplicación y Remoción de Modelos", level=1)
    doc.add_paragraph(
        "Para transformar el ranking general de 36 realizaciones en una recomendación ejecutable de ensamble multi-modelo, "
        "se aplicó un protocolo de filtrado basado en tres reglas de exclusión científica:"
    )

    criterios = [
        ("1. Desduplicación Intra-Familia (Independencia Estructural)",
         "Centros de modelado como MPI-M (10 realizaciones evaluadas), IPSL (6 realizaciones) o Met Office (5 realizaciones) "
         "publicaron múltiples corridas con variaciones en las condiciones iniciales. Incluir varias variantes del mismo código "
         "sesga el ensamble y sobrepondera una física idéntica. Se seleccionó estrictamente la variante con menor Mean Rank y mayor estabilidad (SD Rank)."),
        
        ("2. Discriminación por Resolución Espacial dentro de la Misma Familia",
         "Existen familias donde la única diferencia es la resolución de malla. En todos los casos se retuvo únicamente la de mejor desempeño comprobado:\n"
         "  • NorESM2-MM (~1°) vs NorESM2-LM (~2°): NorESM2-MM obtuvo el puesto #1 unánime (Mean Rank 1.00), mientras que NorESM2-LM cayó al puesto #11 (Mean Rank 26.67). Se retiene NorESM2-MM.\n"
         "  • EC-Earth3-Veg (~100 km) vs EC-Earth3-Veg-LR (~250 km): La versión de mayor resolución EC-Earth3-Veg superó ampliamente a la versión LR (Rank #2.22 vs #9.89). Se retiene EC-Earth3-Veg.\n"
         "  • MPI-ESM1-2-LR vs MPI-ESM1-2-HR: A pesar de que HR posee mayor resolución espacial nominal, la variante MPI-ESM1-2-LR.r5i1p1f1 demostró un desempeño global superior y mayor estabilidad (Rank #6.11 vs #10.50)."),
        
        ("3. Exclusión por Sesgos Severos y Sensibilidad Climática No Física",
         "  • CanESM5 (#35.00): Sesgo seco extremo (-24% a -31%) y sensibilidad climática excesiva (ECS > 5.6°C), clasificado en el rango inferior en todos los experimentos.\n"
         "  • FGOALS-g3 (#33.00) y MIROC6 (#31.56): Dificultades severas en representar la orografía estrecha de Centroamérica y el ciclo de la Canícula.\n"
         "  • INM-CM4-8 (#26.33) e INM-CM5-0 (#28.67): Baja sensibilidad térmica (+2.5°C) y señal anómala de incremento de precipitación (+5.9%), divergente del consenso regional.")
    ]

    for tit, desc in criterios:
        p_cr = doc.add_paragraph()
        p_cr.paragraph_format.left_indent = Inches(0.2)
        p_cr.paragraph_format.space_after = Pt(6)
        r_t = p_cr.add_run(f"• {tit}:\n")
        r_t.bold = True
        r_t.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
        p_cr.add_run(desc)

    doc.add_heading("6. Cuadro de Honor y Ranking Final de las 16 Familias CMIP6", level=1)
    
    # Table of 16 families
    table_fam = doc.add_table(rows=1, cols=7)
    table_fam.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_fam.autofit = False

    fam_headers = ["Rank", "Familia GCM", "Mejor Variante", "Mean Rank (±SD)", "Top 10", "ΔT (°C) (ssp585)", "ΔP (%) (ssp585)"]
    fam_widths = [Inches(0.5), Inches(1.5), Inches(1.6), Inches(1.3), Inches(0.7), Inches(1.1), Inches(1.1)]

    hdr_row = table_fam.rows[0]
    for idx, text in enumerate(fam_headers):
        cell = hdr_row.cells[idx]
        cell.width = fam_widths[idx]
        set_cell_background(cell, "1B365D")
        set_cell_margins(cell, top=80, bottom=80, left=80, right=80)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.bold = True
        r.font.size = Pt(8.5)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)

    fam_data = [
        ("1", "NorESM2-MM", "r1i1p1f1", "1.00 (±0.00)", "9 / 9", "+3.54 °C", "-7.79 %", "E5F9E5"),
        ("2", "EC-Earth3-Veg", "r4i1p1f1", "2.22 (±0.44)", "9 / 9", "+4.07 °C", "-8.18 %", "E5F9E5"),
        ("3", "UKESM1-0-LL", "r1i1p1f2", "5.28 (±3.15)", "8 / 9", "+4.97 °C", "-6.16 %", "F0F8FF"),
        ("4", "MPI-ESM1-2-LR", "r5i1p1f1", "6.11 (±2.20)", "8 / 9", "+2.87 °C", "-12.04 %", "F0F8FF"),
        ("5", "EC-Earth3-Veg-LR", "r1i1p1f1", "9.89 (±5.21)", "5 / 9", "+3.73 °C", "-9.52 %", "F0F8FF"),
        ("6", "MPI-ESM1-2-HR", "r1i1p1f1", "10.50 (±7.45)", "5 / 9", "+2.77 °C", "-10.25 %", "FFFFFF"),
        ("7", "TaiESM1", "r1i1p1f1", "17.28 (±5.76)", "1 / 9", "+4.46 °C", "-7.99 %", "FFFFFF"),
        ("8", "MRI-ESM2-0", "r1i1p1f1", "18.00 (±1.80)", "0 / 9", "+3.42 °C", "-10.53 %", "FFFFFF"),
        ("9", "IPSL-CM6A-LR", "r2i1p1f1", "20.44 (±6.27)", "1 / 9", "+4.00 °C", "-23.96 %", "FFFFFF"),
        ("10", "INM-CM4-8", "r1i1p1f1", "26.33 (±2.92)", "0 / 9", "+2.68 °C", "+5.93 %", "FFFDF0"),
        ("11", "NorESM2-LM", "r1i1p1f1", "26.67 (±4.30)", "0 / 9", "+3.36 °C", "-0.7% ", "FFFDF0"),
        ("12", "KACE-1-0-G", "r1i1p1f1", "28.33 (±2.92)", "0 / 9", "+4.07 °C", "-6.86 %", "FFFDF0"),
        ("13", "INM-CM5-0", "r1i1p1f1", "28.67 (±1.73)", "0 / 9", "+2.52 °C", "-0.58 %", "FFFDF0"),
        ("14", "MIROC6", "r1i1p1f1", "31.56 (±2.96)", "0 / 9", "+3.25 °C", "+4.61 %", "FFF0F0"),
        ("15", "FGOALS-g3", "r1i1p1f1", "33.00 (±1.58)", "0 / 9", "+2.52 °C", "-10.46 %", "FFF0F0"),
        ("16", "CanESM5", "r1i1p1f1", "35.00 (±0.50)", "0 / 9", "+4.99 °C", "-23.63 %", "FFF0F0")
    ]

    for item in fam_data:
        row = table_fam.add_row()
        bg_col = item[7]
        for col_idx in range(7):
            cell = row.cells[col_idx]
            cell.width = fam_widths[col_idx]
            set_cell_background(cell, bg_col)
            set_cell_margins(cell, top=60, bottom=60, left=80, right=80)
            p = cell.paragraphs[0]
            val = item[col_idx]
            if col_idx in [0, 4, 5, 6]:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(val)
            if col_idx in [0, 1]:
                r.bold = True
            r.font.size = Pt(8.5)

    doc.add_paragraph()

    # 7. Espacio de Incertidumbre y Visualización Plotly
    doc.add_heading("7. Espacio de Incertidumbre y Gráfico de Dispersión Futuro", level=1)
    
    img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "results", "future_spread_ssp585_CAM.png"))
    if os.path.exists(img_path):
        p_img = doc.add_paragraph()
        p_img.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_img.paragraph_format.space_before = Pt(6)
        p_img.paragraph_format.space_after = Pt(4)
        run_img = p_img.add_run()
        run_img.add_picture(img_path, width=Inches(6.2))
        
        p_cap = doc.add_paragraph()
        p_cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_cap.paragraph_format.space_after = Pt(12)
        r_cap = p_cap.add_run("Figura 1: Gráfico de dispersión de cambio proyectado (ΔT en °C vs ΔP en %) bajo SSP5-8.5 (2071-2100 vs 1981-2010) en CAM:6. "
                              "Paleta continua oficial de GCMEval (verde=mejor rank, rosa=menor rank). "
                              "Versión interactiva HTML disponible en results/future_spread_ssp585_CAM.html.")
        r_cap.font.size = Pt(8.5)
        r_cap.italic = True
        r_cap.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # 8. Recomendaciones de Ensambles para Downscaling
    doc.add_heading("8. Recomendaciones para la Selección del Ensamble Objetivo", level=1)
    doc.add_paragraph(
        "No es obligatorio descargar rígidamente 10 modelos. La elección debe ajustarse a la capacidad de cómputo y "
        "al propósito específico del estudio de cambio climático:"
    )

    ens_configs = [
        ("Ensamble Central de Alto Rendimiento (Core 4-5)",
         "1. NorESM2-MM (r1i1p1f1)\n2. EC-Earth3-Veg (r4i1p1f1)\n3. UKESM1-0-LL (r1i1p1f2)\n4. MPI-ESM1-2-LR (r5i1p1f1)",
         "Máxima fidelidad climatológica. Captura un calentamiento entre +2.8°C y +4.9°C y un secamiento consistente de -6% a -12%."),
        
        ("Ensamble Diversificado Multimodelo (Recomendado: 8 Familias)",
         "Las 4 anteriores +\n5. TaiESM1 (r1i1p1f1)\n6. MRI-ESM2-0 (r1i1p1f1)\n7. MPI-ESM1-2-HR (r1i1p1f1)\n8. IPSL-CM6A-LR (r2i1p1f1)",
         "Excelente representatividad regional. Suma alta resolución (MPI-HR), modelos asiáticos estables (TaiESM1, MRI) y cubre el extremo seco (-24% de IPSL)."),
        
        ("Ensamble Ampliado (10 a 12 Familias)",
         "Las 8 anteriores +\n9. INM-CM4-8 (r1i1p1f1)\n10. KACE-1-0-G (r1i1p1f1)\n11. INM-CM5-0 (r1i1p1f1)",
         "Para análisis de máxima dispersión de incertidumbre incluyendo sensibilidades térmicas bajas (+2.5°C) y señal húmeda (INM-CM4-8).")
    ]

    for tit, mods, just in ens_configs:
        p_e = doc.add_paragraph()
        p_e.paragraph_format.left_indent = Inches(0.2)
        p_e.paragraph_format.space_after = Pt(4)
        r_t = p_e.add_run(f"• {tit}:\n")
        r_t.bold = True
        r_t.font.color.rgb = RGBColor(0x1B, 0x36, 0x5D)
        
        p_m = doc.add_paragraph()
        p_m.paragraph_format.left_indent = Inches(0.4)
        p_m.paragraph_format.space_after = Pt(2)
        r_m = p_m.add_run(f"Modelos:\n{mods}")
        r_m.font.size = Pt(9.5)
        
        p_j = doc.add_paragraph()
        p_j.paragraph_format.left_indent = Inches(0.4)
        p_j.paragraph_format.space_after = Pt(6)
        r_j = p_j.add_run(f"Justificación: {just}")
        r_j.font.size = Pt(9.5)
        r_j.italic = True

    # 9. Referencias Bibliográficas
    doc.add_heading("9. Referencias Bibliográficas", level=1)
    
    refs = [
        "Adler, R. F., Sapiano, M. R., Huffman, G. J., Wang, J. J., Gu, G., Bolvin, D., ... & Shin, D. B. (2018). The Global Precipitation Climatology Project (GPCP) monthly analysis (new version 2.3) and a review of 2017 global precipitation. Atmosphere, 9(4), 138.",
        "Almazroui, M., et al. (2021). Assessment of CMIP6 Performance and Projected Temperature and Precipitation Changes Over South America and Central America. Earth Systems and Environment, 5(2), 155-183.",
        "Amador, J. A. (1998). A climate feature of the tropical Americas: The trade wind easterly jet. Top. Meteor. Oceanogr, 5(2), 91-102.",
        "Amador, J. A. (2008). The Intra-Americas Sea low-level jet: overview and future research. Annals of the New York Academy of Sciences, 1146(1), 153-188.",
        "Brunner, L., Pendergrass, A. G., Lehner, F., Merrifield, A. L., Lorenz, R., & Knutti, R. (2020). Reduced global warming from CMIP6 projections when weighting models by performance and independence. Earth System Dynamics, 11(4), 995-1012.",
        "Cook, K. H., & Vizy, E. K. (2010). Hydrodynamics of the Caribbean low-level jet and its relationship to precipitation. Journal of Climate, 23(6), 1477-1494.",
        "Durán-Quesada, A. M., Gimeno, L., Amador, J. A., & Nieto, R. (2010). Moisture sources for Central America: Identification of sources using a Lagrangian approach. Journal of Geophysical Research: Atmospheres, 115(D5).",
        "Enfield, D. B., & Alfaro, E. J. (1999). The dependence of Caribbean rainfall on the interaction of tropical Atlantic and Pacific SSTs. Journal of Climate, 12(7), 2093-2103.",
        "Giorgi, F., Coppola, E., Raffaele, F., Diro, G. T., Fuentes-Franco, R., et al. (2014). Changes in extremes and circulation features in CORDEX regional climate simulations over Central America. Journal of Geophysical Research: Atmospheres, 119(11), 6627-6647.",
        "Gutiérrez, J. M., et al. (2021). IPCC AR6 WGI Chapter 10: Linking Global to Regional Climate Change. In Climate Change 2021: The Physical Science Basis. Cambridge University Press.",
        "Hersbach, H., Bell, B., Berrisford, P., Hirahara, S., Horányi, A., Muñoz-Sabater, J., ... & Thépaut, J. N. (2020). The ERA5 global reanalysis. Quarterly Journal of the Royal Meteorological Society, 146(730), 1999-2049.",
        "Hidalgo, H. G., Alfaro, E. J., & Quesada-Montano, B. (2017). Observed and projected changes in Central American drought. Climate Research, 73(1-2), 127-140.",
        "Magaña, V., Amador, J. A., & Medina, S. (1999). The midsummer drought over Mexico and Central America. Journal of Climate, 12(6), 1577-1588.",
        "Maldonado, T., Rutgersson, A., Alfaro, E., Amador, J., & Saha, S. (2016). Interannual variability of the Midsummer Drought in Central America and the connection with sea surface temperatures. Atmósfera, 29(1), 35-59.",
        "Muñoz, E., Busalacchi, A. J., Nigam, S., & Ruiz-Barradas, A. (2008). Winter and summer structure of the Caribbean low-level jet. Journal of Climate, 21(6), 1260-1276.",
        "Parding, K. M., Dobler, A., Haarstad, I. K., & Benestad, R. E. (2020). GCMEval – An interactive tool for evaluation and selection of climate model simulations. SoftwareX, 12, 100595.",
        "Taylor, M. A., et al. (2012). Why dry? Investigating the future evolution of American Tropics dry spells. Journal of Climate, 26(3), 784-801.",
        "Vichot-Llano, A., et al. (2021). Evaluation of CMIP6 models in reproducing the rainfall annual cycle over Central America and northern South America. Climate Dynamics, 57(9), 2419-2437."
    ]

    for ref in refs:
        p_r = doc.add_paragraph()
        p_r.paragraph_format.left_indent = Inches(0.3)
        p_r.paragraph_format.first_line_indent = Inches(-0.3)
        p_r.paragraph_format.space_after = Pt(4)
        r_ref = p_r.add_run(ref)
        r_ref.font.size = Pt(8.5)
        r_ref.font.color.rgb = RGBColor(0x33, 0x33, 0x33)

    doc.save(output_path)
    print(f"[OK] Documento Word exhaustivo generado en: {output_path}")

if __name__ == "__main__":
    out_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "Informe_Evaluacion_Seleccion_Modelos_CMIP6_Centroamerica.docx"))
    build_comprehensive_word_document(out_file)
