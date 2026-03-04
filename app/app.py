
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

    st.download_button("Download planning in Excel","placeholder","krantenplanning.xlsx")
    st.download_button("Download hand-out in PDF","placeholder","handout.pdf")
