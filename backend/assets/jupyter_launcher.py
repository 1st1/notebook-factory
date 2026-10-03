import sys
import pysqlite3
from pathlib import Path

sys.modules["sqlite3"] = pysqlite3

# Seed after dependency restoration so cached workspaces receive current defaults.
workspace = Path(__file__).resolve().parent
plot_config = Path.home() / ".config/matplotlib/matplotlibrc"
plot_config.parent.mkdir(parents=True, exist_ok=True)
plot_config.write_text((workspace / ".notebook-matplotlibrc").read_text())

from jupyterlab.labapp import main
sys.argv.extend(
    [
        f"--LabApp.user_settings_dir={workspace / '.jupyter/lab/user-settings'}",
        f"--LabApp.templates_dir={workspace / '.jupyter/templates'}",
        f"--ServerApp.root_dir={workspace}",
    ]
)

raise SystemExit(main())
