import sys, time, tracemalloc
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from pkdqc.core.geometry import ImageGeometry
from pkdqc.core.labels import LabelTable
from pkdqc.core.regions import build_region_index

def geom(shape): return ImageGeometry.from_affine(shape, np.eye(4))
def run(name, data):
    tracemalloc.start(); t=time.perf_counter(); idx=build_region_index(data, LabelTable.from_ids(np.unique(data)), geom(data.shape)); dt=time.perf_counter()-t; cur, peak=tracemalloc.get_traced_memory(); tracemalloc.stop(); print(f"{name}: {len(idx.records)} regions, {dt:.4f}s, peak {peak/1e6:.2f} MB")
shape=(80,80,40)
one=np.zeros(shape,dtype=np.uint16)
for n in range(300): one[(n*7)%78+1,(n*11)%78+1,(n*13)%38+1]=1
ind=np.zeros(shape,dtype=np.uint16)
for n in range(1,301): ind[(n*7)%78+1,(n*11)%78+1,(n*13)%38+1]=n
mix=one.copy(); mix[ind>0]=ind[ind>0]
sparse=np.zeros(shape,dtype=np.uint16); sparse[1,1,1]=60000; sparse[20,20,20]=7
dense=np.ones((50,50,30),dtype=np.uint16)
for name,data in [("shared-label",one),("individual-label",ind),("mixed",mix),("sparse-high-label",sparse),("dense",dense)]: run(name,data)
