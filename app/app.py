import time
import threading
import tempfile
import shutil
import zipfile
from pathlib import Path

import streamlit as st
import nbformat
from nbclient import NotebookClient

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

# Dagelijks wisselend
kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx", "xls", "csv"])
posities = st.file_uploader("Upload Posities en Kernmerken", type=["xlsx", "xls"])

# Notebook-bestand in repo
NB_PATH = Path("notebooks/pipeline.ipynb")

# Assets in repo
ASSETS_DIR = Path("assets")

# Deze indices zijn de upload/download/install cellen in het notebook (originele indices)
SKIP_CELL_INDICES_ORIGINAL = {
    2,          # DEF1 ipywidgets upload UI
    8, 9, 10, 11,  # DEF2 colab uploads
    13,         # pip install
    15,         # colab download xlsx
    18,         # apt-get/pip install
    19,         # DEF3 colab uploads
    24,         # colab download pdf
}

def prepare_template_zip_if_needed(workdir: Path):
    """
    Notebook verwacht 'Template jpgs.zip' in de workdir.
    Als je de jpgs uitgepakt in assets/templates/ hebt staan, maken we die zip on-the-fly.
    """
    zip_target = workdir / "Template jpgs.zip"

    # Als de zip al in assets staat, kopieer die
    if (ASSETS_DIR / "Template jpgs.zip").exists():
        shutil.copy2(ASSETS_DIR / "Template jpgs.zip", zip_target)
        return

    # Anders: maak zip vanuit assets/templates/*.jpg
    templates_dir = ASSETS_DIR / "templates"
    if templates_dir.exists():
        jpgs = list(templates_dir.rglob("*.jpg"))
        if not jpgs:
            raise RuntimeError("assets/templates bestaat maar bevat geen .jpg bestanden.")
        with zipfile.ZipFile(zip_target, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in jpgs:
                # zet ze in de zip met een relatief pad onder 'templates/'
                arcname = str(p.relative_to(ASSETS_DIR))
                z.write(p, arcname=arcname)
        return

    raise RuntimeError("Geen Template jpgs.zip in assets en ook geen assets/templates map gevonden.")

def run_notebook_pipeline(kordiam_bytes: bytes, posities_bytes: bytes) -> tuple[bytes, bytes]:
    """
    Run notebooks/pipeline.ipynb headless in een temp workdir.
    Return: (xlsx_bytes, pdf_bytes)
    """
    workdir = Path(tempfile.mkdtemp(prefix="krantenplanner_run_"))
    try:
        # Maak workdir/assets zoals notebook verwacht
        (workdir / "assets").mkdir(parents=True, exist_ok=True)

        # Zet vaste assets neer
        fixed_to_assets = [
            "Mappingregels parser.xlsx",
            "Templates.xlsx",
            "Beslispad Spread.xlsx",
            "Beslispad EP.xlsx",
        ]
        for name in fixed_to_assets:
            src = ASSETS_DIR / name
            if not src.exists():
                raise FileNotFoundError(f"Asset ontbreekt: assets/{name}")
            shutil.copy2(src, workdir / "assets" / name)

        # DEF3 verwacht deze in de root van workdir
        hw = ASSETS_DIR / "Hoe vaak komt wat voor.xlsx"
        if not hw.exists():
            raise FileNotFoundError("Asset ontbreekt: assets/Hoe vaak komt wat voor.xlsx")
        shutil.copy2(hw, workdir / "Hoe vaak komt wat voor.xlsx")

        # Templates zip (uitgepakt in repo is ok; we maken zip indien nodig)
        prepare_template_zip_if_needed(workdir)

        # Dagelijkse uploads opslaan
        kordiam_path = workdir / "Kordiam Report.xlsx"
        posities_path = workdir / "Posities en kenmerken.xlsx"
        kordiam_path.write_bytes(kordiam_bytes)
        posities_path.write_bytes(posities_bytes)

        # Notebook laden
        nb = nbformat.read(str(NB_PATH), as_version=4)

        # Upload/download/install cellen verwijderen
        nb.cells = [c for i, c in enumerate(nb.cells) if i not in SKIP_CELL_INDICES_ORIGINAL]

        # Inject cell met paden (geen notebook-logica veranderen)
        injected = f"""
from pathlib import Path

INPUT_XLSX = r\"{kordiam_path.as_posix()}\"
OUTPUT_XLSX = r\"{(workdir / "Verhalenaanbod.xlsx").as_posix()}\"
MAPPING_XLSX = r\"{(workdir / "assets" / "Mappingregels parser.xlsx").as_posix()}\"

TEMPLATES_PATH = r\"{(workdir / "assets" / "Templates.xlsx").as_posix()}\"
BESLISPAD_SPREAD_PATH = r\"{(workdir / "assets" / "Beslispad Spread.xlsx").as_posix()}\"
BESLISPAD_EP_PATH = r\"{(workdir / "assets" / "Beslispad EP.xlsx").as_posix()}\"
POSITIES_PATH = r\"{posities_path.as_posix()}\"

KRANTENPLANNING_XLSX = r\"{(workdir / "Krantenplanning.xlsx").as_posix()}\"
"""
        nb.cells.insert(0, nbformat.v4.new_code_cell(injected))

        # Uitvoeren
        client = NotebookClient(
            nb,
            timeout=None,
            kernel_name="python3",
            resources={"metadata": {"path": str(workdir)}},
        )
        client.execute()

        # Outputs lezen
        xlsx_out = workdir / "Krantenplanning.xlsx"
        pdf_out = workdir / "handout_modern_v3.pdf"

        if not xlsx_out.exists():
            raise FileNotFoundError("Krantenplanning.xlsx is niet aangemaakt.")
        if not pdf_out.exists():
            raise FileNotFoundError("handout_modern_v3.pdf is niet aangemaakt.")

        xlsx_bytes = xlsx_out.read_bytes()
        pdf_bytes = pdf_out.read_bytes()

        # PDF sanity check: echte PDF begint met %PDF
        if not pdf_bytes.startswith(b"%PDF"):
            raise RuntimeError(f"PDF lijkt ongeldig (eerste bytes: {pdf_bytes[:20]!r})")

        return xlsx_bytes, pdf_bytes

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

# UI state
if "running" not in st.session_state:
    st.session_state.running = False
if "xlsx_bytes" not in st.session_state:
    st.session_state.xlsx_bytes = None
if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None
if "error" not in st.session_state:
    st.session_state.error = None
if "start_time" not in st.session_state:
    st.session_state.start_time = None

def start_run():
    st.session_state.running = True
    st.session_state.xlsx_bytes = None
    st.session_state.pdf_bytes = None
    st.session_state.error = None
    st.session_state.start_time = time.time()

    def _job():
        try:
            xb, pb = run_notebook_pipeline(kordiam.getvalue(), posities.getvalue())
            st.session_state.xlsx_bytes = xb
            st.session_state.pdf_bytes = pb
        except Exception as e:
            st.session_state.error = str(e)
        finally:
            st.session_state.running = False

    threading.Thread(target=_job, daemon=True).start()

run = False
if kordiam and posities and not st.session_state.running:
    run = st.button("Genereer krantenplanning", on_click=start_run)

timer = st.empty()

if st.session_state.running:
    elapsed = int(time.time() - st.session_state.start_time)
    m = elapsed // 60
    s = elapsed % 60
    timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")
    time.sleep(1)
    st.rerun()

if st.session_state.error:
    st.error(st.session_state.error)

if (st.session_state.xlsx_bytes is not None) and (st.session_state.pdf_bytes is not None):
    st.success("Krantenplanning gereed")

    st.download_button(
        "Download planning in Excel",
        data=st.session_state.xlsx_bytes,
        file_name="Krantenplanning.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.download_button(
        "Download hand-out in PDF",
        data=st.session_state.pdf_bytes,
        file_name="handout_modern_v3.pdf",
        mime="application/pdf",
    )
