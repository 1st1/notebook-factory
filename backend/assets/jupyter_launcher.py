import sys
import pysqlite3
from pathlib import Path

sys.modules["sqlite3"] = pysqlite3

from jupyterlab.labapp import main

workspace = Path(__file__).resolve().parent
sys.argv.extend(
    [
        f"--LabApp.user_settings_dir={workspace / '.jupyter/lab/user-settings'}",
        f"--LabApp.templates_dir={workspace / '.jupyter/templates'}",
        f"--ServerApp.root_dir={workspace}",
    ]
)

raise SystemExit(main())
