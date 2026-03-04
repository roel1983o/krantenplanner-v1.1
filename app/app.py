import streamlit as st
import time
import subprocess
import os
import glob
import nbformat
from nbformat.v4 import new_code_cell
from pathlib import Path

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

# -----------------------------
# Uploads
# -----------------------------

kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx","xls","csv"])
posities = st.file_uploader("Upload Posities en Kenmerken", type=["xlsx","xls"])

# -----------------------------
# Helpers
# -----------------------------

def save_upload(upload, filename):
    with open(filename, "wb") as f:
        f.write(upload.getbuffer())

def patch_notebook(src, dst):
    nb = nbformat.read(src, as_version=4)

    injected = new_code_cell(
"""
# --- Injected runtime config ---
INPUT_XLSX = "Kordiam_Report.xlsx"
VERHALENAANBOD_PATH = "Verhalenaanbod_Planningsoverzicht.xlsx"
POSITIES_XLSX = "Posities_en_Kenmerken.xlsx"

# Fake Colab upload zodat notebook niet crasht
try:
    import types, sys
    colab = types.ModuleType("google.colab")
    files = types.ModuleType("google.colab.files")

    def upload():
        return {}

    files.upload = upload
    colab.files = files

    sys.modules["google.colab"] = colab
    sys.modules["google.colab.files"] = files
except:
    pass
"""
    )

    nb.cells.insert(0, injected)
    nbformat.write(nb, dst)

def run_notebook(nb_path):

    cmd = [
        "python",
        "-m",
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        "--ExecutePreprocessor.timeout=1800",
        "--output",
        "pipeline_executed.ipynb",
        nb_path
    ]

    start = time.time()
    timer = st.empty()

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    while True:

        elapsed = int(time.time() - start)
        m = elapsed // 60
        s = elapsed % 60

        timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")

        if process.poll() is not None:
            break

        time.sleep(1)

    output = process.stdout.read()

    return process.returncode, output

def find_excel():

    files = glob.glob("*.xlsx") + glob.glob("outputs/*.xlsx")

    blacklist = [
        "Templates.xlsx",
        "Mappingregels parser.xlsx",
        "Beslispad EP.xlsx",
        "Beslispad Spread.xlsx",
        "Hoe vaak komt wat voor.xlsx",
        "Posities en kenmerken.xlsx",
        "Posities_en_Kenmerken.xlsx",
    ]

    files = [f for f in files if os.path.basename(f) not in blacklist]

    if not files:
        raise FileNotFoundError("Geen output Excel gevonden")

    files.sort(key=os.path.getmtime, reverse=True)

    return files[0]

def find_pdf():

    if os.path.exists("handout_modern_v3.pdf"):
        return "handout_modern_v3.pdf"

    alt = glob.glob("**/handout_modern_v3.pdf", recursive=True)

    if alt:
        return alt[0]

    raise FileNotFoundError("PDF niet gevonden")

# -----------------------------
# Run knop
# -----------------------------

run = False
if kordiam and posities:
    run = st.button("Genereer krantenplanning")

# -----------------------------
# Pipeline uitvoeren
# -----------------------------

if run:

    try:

        # uploads opslaan
        save_upload(kordiam, "Kordiam_Report.xlsx")
        save_upload(posities, "Posities_en_Kenmerken.xlsx")

        # notebook patchen
        patch_notebook(
            "notebooks/pipeline.ipynb",
            "notebooks/pipeline_runtime.ipynb"
        )

        # uitvoeren
        ret, logs = run_notebook("notebooks/pipeline_runtime.ipynb")

        if ret != 0:
            st.error("Pipeline crashte")
            st.code(logs[-4000:])
        else:

            st.success("Krantenplanning gereed")

            excel = find_excel()
            pdf = find_pdf()

            with open(excel, "rb") as f:
                st.download_button(
                    "Download planning in Excel",
                    f,
                    file_name=os.path.basename(excel),
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

            with open(pdf, "rb") as f:
                st.download_button(
                    "Download hand-out in PDF",
                    f,
                    file_name=os.path.basename(pdf),
                    mime="application/pdf"
                )

    except Exception as e:

        st.error(f"Fout: {e}")
