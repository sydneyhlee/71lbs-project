"""Launch the Streamlit review UI."""

import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        str(project_root / "app" / "review" / "ui.py"),
        "--server.port", "8501",
    ], cwd=str(project_root))
