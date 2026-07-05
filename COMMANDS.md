# Commands

## Setup

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
# Streamlit web UI (primary)
.\venv\Scripts\python.exe -m streamlit run app.py

# CLI
.\venv\Scripts\python.exe run.py --keyword "Python Developer" --location "Remote" --cv my_cv.pdf

# One-shot Windows setup + launch
install_and_run.bat
```

run directly by 
.\venv\Scripts\python.exe -m streamlit run app.py