import streamlit as st
import time
import subprocess
import os
import glob
import shutil
import uuid
from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell

st.set_page_config(page_title="Krantenplanner V1.1")
st.title("Krantenplanner V1.1")

kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx", "xls", "csv"])
posities = st.file_uploader("Upload Posities en Kenmerken", type=["xlsx", "xls"])

def _save_upload(uploaded_file, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

def _make_template_zip(assets_dir: Path, run_dir: Path) -> None:
    """
    Notebook verwacht een bestand met exact deze naam.
    """
    zip_name = run_dir / "Template jpgs.zip"
    if zip_name.exists():
        return

    # Meest waarschijnlijke locatie in jouw repo:
    templates_dir = assets_dir / "templates"
    if not templates_dir.is_dir():
        # fallback: andere mapnaam
        for cand in assets_dir.glob("*"):
            if cand.is_dir() and "template" in cand.name.lower():
                templates_dir = cand
                break

    if not templates_dir.is_dir():
        raise FileNotFoundError("Kon templates-map met JPGs niet vinden in assets/ (verwacht assets/templates/).")

    # Maak zip (zonder extra topfolder) door in templates_dir te zippen
    base = run_dir / "Template jpgs"
    tmp_zip = shutil.make_archive(str(base), "zip", str(templates_dir))
    os.replace(tmp_zip, str(zip_name))

def _patch_notebook(src_nb: Path, dst_nb: Path) -> None:
    nb = nbformat.read(str(src_nb), as_version=4)

    injected = new_code_cell(
        """
# --- Injected by Streamlit/Render runtime ---
# Forceer inputpaden (deze bestanden worden door de UI weggeschreven in de run-directory)
INPUT_XLSX = "Kordiam_Report.xlsx"
POSITIES_XLSX = "Posities_en_Kenmerken.xlsx"

# Sommige cellen gebruiken google.colab.files.upload(); maak dat onschadelijk
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
except Exception:
    pass
"""
    )

    nb.cells.insert(0, injected)
    nbformat.write(nb, str(dst_nb))

def _run_notebook(nb_path: Path, run_dir: Path):
    cmd = [
        "python", "-m", "jupyter", "nbconvert",
        "--to", "notebook",
        "--execute",
        f"--ExecutePreprocessor.cwd={run_dir}",
        "--ExecutePreprocessor.timeout=1800",
        "--output", "pipeline_executed.ipynb",
        str(nb_path),
    ]

    start = time.time()
    timer = st.empty()

    p = subprocess.Popen(
        cmd,
        cwd=str(run_dir),
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

def _find_planning_xlsx(run_dir: Path) -> Path:
    # Zoek in run_dir en eventueel subfolders
    candidates = list(run_dir.glob("*.xlsx")) + list(run_dir.glob("outputs/*.xlsx"))

    # filter assets/inputs uit
    blacklist = {
        "Templates.xlsx",
        "Mappingregels parser.xlsx",
        "Beslispad EP.xlsx",
        "Beslispad Spread.xlsx",
        "Hoe vaak komt wat voor.xlsx",
        "Posities en kenmerken.xlsx",
        "Posities_en_Kenmerken.xlsx",
        "Kordiam_Report.xlsx",
    }
    candidates = [p for p in candidates if p.name not in blacklist]

    if not candidates:
        raise FileNotFoundError("Geen output Excel gevonden na uitvoering.")

    # voorkeur: krantenplanning in naam, anders nieuwste
    def score(p: Path) -> tuple:
        n = p.name.lower()
        s = 0
        if "kranten" in n: s += 2
        if "planning" in n: s += 2
        if "plan" in n: s += 1
        return (s, p.stat().st_mtime)

    candidates.sort(key=score, reverse=True)
    return candidates[0]

def _find_pdf(run_dir: Path) -> Path:
    p = run_dir / "handout_modern_v3.pdf"
    if p.exists():
        return p
    # fallback recursive
    alts = list(run_dir.rglob("handout_modern_v3.pdf"))
    if alts:
        return alts[0]
    raise FileNotFoundError("PDF 'handout_modern_v3.pdf' niet gevonden na uitvoering.")

# Run knop alleen actief na beide uploads
run_clicked = st.button("Genereer krantenplanning", disabled=not (kordiam and posities))

if run_clicked:
    try:
        # Werk altijd in een writeable run-dir (Render: /tmp is veilig)
        base_runs = Path("/tmp/krantenplanner_runs")
        base_runs.mkdir(parents=True, exist_ok=True)
        run_id = uuid.uuid4().hex
        run_dir = base_runs / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        repo_root = Path.cwd()
        assets_dir = repo_root / "assets"
        notebooks_dir = repo_root / "notebooks"

        # 1) Uploads wegschrijven met vaste namen (zodat notebook ze altijd vindt)
        _save_upload(kordiam, run_dir / "Kordiam_Report.xlsx")
        _save_upload(posities, run_dir / "Posities_en_Kenmerken.xlsx")

        # 2) Assets beschikbaar maken in run_dir (kopie)
        if assets_dir.is_dir():
            shutil.copytree(assets_dir, run_dir / "assets", dirs_exist_ok=True)
            # Veel notebooks verwachten assets in cwd; copy ook de losse files naar root van run_dir
            for f in assets_dir.glob("*.xlsx"):
                shutil.copy2(f, run_dir / f.name)
        else:
            raise FileNotFoundError("assets/ map ontbreekt in de repo.")

        # 3) Template zip maken in run_dir (exacte naam)
        _make_template_zip(run_dir / "assets", run_dir)

        # 4) Notebook patchen naar run_dir en uitvoeren
        src_nb = notebooks_dir / "pipeline.ipynb"
        if not src_nb.exists():
            raise FileNotFoundError("notebooks/pipeline.ipynb niet gevonden in de repo.")

        runtime_nb = run_dir / "pipeline_runtime.ipynb"
        _patch_notebook(src_nb, runtime_nb)

        ret, logs = _run_notebook(runtime_nb, run_dir)

        if ret != 0:
            st.error("Pipeline crashte")
            st.code(logs[-8000:] if logs else "(geen output)", language="text")
        else:
            st.success("Krantenplanning gereed")

            planning_path = _find_planning_xlsx(run_dir)
            pdf_path = _find_pdf(run_dir)

            # Lees bytes in (zodat downloads ook werken als run_dir later wordt opgeschoond)
            planning_bytes = planning_path.read_bytes()
            pdf_bytes = pdf_path.read_bytes()

            st.download_button(
                "Download planning in Excel",
                data=planning_bytes,
                file_name=planning_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )

            st.download_button(
                "Download hand-out in PDF",
                data=pdf_bytes,
                file_name=pdf_path.name,
                mime="application/pdf"
            )

    except Exception as e:
        st.error(f"Fout: {e}")
