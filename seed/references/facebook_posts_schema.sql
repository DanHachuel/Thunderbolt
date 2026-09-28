CREATE TABLE IF NOT EXISTS facebook_posts (
    id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    tema TEXT NOT NULL,
    tom TEXT NOT NULL,
    titulo_gerado TEXT,
    artigo_text TEXT,
    slug TEXT,
    quantidade_imagens INTEGER DEFAULT 5,
    status TEXT NOT NULL DEFAULT 'tema_pendente',
    pasta_local TEXT,
    link_publicado TEXT,
    imagens_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_facebook_posts_channel_status
    ON facebook_posts(channel_id, status);

CREATE INDEX IF NOT EXISTS idx_facebook_posts_channel_tema
    ON facebook_posts(channel_id, tema);

CREATE TABLE IF NOT EXISTS facebook_post_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id TEXT NOT NULL,
    image_index INTEGER NOT NULL,
    search_query TEXT,
    overlay_text TEXT,
    image_path TEXT,
    image_final_path TEXT,
    provider TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id) REFERENCES facebook_posts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_facebook_post_images_post
    ON facebook_post_images(post_id, image_index);
