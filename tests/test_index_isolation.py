from pathlib import Path
from patternlab.config import index_data_dir


def test_each_index_gets_its_own_folders(tmp_path):
    a = {"index": "sp500", "data_dir": str(tmp_path)}
    b = {"index": "nasdaq", "data_dir": str(tmp_path)}
    for kind in ("raw", "features", "outcomes"):
        pa, pb = index_data_dir(a, kind), index_data_dir(b, kind)
        assert pa != pb
        assert pa == Path(tmp_path) / "sp500" / kind
        assert pb == Path(tmp_path) / "nasdaq" / kind
