"""
Root entry point for Render / Streamlit Cloud.
Start command: streamlit run app.py
"""
import runpy
from pathlib import Path

# Run the real dashboard module
dashboard = Path(__file__).parent / "dashboard" / "app.py"
runpy.run_path(str(dashboard), run_name="__main__")
