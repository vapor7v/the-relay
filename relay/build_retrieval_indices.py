import os
from config import RETRIEVAL_SETTINGS
from indexer import PaperIndex

def build_all():
    for setting in RETRIEVAL_SETTINGS:
        path = f"paper_index_{setting.name}.pkl"
        print(f"Building index for setting {setting.name} (chunk_size={setting.chunk_size}, overlap={setting.chunk_overlap})...")
        idx = PaperIndex()
        idx.build(chunk_size=setting.chunk_size, overlap=setting.chunk_overlap)
        idx.save(path)
        print(f"Saved {path} with {len(idx.chunks)} chunks.\n")

if __name__ == "__main__":
    build_all()
