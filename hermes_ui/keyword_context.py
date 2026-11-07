"""1.0.62 — contexto de nicho nas keywords de vídeo (fim do literalismo).

O relato do utilizador: um vídeo do canal de finanças («Why your rental
property bleeds cash») gerou imagens de ARTÉRIAS e HEMÁCEIAS porque o termo
metafórico «bleeding cash» foi usado literalmente pelo extractor de
keywords e enviado ao Pexels/Pixabay. A imagem passou a ser de anatomia
humana num canal de finanças — inaceitável, e acontece em qualquer
blueprint quando o roteiro usa metáforas corporais.

Este módulo concentra a defesa em três camadas:
1. ``NICHE_METAPHOR_BLOCKLIST`` — termos que só fazem sentido em canais de
   SAÚDE; em qualquer outro nicho são removidas das keywords (a LLM pode
   ter extraído a metáfora apesar do prompt);
2. ``NICHE_ANCHOR_TERMS`` — substituição determinística por termos do
   nicho (finanças → finance/money/business/investment…) para a keyword não
   ficar vazia;
3. ``niche_anchor_terms`` — termos-âncora para ENRIQUECER a busca enviada
   ao Pexels/Pixabay ([keyword] + [nicho]).
"""

from __future__ import annotations

import re
from typing import Any, Iterable


# Termos que, fora de um canal de saúde, são SEMPRE erro de extração: o
# roteiro usou uma metáfora corporal e a busca trouxe anatomia/sangue.
NICHE_METAPHOR_BLOCKLIST = (
    "blood",
    "bleeding",
    "bloody",
    "artery",
    "arteries",
    "arterial",
    "vein",
    "veins",
    "capillary",
    "capillaries",
    "red blood cell",
    "red blood cells",
    "blood cell",
    "blood cells",
    "hemoglobin",
    "heart",
    "hearts",
    "cardiac",
    "heartbeat",
    "pulse",
    "medical",
    "medicine",
    "hospital",
    "hospitals",
    "clinic",
    "surgery",
    "surgical",
    "operation room",
    "emergency room",
    "doctor",
    "doctors",
    "nurse",
    "nurses",
    "patient",
    "patients",
    "diagnosis",
    "symptom",
    "symptoms",
    "disease",
    "illness",
    "anatomy",
    "anatomical",
    "organism",
    "organ",
    "organs",
    "tissue",
    "muscle",
    "muscles",
    "bone",
    "bones",
    "skin",
    "wound",
    "wounds",
    "injury",
    "pain",
    "death",
    "dead",
    "dying",
    "corpse",
    "funeral",
    "cemetery",
    "virus",
    "bacteria",
    "infection",
    "vaccine",
    "vaccination",
    "cancer",
    "tumor",
    "stroke",
    "bleeding out",
)

# Marcas de nicho de SAÚDE: só aí os termos acima são legítimos.
HEALTH_NICHE_MARKERS = (
    "saúde",
    "saude",
    "health",
    "médic",
    "medic",
    "enfermagem",
    "nursing",
    "clínic",
    "clinic",
    "hospital",
    "farma",
    "farmá",
    "wellness",
    "bem-estar",
    "bem estar",
    "psicolog",
    "psycholog",
    "nutriç",
    "nutric",
    "fisioterap",
    "physiotherap",
    "odont",
    "dental",
    "veterin",
    "medicina",
    "cirurg",
    "biolog",
    "anatom",
)

# Substituição determinística por nicho conhecido. A chave casa por
# substring com o nicho/blueprint (casefold).
NICHE_ANCHOR_TERMS: dict[str, tuple[str, ...]] = {
    "financ": (
        "finance",
        "money",
        "business",
        "investment",
        "cash flow",
        "accounting",
        "stock market",
        "office",
    ),
    "money": ("finance", "money", "business", "investment", "cash flow", "office"),
    "invest": ("investment", "finance", "stock market", "business", "money"),
    "econom": ("economy", "finance", "business", "market", "money"),
    "business": ("business", "office", "finance", "meeting", "money"),
    "empreend": ("business", "office", "finance", "entrepreneur", "meeting"),
    "negóci": ("business", "finance", "office", "market", "money"),
    "negoci": ("business", "finance", "office", "market", "money"),
    "imóv": ("real estate", "property", "house", "architecture", "city"),
    "imovel": ("real estate", "property", "house", "architecture", "city"),
    "real estate": ("real estate", "property", "house", "city", "architecture"),
    "rental": ("real estate", "property", "apartment", "house", "city"),
    "aluguel": ("real estate", "property", "apartment", "house", "city"),
    "crypto": ("cryptocurrency", "finance", "technology", "trading", "digital"),
    "bitcoin": ("cryptocurrency", "finance", "technology", "trading"),
    "tech": ("technology", "computer", "data", "code", "office"),
    "tecnolog": ("technology", "computer", "data", "code", "office"),
    "ai": ("artificial intelligence", "technology", "computer", "data", "robot"),
    "inteligência artificial": ("artificial intelligence", "technology", "computer", "data", "robot"),
    "market": ("marketing", "business", "office", "advertising", "meeting"),
    "marketing": ("marketing", "business", "advertising", "office", "meeting"),
    "educ": ("education", "school", "books", "study", "classroom"),
    "educaç": ("education", "school", "books", "study", "classroom"),
    "school": ("education", "school", "books", "study", "classroom"),
    "fitness": ("fitness", "gym", "workout", "running", "health"),
    "fitness": ("fitness", "gym", "workout", "running"),
    "travel": ("travel", "landscape", "city", "nature", "vacation"),
    "viagem": ("travel", "landscape", "city", "nature"),
    "food": ("food", "cooking", "kitchen", "restaurant", "agriculture"),
    "comida": ("food", "cooking", "kitchen", "restaurant"),
    "ciência": ("science", "laboratory", "research", "space", "data"),
    "ciencia": ("science", "laboratory", "research", "space", "data"),
    "science": ("science", "laboratory", "research", "space", "data"),
    "polít": ("politics", "government", "city", "flag", "crowd"),
    "politic": ("politics", "government", "city", "flag", "crowd"),
    "history": ("history", "ancient", "castle", "museum", "art"),
    "histór": ("history", "ancient", "castle", "museum", "art"),
    "relig": ("religion", "church", "faith", "sky", "candles"),
    "motiv": ("motivation", "sunrise", "mountain", "running", "success"),
    "auto": ("car", "road", "driving", "garage", "city"),
    "carro": ("car", "road", "driving", "garage", "city"),
    "nature": ("nature", "forest", "mountain", "ocean", "wildlife"),
    "natureza": ("nature", "forest", "mountain", "ocean", "wildlife"),
    "gaming": ("gaming", "computer", "esports", "neon", "controller"),
    "game": ("gaming", "computer", "esports", "controller", "neon"),
    "fashion": ("fashion", "clothing", "model", "studio", "shopping"),
    "moda": ("fashion", "clothing", "model", "studio", "shopping"),
    "music": ("music", "concert", "instrument", "studio", "microphone"),
    "música": ("music", "concert", "instrument", "studio", "microphone"),
    "musica": ("music", "concert", "instrument", "studio", "microphone"),
    "sustent": ("sustainability", "nature", "solar", "forest", "recycling"),
    "ambient": ("environment", "nature", "forest", "ocean", "earth"),
    "meio ambiente": ("environment", "nature", "forest", "ocean", "earth"),
}

GENERIC_ANCHORS = ("business", "office", "money", "data", "success", "city")


def _normalise(text: Any) -> str:
    """Casefold + compacta espaços (comparações tolerantes)."""
    return " ".join(str(text or "").casefold().split())


def _has_blocked_term(term: str) -> str | None:
    """Devolve o termo bloqueado contido em ``term`` (substring, não só igual)."""
    normalised = _normalise(term)
    for blocked in NICHE_METAPHOR_BLOCKLIST:
        if re.search(rf"(?<![a-z]){re.escape(blocked)}(?![a-z])", normalised):
            return blocked
    return None


def is_health_niche(*values: Any) -> bool:
    """Verdadeiro quando o nicho/blueprint é de SAÚDE (aí o termo é legítimo)."""
    for value in values:
        normalised = _normalise(value)
        if not normalised:
            continue
        if any(marker in normalised for marker in HEALTH_NICHE_MARKERS):
            return True
    return False


def niche_anchor_terms(*values: Any, limit: int = 4) -> list[str]:
    """Termos-âncora do nicho para ENRIQUECER a busca ([keyword] + [nicho]).

    Casa o nicho/blueprint com ``NICHE_ANCHOR_TERMS``; sem correspondência
    devolve os genéricos (ordenados, sem duplicados).
    """
    for value in values:
        normalised = _normalise(value)
        if not normalised:
            continue
        for key, terms in NICHE_ANCHOR_TERMS.items():
            if key in normalised:
                result: list[str] = []
                for term in terms:
                    if term not in result:
                        result.append(term)
                    if len(result) >= limit:
                        return result
                return result
    return list(GENERIC_ANCHORS[:limit])


def sanitize_visual_keywords(
    keywords: Iterable[Any],
    *niche_values: Any,
    minimum: int = 6,
) -> list[str]:
    """Remove metáforas perigosas e substitui-as por termos do nicho (1.0.62).

    - canal de SAÚDE: nada é filtrado (sangue/hospital são o tema);
    - qualquer outro: um keyword bloqueado (ex.: ``bleeding cash``) é
      DESCARTADO e, se a lista ficar curta, preenchida com os termos-âncora
      do nicho — a busca ao Pexels nunca fica sem contexto;
    - duplicados (casefold) colapsados; ordem preservada.
    """
    health = is_health_niche(*niche_values)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in keywords:
        value = re.sub(r"\s+", " ", str(item or "").strip())
        if not value:
            continue
        normalised = value.casefold()
        if normalised in seen:
            continue
        if not health and _has_blocked_term(value):
            continue
        cleaned.append(value)
        seen.add(normalised)
    if not health and len(cleaned) < minimum:
        for anchor in niche_anchor_terms(*niche_values, limit=max(minimum, 4)):
            if anchor.casefold() not in seen:
                cleaned.append(anchor)
                seen.add(anchor.casefold())
            if len(cleaned) >= minimum:
                break
    return cleaned[:15]


def keyword_queries_enriched(
    keywords: Iterable[Any],
    *niche_values: Any,
    limit: int = 15,
) -> list[str]:
    """Queries de busca saneadas + âncoras do nicho à frente (1.0.62).

    É o que o Pexels/Pixabay recebe: ``finance``, ``money``,
    ``investment``… ANTES de qualquer keyword extraída — um termo
    metafórico que sobreviva vem sempre DEPOIS do contexto do nicho.
    """
    cleaned = sanitize_visual_keywords(keywords, *niche_values)
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        normalised = term.casefold()
        if term and normalised not in seen:
            ordered.append(term)
            seen.add(normalised)

    for anchor in niche_anchor_terms(*niche_values, limit=4):
        _add(anchor)
    for term in cleaned:
        _add(term)
    return ordered[:limit]
