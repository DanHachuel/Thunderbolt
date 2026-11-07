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
import unicodedata
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
    # 1.0.69 - formas flexionadas: "bleeds cash" sobrevivia ao bloqueio porque
    # a lista só tinha "bleeding" (relato do vídeo do canal de finanças).
    "bleed",
    "bleeds",
    "bled",
    "bleeding",
    "bloodstream",
    "hemorrhage",
    "haemorrhage",
    "drains blood",
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

GENERIC_ANCHORS: tuple[str, ...] = ()  # reservado: nicho desconhecido NÃO leva âncoras


# Palavras de ligação que não descrevem NADA para um banco de imagens: o
# extractor de keywords àixa-as passar quando a LLM falha e o Pexels devolve
# lixo (relato: "your, rental, property, bleeds, cash, even, great, tenants").
SEARCH_STOPWORDS = frozenset(
    {
        "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
        "the", "this", "that", "these", "those", "your", "you", "my", "our", "their", "his", "her", "its",
        "and", "or", "but", "if", "then", "than", "so", "because", "while", "when", "where", "why", "how",
        "with", "without", "for", "from", "into", "about", "over", "under", "between", "during", "after",
        "before", "even", "just", "only", "also", "very", "much", "more", "most", "some", "any", "all",
        "not", "no", "yes", "is", "are", "was", "were", "be", "been", "being", "am",
        "in", "on", "at", "by", "to", "of", "off", "out", "up", "down", "as",
        # 1.0.69 - adjectivos genéricos que não descrevem nada para um banco de
        # imagens (sobreviveram ao primeiro relato: "great tenants").
        "great", "good", "bad", "big", "small", "large", "little", "new", "old", "best", "worst",
        "bom", "boa", "mau", "ma", "grande", "pequeno", "pequena", "novo", "nova", "velho", "velha", "melhor", "pior",
        "e", "ou", "mas", "se", "entao", "então", "porque", "enquanto", "quando", "onde", "por que", "como",
        "com", "sem", "para", "pelo", "pela", "entre", "durante", "depois", "antes", "apos", "após",
        "nao", "não", "sim", "muito", "mais", "menos", "todo", "toda", "todos", "todas", "cada",
    }
)


def _is_search_stopword(term: str) -> bool:
    """Verdadeiro quando o termo é só uma palavra de ligação (lixo de busca)."""
    return _ascii_fold(term) in SEARCH_STOPWORDS


def safe_search_string(terms: Iterable[Any], *, limit: int = 15, separator: str = ",") -> str:
    """String final para o Pexels/Pixabay: ESTRITAMENTE alfanumérica.

    1.0.69 - relato: a busca seguiu com ``your,rental,property,bleeds,cash,
    even,great,tenants,finanças`` — palavras soltas do título, metáfora viva e
    cedilha. Esta função deixa passar só letras/dígitos e espaços internos,
    remove as palavras de ligação e garante um fallback do nicho quando a
    lista fica vazia (a busca nunca sai vazia nem poluída).
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in terms:
        value = _ascii_fold(item)
        # estritamente alfanumérico (espaços internos preservados)
        value = " ".join(re.findall(r"[a-z0-9]+", value))
        value = " ".join(value.split())
        if len(value) < 2 or value in seen:
            continue
        if _is_search_stopword(value):
            continue
        cleaned.append(value)
        seen.add(value)
    return separator.join(cleaned[:limit])


def _ascii_fold(text: Any) -> str:
    """Minúsculas sem diacríticos (ç -> c, ã -> a…) para comparações.

    1.0.69 - A RAIZ do relato: o canal do utilizador chama-se "Finanças" (com
    ç) e a chave do dicionário é ``"financ"`` (ASCII). ``"financ" in
    "finanças"`` é FALSO em Python — as âncoras de nicho nunca apareciam e a
    busca seguia apenas com as palavras do título. Com o folding, "finanças"
    vira "financas" e o nicho casa.
    """
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return " ".join(stripped.casefold().split())


def _normalise(text: Any) -> str:
    """Casefold + folding de diacríticos + compacta espaços (comparações)."""
    return _ascii_fold(text)


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

    Casa o nicho/blueprint com ``NICHE_ANCHOR_TERMS``. Sem nicho conhecido
    devolve lista VAZIA (nada a adicionar) — quem não tem nicho declarado
    não recebe âncoras genéricas a poluir a busca.
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
    return []


def has_niche_context(*values: Any) -> bool:
    """Verdadeiro quando há nicho/blueprint conhecido (para ancorar a busca)."""
    return any(_normalise(value) for value in values)


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
    """Queries de busca saneadas + âncoras do nicho à frente (1.0.62/1.0.69).

    É o que o Pexels/Pixabay recebe: ``finance``, ``money``,
    ``investment``… ANTES de qualquer keyword extraída — um termo
    metafórico que sobreviva vem sempre DEPOIS do contexto do nicho. Sem
    nicho conhecido não há âncoras: a busca segue só com as keywords
    saneadas (nada de genéricos a poluir um canal sem nicho declarado).

    1.0.69 - três endirecções do relato (busca com palavras soltas do título):
    as palavras de ligação (``your``, ``even``, ``great`` …) saem; se a lista
    ficar VAZIA depois da limpeza, os âncoras do nicho entram sozinhos (a
    busca nunca fica sem contexto); e cada termo fica estritamente
    alfanumérico (sem cedilhas/aspas a poluir a query).
    """
    cleaned = sanitize_visual_keywords(keywords, *niche_values)
    anchors = niche_anchor_terms(*niche_values, limit=4)
    if not has_niche_context(*niche_values):
        ordered = _dedupe(cleaned)
    else:
        ordered = _dedupe([*anchors, *cleaned])
    # fallback: lista vazia (só stopwords/metáforas) -> o nicho assume a busca
    if not ordered and anchors:
        ordered = _dedupe(anchors)
    return ordered[:limit]


def _dedupe(terms: Iterable[Any]) -> list[str]:
    """Remove duplicados e palavras de ligação, preservando a ordem."""
    result: list[str] = []
    seen: set[str] = set()
    for item in terms:
        value = " ".join(_ascii_fold(item).split())
        value = " ".join(re.findall(r"[a-z0-9]+", value))
        if len(value) < 2 or value in seen or _is_search_stopword(value):
            continue
        result.append(value)
        seen.add(value)
    return result
