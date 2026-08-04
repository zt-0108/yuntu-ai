"""
一次性重建 Chroma 索引：先删除旧 collection，再用新切分重新 ingest。

放到项目根目录（与 app/ 同级），执行：
    python reingest.py

为什么要先删：旧的 ingest 用 upsert，只会更新同 id 的片段；
切分改了之后 chunk id 全变，旧片段不会被自动清掉，会和新片段并存污染检索。
"""

import chromadb

from app.config import CHROMA_COLLECTION_NAME, CHROMA_DB_DIR
from app.rag.vector_db import ingest_guide_chunks_to_chroma


def reset_collection() -> None:
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    try:
        client.delete_collection(name=CHROMA_COLLECTION_NAME)
        print(f"[reingest] 已删除旧 collection: {CHROMA_COLLECTION_NAME}")
    except Exception as exc:
        # collection 不存在时 delete 会抛错，忽略即可
        print(f"[reingest] 跳过删除（可能本就不存在）: {type(exc).__name__}: {exc}")


def main() -> None:
    reset_collection()
    count = ingest_guide_chunks_to_chroma()
    print(f"[reingest] 重新写入完成，共 {count} 个片段。")


if __name__ == "__main__":
    main()