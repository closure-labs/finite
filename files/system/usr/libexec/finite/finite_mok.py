"""Read the enrolled public Machine Owner Key certificates."""
from pathlib import Path
import subprocess
import tempfile


def enrolled_mok_certificates(run=subprocess.run):
    """Return exact DER bytes from shim's enrolled certificate database."""
    with tempfile.TemporaryDirectory(prefix='finite-mok-') as temporary:
        run(['mokutil', '--export'], cwd=temporary, check=True, timeout=30)
        return {path.read_bytes() for path in Path(temporary).glob('MOK-*.der')}
