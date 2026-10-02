import sys
import pysqlite3

sys.modules["sqlite3"] = pysqlite3

from jupyterlab.labapp import main

raise SystemExit(main())
