"""
构建会计科目向量数据库

用法:
    python build_db.py                          # 构建（默认中文模型）
    python build_db.py --model all-MiniLM-L6-v2  # 指定其他模型
    python build_db.py --rebuild                 # 强制重建
"""

import argparse
import os
import sys

import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer

# 取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "chroma_db")

sys.path.insert(0, BASE_DIR)
from data import ACCOUNTING_SUBJECTS


class ChineseEmbeddingFunction(EmbeddingFunction):
    """使用 sentence-transformers 中文模型做 embedding"""

    def __init__(self, model_name: str = None):
        if model_name is None:
            model_name = "shibing624/text2vec-base-chinese"
        print(f"[Embedding] 加载模型: {model_name}")
        self.model = SentenceTransformer(model_name, trust_remote_code=True)

    def __call__(self, input: Documents) -> Embeddings:
        embeddings = self.model.encode(
            list(input),
            show_progress_bar=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()


def build_vector_db(model_name: str = None, rebuild: bool = False):
    """构建会计科目向量数据库"""
    if rebuild and os.path.exists(DB_DIR):
        import shutil
        print(f"[Build] 删除旧数据库: {DB_DIR}")
        shutil.rmtree(DB_DIR)

    # ChromaDB 客户端（持久化到本地目录）
    client = chromadb.PersistentClient(path=DB_DIR)

    # embedding 函数
    embed_fn = ChineseEmbeddingFunction(model_name)

    # 创建或获取 collection
    collection = client.get_or_create_collection(
        name="accounting_subjects",
        embedding_function=embed_fn,
        metadata={"description": "担保企业会计核算办法 — 会计科目"},
    )

    # 检查是否已有数据
    if collection.count() > 0 and not rebuild:
        print(f"[Build] 数据库已存在，共 {collection.count()} 条记录")
        print("[Build] 如需重建请使用 --rebuild 参数")
        return

    # 准备数据
    documents = []
    metadatas = []
    ids = []

    for subj in ACCOUNTING_SUBJECTS:
        # document = 用于语义搜索的文本（综合所有字段）
        doc = (
            f"科目名称: {subj['name']}\n"
            f"科目编号: {subj['code']}\n"
            f"类别: {subj['category']}\n"
            f"使用说明: {subj['usage']}\n"
            f"对应报表项目: {subj['report_item']}"
        )
        documents.append(doc)

        metadatas.append({
            "order": subj["order"],
            "code": subj["code"],
            "name": subj["name"],
            "category": subj["category"],
            "report_item": subj["report_item"],
        })
        ids.append(subj["code"])  # 用科目编号作为唯一 ID

    # 批量添加
    print(f"[Build] 正在写入 {len(documents)} 条记录...")
    collection.add(
        documents=documents,
        metadatas=metadatas,
        ids=ids,
    )

    print(f"[Build] 完成！数据库路径: {DB_DIR}")
    print(f"[Build] 集合 '{collection.name}' 共 {collection.count()} 条记录")


def main():
    parser = argparse.ArgumentParser(description="构建会计科目向量数据库")
    parser.add_argument("--model", default=None,
                        help="sentence-transformers 模型名称（默认: shibing624/text2vec-base-chinese）")
    parser.add_argument("--rebuild", action="store_true",
                        help="强制重建数据库")
    args = parser.parse_args()

    build_vector_db(model_name=args.model, rebuild=args.rebuild)


if __name__ == "__main__":
    main()
