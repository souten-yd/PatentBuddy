"""Run the existing server, requiring an explicit data location."""
import sys
from .cli import serve

sys.exit(serve(sys.argv[1:]))
