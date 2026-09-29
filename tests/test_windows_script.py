"""Lance le test PowerShell de la version Windows si pwsh est disponible."""

import shutil
import subprocess
from pathlib import Path

import pytest

PWSH = shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) non installé")
def test_windows_script():
    script = Path(__file__).with_name("test_windows_script.ps1")
    run = subprocess.run([PWSH, "-NoProfile", "-File", str(script)], capture_output=True,
                         text=True, timeout=300)
    assert run.returncode == 0, run.stdout + run.stderr
