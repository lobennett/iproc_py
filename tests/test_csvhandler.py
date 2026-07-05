import argparse
from pathlib import Path
from iproc.config import Config
from iproc import csvHandler
FIX = Path(__file__).parent / "fixtures"
def _c():
    c = Config(); c.parse(str(FIX / "minimal.cfg")); return c
def test_ingest():
    s = csvHandler.scansHandler(_c())
    s.ingest_task_csv(str(FIX / "tasktype.csv"))
    s.ingest_bold_csv(str(FIX / "scanlist.csv"))
    assert s.task_dict["REST"]["NUMVOL"] == "818"
    assert s.scan_by_session["ses01_TEST01"].bold_scans[5]["TYPE"] == "REST"
def test_cluster_requests():
    a = argparse.Namespace(); a.cluster = {}
    csvHandler.load_cluster_requests(str(FIX / "cluster_requests.csv"), a)
    assert a.cluster["recon_all"]["cpu"] == "16"
    assert a.cluster["recon_all"]["RUNMODE"] == "run"
