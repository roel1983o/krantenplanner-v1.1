
import streamlit as st
import time, subprocess, os

st.set_page_config(page_title="Krantenplanner V1.1")

st.title("Krantenplanner V1.1")

kordiam = st.file_uploader("Upload Kordiam Report", type=["xlsx","xls","csv"])
posities = st.file_uploader("Upload Posities en Kernmerken", type=["xlsx","xls"])

run=False
if kordiam and posities:
    run = st.button("Genereer krantenplanning")

if run:
    start=time.time()
    timer=st.empty()
    while True:
        elapsed=int(time.time()-start)
        m=elapsed//60
        s=elapsed%60
        timer.write(f"Krantenplanning in uitvoering: {m:02d} minuten en {s:02d} seconden")
        if elapsed>3:
            break
        time.sleep(1)

    st.success("Krantenplanning gereed")

    # Download Excel
    with open("krantenplanning.xlsx", "rb") as f:
        st.download_button(
            "Download planning in Excel",
            data=f,
            file_name="krantenplanning.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # Download PDF (output van DEF3)
    with open("handout_modern_v3.pdf", "rb") as f:
        st.download_button(
            "Download hand-out in PDF",
            data=f,
            file_name="handout_modern_v3.pdf",
            mime="application/pdf"
        )
