import streamlit as st
import time
import subprocess
import os
import glob
import shutil
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx", "xls", "csv"])
posities = st.file_uploader("Upload Posities en Kenmerken", type=["xlsx", "xls"])

REPO_ROOT = Path.cwd()
NOTEBOOK_SRC = REPO_ROOT / "notebooks" / "pipeline.ipynb"
NOTEBOOK_RUNTIME = REPO_ROOT / "notebooks" / "pipeline_runtime.ipynb"

def _save_upload(uploaded_file, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as f:
        f.write(uploaded_file.getbuffer())

def _ensure_template_zip() -> None:
    """
    Notebook verwacht: 'Template jpgs.zip' in de working directory.
    In de repo staan JPGs uitgepakt in assets/templates/.
    """
    zip_path = REPO_ROOT / "Template jpgs.zip"
    if zip_path.exists():
        return

    templates_dir = REPO_ROOT / "assets" / "templates"
    if not templates_dir.is_dir():
        # fallback: zoek map met "template" in naam
        for cand in (REPO_ROOT / "assets").glob("*"):
            if cand.is_dir() and "template" in cand.name.lower():
                templates_dir = cand
                break

    if not templates_dir.is_dir():
        raise FileNotFoundError("Kon templates-map niet vinden. Verwacht assets/templates/ met JPGs.")

    base = REPO_ROOT / "Template jpgs"
    tmp_zip = shutil.make_archive(str(base), "zip", str(templates_dir))
    os.replace(tmp_zip, str(zip_path))

def _patch_notebook(src_nb: Path, dst_nb: Path) -> None:
    """
    Minimal patch: voorkom Colab uploads; laat uploadcellen vaste paden 'zien'
    door google.colab.files.upload() te faken met een call-counter.
    """
    nb = nbformat.read(str(src_nb), as_version=4)

    injected = new_code_cell(
        """
# --- Injected by Streamlit/Render runtime ---
# Dit bestand bestaat altijd, want de UI schrijft het weg in de repo-root:
# - Kordiam_Report.xlsx
# - Posities en kenmerken.xlsx (en varianten)

# Fake Colab upload zodat de originele notebook-cellen kunnen blijven bestaan.
# We geven per upload-call een andere "geüploade" bestandsnaam terug.
try:
    import types, sys
    _upload_calls = {"n": 0}

    def _upload():
        _upload_calls["n"] += 1
        if _upload_calls["n"] == 1:
            return {"Kordiam_Report.xlsx": None}
        elif _upload_calls["n"] == 2:
            return {"Posities en kenmerken.xlsx": None}
        elif _upload_calls["n"] == 3:
            # output van DEF1 / input van DEF2 (zoals in jullie pipeline gebruikt)
            return {"Verhalenaanbod_Planningsoverzicht.xlsx": None}
        else:
            return {}

    colab = types.ModuleType("google.colab")
    files = types.ModuleType("google.colab.files")
    files.upload = _upload
    colab.files = files
    sys.modules["google.colab"] = colab
    sys.modules["google.colab.files"] = files
except Exception:
    pass
"""
    )

    nb.cells.insert(0, injected)
    nbformat.write(nb, str(dst_nb))

def _run_notebook_with_timer(nb_path: Path):
    cmd = [
        "python", "-m", "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        f"--ExecutePreprocessor.cwd={REPO_ROOT}",
        "--ExecutePreprocessor.timeout=1800",
        "--output", "pipeline_executed.ipynb",
        str(nb_path),
    ]

    start = time.time()
    timer = st.empty()

    p = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    while True:
        elapsed = int(time.time() - start)
        m, s = divmod(elapsed, 60)
        timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")
        if p.poll() is not None:
            break
        time.sleep(1)

    out = p.stdout.read() if p.stdout else ""
    return p.returncode, out

def _find_planning_xlsx() -> Path:
    # Zoek in repo-root en outputs/
    candidates = [Path(p) for p in (glob.glob(str(REPO_ROOT / "*.xlsx")) + glob.glob(str(REPO_ROOT / "outputs" / "*.xlsx")))]

    # filter assets/inputs uit
    blacklist = {
        "Templates.xlsx",
        "Mappingregels parser.xlsx",
        "Beslispad EP.xlsx",
        "Beslispad Spread.xlsx",
        "Hoe vaak komt wat voor.xlsx",
        "Kordiam_Report.xlsx",
        "Posities en kenmerken.xlsx",
        "Posities en Kenmerken.xlsx",
        "Posities_en_Kenmerken.xlsx",
        "Verhalenaanbod_Planningsoverzicht.xlsx",
    }
    candidates = [p for p in candidates if p.name not in blacklist]

    if not candidates:
        raise FileNotFoundError("Geen output Excel gevonden na uitvoering.")

    # voorkeur: krantenplanning in naam, anders nieuwste
    def score(p: Path):
        n = p.name.lower()
        s = 0
        if "kranten" in n: s += 2
        if "planning" in n: s += 2
        if "plan" in n: s += 1
        return (s, p.stat().st_mtime)

    candidates.sort(key=score, reverse=True)
    return candidates[0]

def _find_pdf() -> Path:
    p = REPO_ROOT / "handout_modern_v3.pdf"
    if p.exists():
        return p
    alts = list(REPO_ROOT.rglob("handout_modern_v3.pdf"))
    if alts:
        return alts[0]
    raise FileNotFoundError("PDF 'handout_modern_v3.pdf' niet gevonden na uitvoering.")

run_clicked = st.button("Genereer krantenplanning", disabled=not (kordiam and posities))

if run_clicked:
    try:
        if not NOTEBOOK_SRC.exists():
            raise FileNotFoundError("notebooks/pipeline.ipynb niet gevonden in de repo.")

        # 1) Uploads wegschrijven met vaste namen (zodat notebook ze altijd vindt)
        # Kordiam
        _save_upload(kordiam, REPO_ROOT / "Kordiam_Report.xlsx")
        # ook originele naam bewaren (handig voor debug)
        _save_upload(kordiam, REPO_ROOT / kordiam.name)

        # Posities: schrijf meerdere varianten weg om mismatch door spaties/case te voorkomen
        _save_upload(posities, REPO_ROOT / "Posities en kenmerken.xlsx")
        _save_upload(posities, REPO_ROOT / "Posities en Kenmerken.xlsx")
        _save_upload(posities, REPO_ROOT / "Posities_en_Kenmerken.xlsx")
        _save_upload(posities, REPO_ROOT / posities.name)

        # 2) Zorg dat Template jpgs.zip bestaat in repo-root
        _ensure_template_zip()

        # 3) Notebook patchen (minimaal) en uitvoeren in repo-root
        _patch_notebook(NOTEBOOK_SRC, NOTEBOOK_RUNTIME)
        ret, logs = _run_notebook_with_timer(NOTEBOOK_RUNTIME)

        if ret != 0:
            st.error("Pipeline crashte")
            st.code(logs[-8000:] if logs else "(geen output)", language="text")
        else:
            st.success("Krantenplanning gereed")

            planning_path = _find_planning_xlsx()
            pdf_path = _find_pdf()

            st.download_button(
                "Download planning in Excel",
                data=planning_path.read_bytes(),
                file_name=planning_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            st.download_button(
                "Download hand-out in PDF",
                data=pdf_path.read_bytes(),
                file_name=pdf_path.name,
                mime="application/pdf"
            )

    except Exception as e:
        st.error(f"Fout: {e}")
