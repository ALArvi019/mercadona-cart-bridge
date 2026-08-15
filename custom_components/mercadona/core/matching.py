"""Emparejador de texto libre a producto concreto.

Cuando alguien dice "papel higiénico" hay decenas de productos que encajan. La regla del
proyecto es sencilla y refleja cómo se compra de verdad: gana lo que ya soléis comprar.

Orden de preferencia:
  1. Alias aprendido — si alguien ya corrigió esa frase desde el panel, se respeta.
  2. Productos habituales — la lista que Mercadona mantiene sola.
  3. Historial de pedidos — lo comprado alguna vez.
  4. Catálogo del almacén — cualquier otra cosa.

Dentro de cada fuente se puntúa por parecido de texto. Una fuente mejor solo gana si su
resultado es razonablemente bueno, para que un habitual malo no tape una coincidencia
exacta del catálogo.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable

# Palabras que no aportan nada al emparejamiento.
STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o",
    "para", "con", "al", "a", "en", "por", "mas", "más",
    # Muletillas de dictado: "añade a la lista de la compra papel higiénico"
    "anade", "añade", "añadir", "anadir", "agrega", "agregar", "pon", "poner",
    "compra", "comprar", "lista", "carrito", "necesito", "hace", "falta",
    "apunta", "apuntar", "apuntame", "mete", "meter", "meteme", "echa", "echar",
    "quiero", "tambien", "ademas", "porfa", "favor",
}

# Con estas palabras la frase deja de ser "mete esto" y pasa a ser "saca esto".
REMOVE_WORDS = {
    "quita", "quitar", "quitame", "elimina", "eliminar", "borra", "borrar",
    "saca", "sacar", "retira", "retirar", "fuera", "anula", "cancela",
}

NUMBERS = {
    "un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12,
    "media": 1, "medio": 1, "par": 2,
}

# Unidades de envase: "dos paquetes de arroz" -> cantidad 2, producto "arroz".
UNITS = {
    "paquete", "paquetes", "bote", "botes", "botella", "botellas", "caja", "cajas",
    "bolsa", "bolsas", "lata", "latas", "brick", "bricks", "pack", "packs",
    "unidad", "unidades", "kilo", "kilos", "kg", "litro", "litros", "l", "docena",
    "barra", "barras", "tarro", "tarros", "sobre", "sobres", "bandeja", "bandejas",
}

SOURCE_WEIGHT = {"alias": 1.0, "regular": 0.90, "history": 0.80, "catalog": 0.68}
# Por debajo de esto no se añade nada: se pide confirmación en el panel.
MIN_SCORE = 0.42
# Para quitar del carrito se puede ser más laxo: se elige entre diez o veinte
# productos que ya están ahí, no entre miles del catálogo.
MIN_SCORE_REMOVE = 0.30
# A partir de aquí la elección se da por buena y no se avisa de nada.
CONFIDENT_SCORE = 0.60
# Si el segundo candidato queda a menos de esto del primero, la elección es un
# volado: se añade el mejor igualmente, pero avisando.
AMBIGUITY_GAP = 0.06


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9\s]", " ", text)


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if t and t not in STOPWORDS]


@dataclass
class Request:
    """Lo que se ha pedido: qué producto, cuántos y si es para añadir o para quitar."""
    intent: str          # "add" | "remove"
    query: str
    quantity: float = 1.0
    explicit_quantity: bool = False


def parse_request(text: str) -> tuple[str, float]:
    """Separa cantidad y producto: "dos paquetes de arroz" -> ("arroz", 2)."""
    r = parse_intent(text)
    return r.query, r.quantity


def parse_intent(text: str) -> Request:
    """Interpreta la frase dictada.

    Las muletillas se quitan antes de buscar el número, porque la gente dice
    "añade 2 mantequillas" y no "2 mantequillas": buscar la cantidad solo al
    principio de la frase se dejaba fuera el caso normal.
    """
    words = [w for w in normalize(text).split() if w and w not in STOPWORDS]

    intent = "add"
    if words and words[0] in REMOVE_WORDS:
        intent = "remove"
        words.pop(0)

    qty = 1.0
    explicit = False
    if words and words[0].isdigit() and int(words[0]) < 100:
        qty, explicit = float(words.pop(0)), True
    elif words and words[0] in NUMBERS:
        qty, explicit = float(NUMBERS[words.pop(0)]), True

    # Quita la unidad de envase si va justo delante del producto.
    while words and words[0] in UNITS:
        words.pop(0)

    return Request(intent, " ".join(words), qty, explicit)


def _token_similarity(qt: str, nt: str) -> float:
    """Parecido entre una palabra pedida y una del nombre del producto."""
    if qt == nt:
        return 1.0
    # Plurales y variantes ("yogur"/"yogures"). Se exige que ambas palabras sean
    # largas y de longitud parecida: si no, el "de" de "Huevos de gallinas" casaría
    # con "detergente" y colaría cualquier cosa.
    if len(qt) >= 4 and len(nt) >= 4 and abs(len(qt) - len(nt)) <= 3:
        if nt.startswith(qt) or qt.startswith(nt):
            return 0.9
    if len(qt) < 4 or len(nt) < 4:
        return 0.0
    return SequenceMatcher(None, qt, nt).ratio() * 0.8


def _score(query_tokens: list[str], name: str) -> float:
    """Parecido entre lo dicho y el nombre del producto, de 0 a 1."""
    if not query_tokens:
        return 0.0
    name_norm = normalize(name)
    name_tokens = name_norm.split()
    if not name_tokens:
        return 0.0

    # Cuántas palabras de lo pedido aparecen en el nombre.
    hits = 0.0
    for qt in query_tokens:
        best = max((_token_similarity(qt, nt) for nt in name_tokens), default=0.0)
        hits += best if best > 0.6 else 0.0
    coverage = hits / len(query_tokens)

    # La frase completa dentro del nombre es señal fuerte ("papel higienico").
    phrase = " ".join(query_tokens)
    exact = 1.0 if phrase in name_norm else 0.0

    # Que el nombre empiece por lo pedido distingue "Leche semidesnatada" de
    # "Fruta + leche tropical": las dos contienen "leche", pero solo una es leche.
    leading = 1.0 if name_norm.startswith(phrase) else 0.0

    # Entre dos productos que encajan igual, preferimos el de nombre más escueto,
    # que suele ser el genérico y no una variante rara.
    brevity = min(1.0, 4.0 / max(1, len(name_tokens)))

    return 0.60 * coverage + 0.18 * exact + 0.14 * leading + 0.08 * brevity


@dataclass
class Match:
    product: dict[str, Any]
    score: float
    source: str
    quantity: float = 1.0

    @property
    def product_id(self) -> str:
        return str(self.product["id"])

    @property
    def name(self) -> str:
        return self.product.get("display_name", "")


def _available(p: dict[str, Any]) -> bool:
    return p.get("published", True) and p.get("status") != "unavailable"


def _best(query_tokens: list[str], products: Iterable[dict[str, Any]], source: str,
          limit: int = 5, only_available: bool = True) -> list[Match]:
    scored = [
        Match(p, _score(query_tokens, p.get("display_name", "")), source)
        for p in products if not only_available or _available(p)
    ]
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:limit]


class Matcher:
    def __init__(self, catalog, regulars_provider, history_provider, aliases_provider):
        self._catalog = catalog
        self._regulars = regulars_provider      # () -> list[product]
        self._history = history_provider        # () -> list[product]
        self._aliases = aliases_provider        # (phrase) -> product_id | None

    def resolve_in_cart(self, cart_products: list[dict[str, Any]],
                        text: str) -> tuple[Match | None, list[Match]]:
        """Empareja lo dicho contra lo que ya hay en el carrito, para poder quitarlo.

        Aquí no se filtra por disponibilidad: un producto que se ha quedado sin stock
        sigue estando en el carrito y hay que poder sacarlo.
        """
        request = parse_intent(text)
        qt = tokens(request.query)
        if not qt or not cart_products:
            return None, []
        candidates = _best(qt, cart_products, "cart", limit=5, only_available=False)
        for m in candidates:
            m.quantity = request.quantity
        if not candidates or candidates[0].score < MIN_SCORE_REMOVE:
            return None, candidates
        return candidates[0], candidates[1:]

    def resolve(self, text: str) -> tuple[Match | None, list[Match], float]:
        """Devuelve (mejor coincidencia, alternativas, cantidad pedida)."""
        query, qty = parse_request(text)
        qt = tokens(query)
        if not qt:
            return None, [], qty

        alias_id = self._aliases(query)
        if alias_id:
            p = (self._catalog.products.get(alias_id)
                 or next((x for x in self._regulars() if str(x["id"]) == alias_id), None))
            if p:
                return Match(p, 1.0, "alias", qty), [], qty

        candidates: list[Match] = []
        candidates += _best(qt, self._regulars(), "regular")
        candidates += _best(qt, self._history(), "history")
        candidates += _best(qt, self._catalog.products.values(), "catalog")

        # Una fuente preferente solo gana si además ha acertado razonablemente.
        for m in candidates:
            m.score = m.score * SOURCE_WEIGHT[m.source] + (0.06 if m.source == "regular" else 0.0)

        seen: set[str] = set()
        unique: list[Match] = []
        for m in sorted(candidates, key=lambda m: m.score, reverse=True):
            if m.product_id in seen:
                continue
            seen.add(m.product_id)
            m.quantity = qty
            unique.append(m)

        if not unique or unique[0].score < MIN_SCORE:
            return None, unique[:5], qty
        return unique[0], unique[1:5], qty
