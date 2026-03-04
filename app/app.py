
import streamlit as st
import time, subprocess, os, glob, shutil
from pathlib import Path
import nbformat
from nbformat.v4 import new_code_cell

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

# Uploads (dagelijks wisselend)
kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx", "xls", "csv"])
posities = st.file_uploader("Upload Posities en Kenmerken", type=["xlsx", "xls"])

def _write_upload(uploaded_file, target_path: str) -> None:
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

def _ensure_template_zip() -> None:
    """
    Notebook verwacht 'Template jpgs.zip' als asset.
    In de repo staan de JPGs uitgepakt; we maken hier runtime een zip met dezelfde naam.
    """
    zip_name = "Template jpgs.zip"
    if os.path.exists(zip_name):
        return

    candidates = [
        "assets/templates",
        "assets/Template jpgs",
        "assets/template_jpgs",
    ]
    templates_dir = None
    for c in candidates:
        if os.path.isdir(c):
            templates_dir = c
            break

    if templates_dir is None:
        # Als jouw repo een andere mapnaam gebruikt, dan zie je dit direct in UI
        raise FileNotFoundError("Kon templates-map met JPGs niet vinden in assets/ (verwacht assets/templates/).")

    # Maak zip in current working dir met exact de verwachte naam
    base_name = "Template jpgs"
    # shutil.make_archive maakt base_name + .zip, dus eerst maken en dan hernoemen
    tmp_zip = shutil.make_archive(base_name, "zip", templates_dir)
    os.replace(tmp_zip, zip_name)

def _find_planning_xlsx() -> str:
    """
    We weten zeker: PDF heet 'handout_modern_v3.pdf' (uit notebook).
    Excel-naam kan variëren (case/underscore). We zoeken de juiste foutloos.
    """
    # 1) voorkeursnamen (meest waarschijnlijk)
    preferred = [
        "Krantenplanning.xlsx",
        "krantenplanning.xlsx",
        "Krantenplannen.xlsx",
        "krantenplannen.xlsx",
    ]
    for p in preferred:
        if os.path.exists(p):
            return p

    # 2) alles in root + outputs/ doorzoeken
    candidates = glob.glob("*.xlsx") + glob.glob("outputs/*.xlsx")

    # filter bekende input/assets uit (zodat we niet per ongeluk Templates.xlsx teruggeven)
    blacklist = {
        "Templates.xlsx",
        "Beslispad EP.xlsx",
        "Beslispad Spread.xlsx",
        "Hoe vaak komt wat voor.xlsx",
        "Mappingregels parser.xlsx",
        "Posities en kenmerken.xlsx",
        "Posities en Kernmerken.xlsx",
    }
    cleaned = []
    for c in candidates:
        name = os.path.basename(c)
        if name in blacklist:
            continue
        cleaned.append(c)

    if not cleaned:
        raise FileNotFoundError("Geen output .xlsx gevonden na uitvoering. Pipeline lijkt geen Excel te hebben weggeschreven.")

    # 3) kies de meest waarschijnlijk: bevat 'kranten' en 'plan' in de naam
    def score(path: str) -> int:
        n = os.path.basename(path).lower()
        s = 0
        if "kranten" in n: s += 2
        if "plan" in n: s += 2
        if "planning" in n: s += 2
        return s

    cleaned.sort(key=lambda p: (score(p), os.path.getmtime(p)), reverse=True)
    return cleaned[0]

def _run_notebook_with_timer(nb_path: str):
    """
    Draait notebook via nbconvert en toont live timer zolang het proces loopt.
    """
    # NB: nbconvert moet in requirements staan (zie stap 2 hieronder)
    cmd = [
        "python", "-m", "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=1800",
        "--output", "pipeline_executed.ipynb",
        nb_path,
    ]

    status = st.empty()
    timer = st.empty()

    start = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # live timer + (compact) status
    while True:
        elapsed = int(time.time() - start)
        m, s = divmod(elapsed, 60)
        timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")

        ret = p.poll()
        if ret is not None:
            # Process klaar; lees output
            out = p.stdout.read() if p.stdout else ""
            return ret, out

        time.sleep(1)

# Knop pas actief als beide uploads aanwezig zijn
can_run = kordiam is not None and posities is not None
run = st.button("Genereer krantenplanning", disabled=not can_run)

if run:
    try:
        # Schrijf uploads naar bestandsnamen die notebook verwacht/kan vinden
        # (we bewaren ook de originele naam voor traceerbaarheid)
        _write_upload(kordiam, f"INPUT_KORDIAM_{kordiam.name}")
        _write_upload(posities, f"INPUT_POSITIES_{posities.name}")

        # Vaak verwachten notebooks een vaste bestandsnaam; zet ook die neer:
        _write_upload(kordiam, "Kordiam_Report.xlsx")
        _write_upload(posities, "Posities_en_Kenmerken.xlsx")

        # Zorg dat de template zip bestaat (notebook-assetnaam)
        _ensure_template_zip()

        # Voer notebook uit
        ret, out = _run_notebook_with_timer("notebooks/pipeline.ipynb")

        if ret != 0:
            st.error("Pipeline is gestopt met een fout. Hieronder de output:")
            st.code(out[-4000:] if out else "(geen output)", language="text")
        else:
            st.success("Krantenplanning gereed")

            # Excel output vinden (foutloos)
            planning_path = _find_planning_xlsx()

            # PDF output is zeker (uit jouw notebook)
            pdf_path = "handout_modern_v3.pdf"
            if not os.path.exists(pdf_path):
                # soms schrijft notebook in outputs/ of andere plek; probeer ook daar
                alt = glob.glob("**/handout_modern_v3.pdf", recursive=True)
                if alt:
                    pdf_path = alt[0]
                else:
                    raise FileNotFoundError("PDF 'handout_modern_v3.pdf' niet gevonden na uitvoering.")

            with open(planning_path, "rb") as f:
                st.download_button(
                    "Download planning in Excel",
                    data=f,
                    file_name=os.path.basename(planning_path),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

            with open(pdf_path, "rb") as f:
                st.download_button(
                    "Download hand-out in PDF",
                    data=f,
                    file_name=os.path.basename(pdf_path),
                    mime="application/pdf",
                )

    except Exception as e:
        st.error(f"Fout: {e}")
