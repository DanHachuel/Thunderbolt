"""Roda DENTRO do Kaggle. Dataset já montado em /kaggle/input/."""
import json
import os
import re
import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
from mlxtend.frequent_patterns import association_rules, fpgrowth
from mlxtend.preprocessing import TransactionEncoder
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer

DATASET_DIR = Path("/kaggle/input/trending-youtube-videos-113-countries")
OUTPUT_DIR = Path("/kaggle/working/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

N_CLUSTERS = int(os.environ.get("NICHE_N_CLUSTERS", "5"))
MIN_SUPPORT = float(os.environ.get("NICHE_MIN_SUPPORT", "0.05"))
MAX_ROWS = int(os.environ.get("NICHE_MAX_ROWS", "50000"))


def find_csv() -> Path:
    if not DATASET_DIR.exists():
        raise FileNotFoundError(f"Dataset não encontrado em {DATASET_DIR}")
    csvs = list(DATASET_DIR.rglob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"Nenhum CSV em {DATASET_DIR}")
    csvs.sort(key=lambda path: path.stat().st_size, reverse=True)
    print(f"CSV: {csvs[0]} ({csvs[0].stat().st_size / 1e6:.1f} MB)")
    return csvs[0]


def load_dataset(csv_path: Path) -> pd.DataFrame:
    print(f"Carregando {csv_path.name} (máx {MAX_ROWS} linhas)...")
    df = pd.read_csv(csv_path, nrows=MAX_ROWS, low_memory=False)
    print(f"Carregado: {len(df)} linhas, {len(df.columns)} colunas")
    aliases = {
        "title": ["title", "video_title", "name"],
        "tags": ["video_tags", "tags", "keywords"],
        "views": ["view_count", "views", "video_views"],
        "likes": ["like_count", "likes", "video_likes"],
        "comments": ["comment_count", "comments", "video_comments"],
    }
    for canonical, options in aliases.items():
        for option in options:
            if option in df.columns:
                if canonical != option:
                    df[canonical] = df[option]
                break
        else:
            print(f"[AVISO] Coluna '{canonical}' ausente.")
            df[canonical] = ""
    return df


def run_kmeans(df: pd.DataFrame) -> pd.DataFrame:
    print(f"\n=== K-Means ({N_CLUSTERS} clusters) ===")
    df["title_clean"] = (
        df["title"].fillna("").astype(str).str.lower()
        .str.replace(r"[^a-z\s]", "", regex=True).str.strip()
    )
    mask = df["title_clean"].str.len() > 0
    if mask.sum() < N_CLUSTERS:
        raise ValueError("Poucos títulos válidos.")
    vectorizer = TfidfVectorizer(max_features=500, stop_words="english", min_df=2, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(df.loc[mask, "title_clean"])
    features = vectorizer.get_feature_names_out()
    model = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
    df.loc[mask, "cluster"] = model.fit_predict(matrix)
    df["cluster"] = df["cluster"].fillna(-1).astype(int)
    rows = []
    for cluster_id in range(N_CLUSTERS):
        top = [features[index] for index in np.argsort(model.cluster_centers_[cluster_id])[-15:][::-1]]
        cluster_frame = df[df["cluster"] == cluster_id]
        views = pd.to_numeric(cluster_frame["views"], errors="coerce").fillna(0)
        likes = pd.to_numeric(cluster_frame["likes"], errors="coerce").fillna(0)
        comments = pd.to_numeric(cluster_frame["comments"], errors="coerce").fillna(0)
        rows.append({
            "cluster_id": cluster_id,
            "palavras": ", ".join(top),
            "tamanho": int(len(cluster_frame)),
            "media_visualizacoes": float(views.mean()),
            "media_engagement": float(((likes + comments) / views.clip(lower=1) * 100).mean()),
        })
    return pd.DataFrame(rows).sort_values("tamanho", ascending=False)


def parse_tags(value) -> list[str]:
    if pd.isna(value):
        return []
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "[]", "{}"}:
        return []
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(tag).strip().lower() for tag in parsed if str(tag).strip()]
        except json.JSONDecodeError:
            pass
    return [part.strip().lower() for part in re.split(r"[|,]", text.strip("[]")) if part.strip()]


def run_fpgrowth(df: pd.DataFrame):
    print(f"\n=== FP-Growth (min_support={MIN_SUPPORT}) ===")
    df["tags_list"] = df["tags"].apply(parse_tags)
    baskets = [tags for tags in df["tags_list"] if len(tags) >= 2]
    if len(baskets) < 10:
        print("[AVISO] Poucas transações.")
        return pd.DataFrame(), pd.DataFrame()
    encoder = TransactionEncoder()
    encoded = pd.DataFrame(encoder.fit(baskets).transform(baskets), columns=encoder.columns_)
    frequent = fpgrowth(encoded, min_support=MIN_SUPPORT, use_colnames=True)
    if frequent.empty:
        return pd.DataFrame(), pd.DataFrame()
    rules = association_rules(frequent, metric="lift", min_threshold=1.0).sort_values("lift", ascending=False)
    frequent["itemsets"] = frequent["itemsets"].apply(lambda values: ", ".join(sorted(values)))
    for column in ("antecedents", "consequents"):
        rules[column] = rules[column].apply(lambda values: ", ".join(sorted(values)))
    rules = rules[["antecedents", "consequents", "support", "confidence", "lift"]]
    return frequent, rules


def main():
    try:
        frame = load_dataset(find_csv())
        clusters = run_kmeans(frame)
        frequent, rules = run_fpgrowth(frame)
        clusters.to_csv(OUTPUT_DIR / "clusters.csv", index=False)
        if frequent.empty:
            pd.DataFrame(columns=["support", "itemsets"]).to_csv(OUTPUT_DIR / "frequent_items.csv", index=False)
        else:
            frequent.to_csv(OUTPUT_DIR / "frequent_items.csv", index=False)
        if rules.empty:
            pd.DataFrame(columns=["antecedents", "consequents", "support", "confidence", "lift"]).to_csv(
                OUTPUT_DIR / "association_rules.csv", index=False
            )
        else:
            rules.to_csv(OUTPUT_DIR / "association_rules.csv", index=False)
        print("\n=== ANÁLISE CONCLUÍDA ===")
    except Exception:
        print("\n=== ERRO ===")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
