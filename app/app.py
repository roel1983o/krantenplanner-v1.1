
import streamlit as st
import time, subprocess, os, json, shutil, zipfile, tempfile
from pathlib import Path

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx","xls","csv"])
posities = st.file_uploader("Upload Posities en Kernmerken", type=["xlsx","xls"])

# Paths inside repo (Render runs from repo root)
REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = REPO_ROOT / "assets"
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "pipeline.ipynb"

run = False
if kordiam and posities:
    run = st.button("Genereer krantenplanning")

def _write_uploaded(uploaded_file, dest_path: Path):
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return dest_path

def _make_templates_zip(src_templates_dir: Path, dest_zip: Path):
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in src_templates_dir.rglob("*.jpg"):
            # store with just filename (not full path) to match notebook expectations (CODE.jpg)
            z.write(p, arcname=p.name)
    return dest_zip

def _ensure_fake_google_colab_files(workdir: Path):
    """
    Notebook gebruikt: from google.colab import files; uploaded = files.upload()
    We maken een lokale stub-module google/colab/files.py zodat dit ook buiten Colab werkt.
    De stub leest UPLOAD_SEQUENCE (JSON list) uit env en geeft per upload() call steeds het volgende pad terug.
    """
    pkg_dir = workdir / "google" / "colab"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (workdir / "google" / "__init__.py").write_text("")
    (workdir / "google" / "colab" / "__init__.py").write_text("")
    (workdir / "google" / "colab" / "files.py").write_text(
        "import os, json\n"
        "_seq = None\n"
        "def upload():\n"
        "    global _seq\n"
        "    if _seq is None:\n"
        "        _seq = json.loads(os.environ.get('UPLOAD_SEQUENCE','[]'))\n"
        "    if not _seq:\n"
        "        raise RuntimeError('UPLOAD_SEQUENCE is leeg; geen bestand om te leveren aan files.upload()')\n"
        "    path = _seq.pop(0)\n"
        "    # Colab returns dict of {filename: bytes}; notebook pakt next(iter(keys()))\n"
        "    return {path: b''}\n"
    )

if run:
    # Workdir per run
    workdir = Path(tempfile.mkdtemp(prefix="krantenplanner_run_"))
    # Zorg dat notebook relative paths naar assets werken
    # We kopiëren assets naar workdir/assets (zodat paths identiek zijn)
    shutil.copytree(ASSETS_DIR, workdir / "assets")

    # Dagelijkse uploads wegschrijven in workdir (we gebruiken vaste namen zodat notebook ze eenduidig kan vinden)
    kordiam_path = _write_uploaded(kordiam, workdir / "Kordiam_Report.xlsx")
    posities_path = _write_uploaded(posities, workdir / "Posities_en_kenmerken.xlsx")

    # Maak Template jpgs.zip vanuit uitgepakte templates
    templates_dir = workdir / "assets" / "templates"
    template_zip_path = _make_templates_zip(templates_dir, workdir / "Template jpgs.zip")

    # Upload-volgorde exact zoals notebook de upload-cellen aanroept
    upload_sequence = [
        "assets/Templates.xlsx",
        "assets/Beslispad Spread.xlsx",
        "assets/Beslispad EP.xlsx",
        "assets/Hoe vaak komt wat voor.xlsx",
        "assets/Mappingregels parser.xlsx",
        str(kordiam_path.name),                 # Kordiam report (in workdir root)
        str(posities_path.name),                # Posities en kenmerken (in workdir root)
        "assets/Hoe vaak komt wat voor.xlsx",   # DEF3 mapping upload
        str(template_zip_path.name),            # DEF3 template zip upload
    ]

    # Stub google.colab.files.upload
    _ensure_fake_google_colab_files(workdir)

    # Execute notebook
    start = time.time()
    timer = st.empty()
    status = st.empty()

    env = os.environ.copy()
    env["UPLOAD_SEQUENCE"] = json.dumps(upload_sequence)
    # Zorg dat onze stub-module wordt gevonden vóór echte packages
    env["PYTHONPATH"] = str(workdir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    cmd = [
        "python", "-m", "nbconvert",
        "--to", "notebook",
        "--execute", str(NOTEBOOK_PATH),
        "--output", "executed_pipeline.ipynb",
        "--ExecutePreprocessor.timeout=1800",
        "--ExecutePreprocessor.kernel_name=python3",
    ]

    status.info("Krantenplanning wordt uitgevoerd…")

    proc = subprocess.Popen(cmd, cwd=str(workdir), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    # live timer while process runs
    log_lines = []
    while True:
        elapsed = int(time.time() - start)
        m = elapsed // 60
        s = elapsed % 60
        timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")

        line = proc.stdout.readline() if proc.stdout else ""
        if line:
            log_lines.append(line.rstrip())
        if proc.poll() is not None:
            break
        time.sleep(1)

    rc = proc.returncode
    if rc != 0:
        status.error("Er ging iets mis bij het uitvoeren van de pipeline.")
        # toon laatste logs om te debuggen
        if log_lines:
            st.code("\n".join(log_lines[-50:]))
        st.stop()

    status.success("Krantenplanning gereed")

    # Outputs (volgens notebook)
    excel_out = workdir / "Krantenplanning.xlsx"
    pdf_out = workdir / "handout_modern_v3.pdf"

    # Downloads alleen tonen als bestanden bestaan
    if not excel_out.exists():
        st.error("Krantenplanning.xlsx is niet gevonden na uitvoering.")
    else:
        with open(excel_out, "rb") as f:
            st.download_button(
                "Download planning in Excel",
                data=f,
                file_name="Krantenplanning.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    if not pdf_out.exists():
        st.error("handout_modern_v3.pdf is niet gevonden na uitvoering.")
    else:
        with open(pdf_out, "rb") as f:
            st.download_button(
                "Download hand-out in PDF",
                data=f,
                file_name="handout_modern_v3.pdf",
                mime="application/pdf",
            )
