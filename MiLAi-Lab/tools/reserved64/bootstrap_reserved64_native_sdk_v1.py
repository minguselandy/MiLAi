"""Use the established CUDA SDK first, then append existing HTTP/graph dependencies."""
import runpy
import sys
from pathlib import Path

import transformers
import tokenizers

assert transformers.__version__ == "4.52.3"
assert tokenizers.__version__ == "0.21.4"
site, entry = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.append(str(site))
sys.path.insert(0, str(entry.parent))
sys.argv = [str(entry), *sys.argv[3:]]
runpy.run_path(str(entry), run_name="__main__")
