import tempfile
from pathlib import Path

from fbpred import config

# testy nie mogą zapisywać parametrów do prawdziwego katalogu params/ w repo
config.PARAMS_DIR = Path(tempfile.mkdtemp(prefix="fbpred_params_"))

# ... ani zależeć od prawdziwej historii z repo: domyślnie pusty katalog (testy, które jej potrzebują, ustawiają własny)
config.HISTORY_DIR = Path(tempfile.mkdtemp(prefix="fbpred_history_"))
