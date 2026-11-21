"""Entry point for running studio as a module: python -m studio"""
import sys, os

# When packaged with PyInstaller (console=False / GUI mode), sys.stdout and sys.stderr are None.
# uvicorn's logging formatter calls sys.stdout.isatty() which throws AttributeError: 'NoneType' object has no attribute 'isatty'.
class _NullWriter:
    def write(self, s): pass
    def flush(self): pass
    def isatty(self): return False

if sys.stdout is None:
    sys.stdout = _NullWriter()
if sys.stderr is None:
    sys.stderr = _NullWriter()

from studio.server import main
main()
