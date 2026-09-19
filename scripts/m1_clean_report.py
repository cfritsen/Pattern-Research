import pandas as pd
from pathlib import Path
from patternlab.config import load_config
from patternlab.clean import load_clean

cfg = load_config()
rows = []
for p in sorted(Path(cfg["data_dir"], "raw").glob("*.parquet")):
    df, n = load_clean(p.stem, cfg)
    if n["trimmed_prehistory"] or n["start_override"]:
        rows.append((p.stem, n["rows_in"], n["rows_out"], n["trimmed_prehistory"],
                     df.index[0].date(), n["start_override"]))
print(pd.DataFrame(rows, columns=["ticker", "rows_in", "rows_out", "trimmed",
                                  "new_first_bar", "override"]).to_string(index=False))