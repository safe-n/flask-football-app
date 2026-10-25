import tempfile
from pathlib import Path

from fbpred import config

# testy nie mogą zapisywać parametrów do prawdziwego katalogu params/ w repo
config.PARAMS_DIR = Path(tempfile.mkdtemp(prefix="fbpred_params_"))
