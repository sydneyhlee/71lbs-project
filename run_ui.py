"""Launch the Streamlit review UI."""

import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([
        sys.executable, "-m", "streamlit", "run",
        "app/review/ui.py",
        "--server.port", "8501",
    ])
