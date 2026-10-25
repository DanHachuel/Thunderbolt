"""1.0.33 — páginas legais e de verificação (legal/).

Critérios da tarefa: os três ficheiros existem em legal/, o index.html reflecte
as funcionalidades reais do Thunderbolt, os documentos legais são em Português
(Brasil) com conformidade explícita à LGPD (Lei 13.709/2018), e as páginas
referenciam-se entre si com os contactos do desenvolvedor.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "legal"
INDEX = (LEGAL / "index.html").read_text(encoding="utf-8")
PRIVACY = (LEGAL / "privacy.html").read_text(encoding="utf-8")
TERMS = (LEGAL / "terms.html").read_text(encoding="utf-8")
ALL_PAGES = {"index.html": INDEX, "privacy.html": PRIVACY, "terms.html": TERMS}


def test_the_three_legal_pages_exist():
    for name in ("index.html", "privacy.html", "terms.html"):
        assert (LEGAL / name).is_file(), f"legal/{name} em falta"
    # HTML5 semântico e responsivo em todas as páginas
    for name, source in ALL_PAGES.items():
        assert source.lstrip().startswith("<!DOCTYPE html>"), f"{name} não é HTML5"
        assert 'lang="pt-BR"' in source, f"{name} não declara pt-BR"
        assert '<meta name="viewport"' in source, f"{name} sem viewport (responsivo)"
        assert "<main" in source, f"{name} sem HTML semântico (<main>)"
        # CSS embutido — a página é autónoma, sem assets externos
        assert "<style>" in source, f"{name} sem CSS embutido"
        assert 'rel="stylesheet"' not in source, f"{name} não deve depender de CSS externo"


def test_index_reflects_the_real_thunderbolt_features():
    for pipeline in ("Pexels", "Pixabay", "Text-to-Images", "Nano Banana", "FAL AI",
                     "Google Imagens", "Full IA", "Remotion", "58 skills",
                     "Only Music", "Clipes de Música"):
        assert pipeline in INDEX, f"o index não menciona o pipeline {pipeline}"
    for feature in ("Roteiros", "Azure Speech", "ElevenLabs", "Thumbnails",
                    "Agendamento", "Filas paralelas", "Upload automático",
                    "Múltiplos Canais", "Nichos"):
        assert feature in INDEX, f"o index não menciona a funcionalidade {feature}"
    # plataformas de destino e serviços de IA
    for platform in ("YouTube", "TikTok", "Instagram", "Facebook", "Bilibili"):
        assert platform in INDEX, f"o index não menciona a plataforma {platform}"
    assert "YouTube Data API v3" in INDEX
    assert "TikTok Content Posting API" in INDEX
    assert "Instagram Graph API" in INDEX
    assert "Meta Graph API" in INDEX
    for service in ("OpenAI", "Gemini", "Anthropic", "Azure", "FAL AI"):
        assert service in INDEX, f"o index não menciona o serviço {service}"


def test_index_links_to_the_legal_documents_and_the_verification_footer():
    assert 'href="privacy.html"' in INDEX
    assert 'href="terms.html"' in INDEX
    assert "Dan Hachuel" in INDEX
    assert "danchannels96@gmail.com" in INDEX
    assert "verificação de aplicação" in INDEX
    # plataformas de verificação pedidas pela tarefa
    for platform in ("TikTok", "YouTube", "Meta", "Pinterest"):
        assert platform in INDEX, f"o rodapé deve citar a plataforma de verificação {platform}"


def test_privacy_is_lgpd_compliant_and_thunderbolt_specific():
    assert "LGPD" in PRIVACY
    assert "13.709/2018" in PRIVACY
    assert "Data de vigência" in PRIVACY
    # dados coletados exigidos pela tarefa
    for topic in ("E-mail", "perfis de canais", "Dados de uso", "Cookies", "OAuth"):
        assert topic in PRIVACY, f"a política não cobre {topic}"
    # armazenamento local (aplicação local, JSONs/SQLite, disco do utilizador)
    assert "disco do utilizador" in PRIVACY
    assert "JSON" in PRIVACY
    assert "SQLite" in PRIVACY or "bases locais" in PRIVACY
    # compartilhamento: texto → LLMs; vídeos → redes via APIs oficiais
    assert "OpenAI" in PRIVACY and "Gemini" in PRIVACY
    assert "Pexels" in PRIVACY and "Azure" in PRIVACY
    assert "APIs oficiais" in PRIVACY
    # direitos do titular + segurança das chaves
    assert "Direitos do Titular" in PRIVACY
    assert "Acessar" in PRIVACY and "Corrigir" in PRIVACY and "Eliminar" in PRIVACY
    assert "chaves de API" in PRIVACY
    assert "localmente" in PRIVACY


def test_terms_cover_the_essential_clauses():
    for clause in ("Aceitação", "Descrição do Serviço", "Responsabilidades do Utilizador",
                   "Limitação de Responsabilidade", "Propriedade Intelectual", "Foro"):
        assert clause in TERMS, f"os termos não contêm a cláusula {clause}"
    # fornecida "como está"
    assert "como está" in TERMS
    # responsabilidades do utilizador: conteúdo, chaves, proibição de spam/manipulação
    assert "direitos autorais" in TERMS
    assert "Chaves de API" in TERMS
    assert "spam" in TERMS
    assert "manipulação" in TERMS
    # limitação: banimentos nas plataformas e custos das APIs terceiras
    assert "banimentos" in TERMS
    assert "OpenAI" in TERMS and "Azure" in TERMS and "FAL" in TERMS
    # propriedade: uso pessoal, sem revenda; foro: Brasil
    assert "uso pessoal" in TERMS
    assert "revendidos" in TERMS
    assert "Brasil" in TERMS
    # referencia a política de privacidade
    assert 'href="privacy.html"' in TERMS
    assert 'href="index.html"' in TERMS


def test_pages_ship_in_the_npm_tarball():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    assert '"legal/*.html"' in package
