"""
Deterministic geographic eligibility policy for job listings.

This module is intentionally dependency-free: it uses only the Python standard
library so it can be unit-tested without importing settings, pydantic, Groq, or
any other project module. It performs no I/O.

Policy summary:
- The candidate lives in Mar del Plata, Argentina.
- Remote work is acceptable everywhere, unless the listing requires residence in
  a foreign country.
- On-site and hybrid work is acceptable only in Mar del Plata.
- Anything that cannot be classified as eligible fails closed (blocked).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class WorkMode(str, Enum):
    """How the job is expected to be performed."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


# Stable machine-readable reason codes. They are logged and persisted in the DB,
# so treat them as part of the public contract.
REASON_REMOTE_OK = "remote_ok"
REASON_REMOTE_FOREIGN_RESTRICTED = "remote_foreign_restricted"
REASON_ONSITE_CANDIDATE_CITY = "onsite_candidate_city"
REASON_ONSITE_FOREIGN = "onsite_foreign"
REASON_ONSITE_OTHER_ARGENTINA = "onsite_other_argentina"
REASON_UNKNOWN_LOCATION = "unknown_location"
REASON_UNKNOWN_WORK_MODE_FOREIGN = "unknown_work_mode_foreign"
REASON_REMOTE_DISABLED = "remote_disabled"


@dataclass(frozen=True)
class LocationVerdict:
    """Outcome of the geographic eligibility classification."""

    eligible: bool
    reason: str
    work_mode: str
    country: Optional[str]
    city: Optional[str]
    human_reason: str


# --- Text normalization -----------------------------------------------------

def _normalize(text: Optional[str]) -> str:
    """Lowercase, strip accents, and collapse whitespace/separators."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", str(text))
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    lowered = without_accents.lower()
    # Treat "_" and "-" as word separators so "remote-spain" matches "remote".
    replaced = re.sub(r"[_\-]", " ", lowered)
    return re.sub(r"\s+", " ", replaced).strip()


def _contains_phrase(text: str, phrase: str) -> bool:
    """Word-boundary aware substring check over already-normalized text."""
    if not text or not phrase:
        return False
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _has_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(_contains_phrase(text, phrase) for phrase in phrases)


# --- Country and city catalogs ---------------------------------------------

# Canonical country name -> English/Spanish surface aliases.
_COUNTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "Argentina": ("argentina", "arg"),
    "Spain": ("spain", "espana"),
    "Mexico": ("mexico",),
    "Colombia": ("colombia",),
    "Chile": ("chile",),
    "Uruguay": ("uruguay",),
    "Brazil": ("brazil", "brasil"),
    "Peru": ("peru",),
    "Ecuador": ("ecuador",),
    "Bolivia": ("bolivia",),
    "Paraguay": ("paraguay",),
    "Venezuela": ("venezuela",),
    "United States": ("usa", "united states", "estados unidos", "eeuu", "ee uu"),
    "Canada": ("canada",),
    "Portugal": ("portugal",),
    "Germany": ("germany", "alemania"),
    "France": ("france", "francia"),
    "Italy": ("italy", "italia"),
    "Netherlands": ("netherlands", "paises bajos", "holanda"),
    "United Kingdom": ("uk", "united kingdom", "reino unido", "england", "inglaterra"),
    "Ireland": ("ireland", "irlanda"),
    "Poland": ("poland", "polonia"),
    "Romania": ("romania", "rumania"),
    "India": ("india",),
    "Philippines": ("philippines", "filipinas"),
    "Costa Rica": ("costa rica",),
    "Panama": ("panama",),
    "Dominican Republic": ("dominican republic", "republica dominicana"),
    "Guatemala": ("guatemala",),
    "Honduras": ("honduras",),
    "El Salvador": ("el salvador",),
    "Nicaragua": ("nicaragua",),
    "Cuba": ("cuba",),
    "Puerto Rico": ("puerto rico",),
}

# display name, canonical country, normalized aliases
_CITY_ENTRIES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # Spain
    ("Madrid", "Spain", ("madrid",)),
    ("Barcelona", "Spain", ("barcelona",)),
    ("Valencia", "Spain", ("valencia",)),
    ("Seville", "Spain", ("seville", "sevilla")),
    ("Malaga", "Spain", ("malaga",)),
    ("Murcia", "Spain", ("murcia",)),
    ("Girona", "Spain", ("girona", "gerona")),
    ("A Coruna", "Spain", ("a coruna", "la coruna")),
    ("Marbella", "Spain", ("marbella",)),
    ("Sant Cugat", "Spain", ("sant cugat",)),
    ("Sant Just Desvern", "Spain", ("sant just desvern",)),
    ("Bilbao", "Spain", ("bilbao",)),
    ("Zaragoza", "Spain", ("zaragoza",)),
    # Mexico
    ("Mexico City", "Mexico", ("mexico city", "cdmx", "ciudad de mexico")),
    ("Guadalajara", "Mexico", ("guadalajara",)),
    ("Monterrey", "Mexico", ("monterrey",)),
    ("Queretaro", "Mexico", ("queretaro",)),
    ("Tlaquepaque", "Mexico", ("tlaquepaque",)),
    ("Jalisco", "Mexico", ("jalisco",)),
    ("Puebla", "Mexico", ("puebla",)),
    ("Ecatepec", "Mexico", ("ecatepec",)),
    ("Nezahualcoyotl", "Mexico", ("nezahualcoyotl",)),
    ("Torreon", "Mexico", ("torreon",)),
    ("Tijuana", "Mexico", ("tijuana",)),
    ("Toluca", "Mexico", ("toluca",)),
    ("Leon", "Mexico", ("leon",)),
    # Colombia
    ("Bogota", "Colombia", ("bogota",)),
    ("Medellin", "Colombia", ("medellin",)),
    ("Cali", "Colombia", ("cali",)),
    ("Barranquilla", "Colombia", ("barranquilla",)),
    ("Pereira", "Colombia", ("pereira",)),
    ("Ibague", "Colombia", ("ibague",)),
    ("Soacha", "Colombia", ("soacha",)),
    ("Palmira", "Colombia", ("palmira",)),
    ("Antioquia", "Colombia", ("antioquia",)),
    ("Cauca", "Colombia", ("cauca",)),
    ("Cundinamarca", "Colombia", ("cundinamarca",)),
    ("Risaralda", "Colombia", ("risaralda",)),
    ("Valle del Cauca", "Colombia", ("valle del cauca",)),
    ("Atlantico", "Colombia", ("atlantico",)),
    ("Tolima", "Colombia", ("tolima",)),
    # Chile
    ("Santiago", "Chile", ("santiago",)),
    ("Valparaiso", "Chile", ("valparaiso",)),
    ("Concepcion", "Chile", ("concepcion",)),
    ("Antofagasta", "Chile", ("antofagasta",)),
    ("Vina del Mar", "Chile", ("vina del mar",)),
    # Uruguay
    ("Montevideo", "Uruguay", ("montevideo",)),
    ("Salto", "Uruguay", ("salto",)),
    ("Rivera", "Uruguay", ("rivera",)),
    ("Canelones", "Uruguay", ("canelones",)),
    ("Las Piedras", "Uruguay", ("las piedras",)),
    ("Ciudad de la Costa", "Uruguay", ("ciudad de la costa",)),
    ("Maldonado", "Uruguay", ("maldonado",)),
    ("Paysandu", "Uruguay", ("paysandu",)),
    # Brazil
    ("Sao Paulo", "Brazil", ("sao paulo",)),
    ("Rio de Janeiro", "Brazil", ("rio de janeiro",)),
    ("Belo Horizonte", "Brazil", ("belo horizonte",)),
    ("Curitiba", "Brazil", ("curitiba",)),
    ("Porto Alegre", "Brazil", ("porto alegre",)),
    # Peru
    ("Lima", "Peru", ("lima",)),
    ("Arequipa", "Peru", ("arequipa",)),
    ("Trujillo", "Peru", ("trujillo",)),
    # Ecuador
    ("Quito", "Ecuador", ("quito",)),
    ("Guayaquil", "Ecuador", ("guayaquil",)),
    # Bolivia
    ("La Paz", "Bolivia", ("la paz",)),
    ("Santa Cruz de la Sierra", "Bolivia", ("santa cruz de la sierra",)),
    ("Cochabamba", "Bolivia", ("cochabamba",)),
    # Paraguay
    ("Asuncion", "Paraguay", ("asuncion",)),
    ("Ciudad del Este", "Paraguay", ("ciudad del este",)),
    # Venezuela
    ("Caracas", "Venezuela", ("caracas",)),
    ("Maracaibo", "Venezuela", ("maracaibo",)),
)

# Argentine cities that are NOT the candidate city. On-site/hybrid jobs there
# are blocked; remote jobs are fine.
_ARGENTINA_CITIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Buenos Aires", ("buenos aires",)),
    ("CABA", ("caba",)),
    ("Ciudad Autonoma de Buenos Aires", ("ciudad autonoma de buenos aires",)),
    ("La Plata", ("la plata",)),
    ("Tigre", ("tigre",)),
    ("Cordoba", ("cordoba",)),
    ("Rosario", ("rosario",)),
    ("Mendoza", ("mendoza",)),
    ("Santa Fe", ("santa fe",)),
    ("Bahia Blanca", ("bahia blanca",)),
    ("Neuquen", ("neuquen",)),
    ("Salta", ("salta",)),
    ("Tucuman", ("tucuman",)),
)

# Work-mode keyword catalogs (normalized text).
_REMOTE_KEYWORDS = (
    "remote", "remoto", "remota", "remotamente", "teletrabajo",
    "work from home", "home office", "trabajo remoto",
    "anywhere", "worldwide", "world wide", "work from anywhere",
)
_HYBRID_KEYWORDS = ("hybrid", "hibrido", "hibrida", "mixto", "mixed")
_ONSITE_KEYWORDS = (
    "onsite", "on site", "presencial", "in office", "in person",
    "face to face", "presencialidad",
)

# Regions that explicitly open a listing to the candidate's country. A listing
# mentioning any of these is open to Argentina even when its location anchor is
# a foreign city. Regions that EXCLUDE Argentina (US, EU, EMEA, APAC, ...) are
# deliberately absent here: they are treated as residence restrictions instead.
_OPENNESS_KEYWORDS = (
    "anywhere", "worldwide", "world wide", "global", "globally",
    "international", "remote first", "fully remote", "work from anywhere",
    "latam", "latin america", "america latina", "latinoamerica",
    "americas", "south america", "sudamerica", "any location", "any country",
)

# Tokens that turn a country word into part of a place name, e.g. the Uruguayan
# town "Villa Argentina" is not the country Argentina.
_PLACE_NAME_PREFIXES = ("villa",)


def _build_place_regexes() -> tuple[re.Pattern, re.Pattern, re.Pattern]:
    """Build (country, foreign-city, argentina-city) regexes over known aliases."""
    country_aliases = sorted(
        (alias for aliases in _COUNTRY_ALIASES.values() for alias in aliases),
        key=len,
        reverse=True,
    )
    city_aliases = sorted(
        (alias for _, _, aliases in _CITY_ENTRIES for alias in aliases),
        key=len,
        reverse=True,
    )
    arg_city_aliases = sorted(
        (alias for _, aliases in _ARGENTINA_CITIES for alias in aliases),
        key=len,
        reverse=True,
    )
    country_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(a) for a in country_aliases) + r")(?!\w)"
    )
    city_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(a) for a in city_aliases) + r")(?!\w)"
    )
    arg_city_pattern = re.compile(
        r"(?<!\w)(" + "|".join(re.escape(a) for a in arg_city_aliases) + r")(?!\w)"
    )
    return country_pattern, city_pattern, arg_city_pattern


_COUNTRY_REGEX, _CITY_REGEX, _ARG_CITY_REGEX = _build_place_regexes()

# alias -> canonical country (longest aliases resolved first by regex alternation)
_ALIAS_TO_COUNTRY: dict[str, str] = {
    alias: country
    for country, aliases in _COUNTRY_ALIASES.items()
    for alias in aliases
}
# alias -> (display, canonical country)
_ALIAS_TO_CITY: dict[str, tuple[str, str]] = {
    alias: (display, country)
    for display, country, aliases in _CITY_ENTRIES
    for alias in aliases
}
_ALIAS_TO_ARG_CITY: dict[str, str] = {
    alias: display for display, aliases in _ARGENTINA_CITIES for alias in aliases
}


def _canonical_country(name: Optional[str]) -> Optional[str]:
    """Resolve a user-provided country name to its canonical form."""
    normalized = _normalize(name)
    if not normalized:
        return None
    if normalized in _ALIAS_TO_COUNTRY:
        return _ALIAS_TO_COUNTRY[normalized]
    for canonical in _COUNTRY_ALIASES:
        if _normalize(canonical) == normalized:
            return canonical
    return normalized.title()


def _candidate_city_aliases(city: str) -> set[str]:
    """Aliases accepted as the candidate city, including MDP variants."""
    base = _normalize(city.split(",")[0] if city else "")
    aliases = {base} if base else set()
    if base == "mar del plata":
        aliases.update({"mdp", "general pueyrredon"})
    return {alias for alias in aliases if alias}


def _is_place_name_prefix(text: str, match_start: int) -> bool:
    """True when the match is preceded by a token that turns it into a place name."""
    before = text[:match_start].split()
    return bool(before) and before[-1] in _PLACE_NAME_PREFIXES


def _detect_countries(text: str) -> list[str]:
    """Canonical countries mentioned in the text, in order of appearance."""
    found: list[tuple[int, str]] = []
    for match in _COUNTRY_REGEX.finditer(text):
        if _is_place_name_prefix(text, match.start()):
            # "Villa Argentina" is a place name, not a country mention.
            continue
        country = _ALIAS_TO_COUNTRY.get(match.group(1))
        if country:
            found.append((match.start(), country))
    return _ordered_unique(found)


def _detect_cities(text: str) -> list[tuple[int, str, str]]:
    """Known cities in the text as (position, display, country)."""
    found: list[tuple[int, str, str]] = []
    for match in _CITY_REGEX.finditer(text):
        display, country = _ALIAS_TO_CITY[match.group(1)]
        found.append((match.start(), display, country))
    # Venezuela disambiguation: "Valencia" collides with Valencia, Spain.
    # Default to Spain; if Venezuelan context is present, attribute it there.
    if _has_any(text, ("venezuela", "caracas", "maracaibo")):
        found = [
            (pos, display, "Venezuela" if display == "Valencia" else country)
            for pos, display, country in found
        ]
    return found


def _detect_argentina_cities(text: str) -> list[tuple[int, str]]:
    """Known Argentine (non-candidate) cities in the text as (position, display)."""
    found: list[tuple[int, str]] = []
    for match in _ARG_CITY_REGEX.finditer(text):
        found.append((match.start(), _ALIAS_TO_ARG_CITY[match.group(1)]))
    return found


def _detect_candidate_city(text: str, aliases: set[str]) -> bool:
    return any(_contains_phrase(text, alias) for alias in aliases)


def _detect_city_display(text: str, candidate_aliases: set[str]) -> Optional[str]:
    """First recognized city display name in the text (candidate city or foreign)."""
    candidates: list[tuple[int, str]] = []
    for match in _CITY_REGEX.finditer(text):
        display, _ = _ALIAS_TO_CITY[match.group(1)]
        candidates.append((match.start(), display))
    for match in _ARG_CITY_REGEX.finditer(text):
        candidates.append((match.start(), _ALIAS_TO_ARG_CITY[match.group(1)]))
    for alias in candidate_aliases:
        idx = text.find(alias)
        if idx != -1:
            candidates.append((idx, "Mar del Plata" if alias in {"mdp", "general pueyrredon"} else alias.title()))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _ordered_unique(pairs: list[tuple[int, str]]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for _, value in sorted(pairs, key=lambda item: item[0]):
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _has_known_city(text: str, candidate_aliases: set[str]) -> bool:
    if _CITY_REGEX.search(text):
        return True
    if _ARG_CITY_REGEX.search(text):
        return True
    return _detect_candidate_city(text, candidate_aliases)


# --- Residence restriction detection ---------------------------------------

# Bounded surface forms for a bare "US", which is deliberately NOT a generic
# country alias (so "join us", "Indianapolis", "Ukulele" never match). Each
# pattern requires a restriction context: a remote qualifier, "only", a
# residence verb, or "within the US".
_US_RESTRICTION_PATTERNS = (
    re.compile(r"\bremote\s*\(\s*(?:us|u s|usa)\s*\)"),
    re.compile(r"\bremote\s*,\s*(?:us|u s|usa)\b"),
    re.compile(r"\b(?:us|u s|usa)\s+remote\b"),
    re.compile(r"\bremote\s+within\s+(?:the\s+)?(?:us|u s|usa)\b"),
    re.compile(rf"\bremote\s+(?:only\s+)?(?:from\s+|in\s+|for\s+|at\s+)?(?:the\s+)?(?:us|u s|usa)\b"),
    re.compile(r"\bwithin\s+(?:the\s+)?(?:us|usa)\b"),
    re.compile(r"\b(?:us|u s|usa)\s+only\b"),
    re.compile(r"\bonly\s+(?:us|u s|usa)\b"),
    re.compile(
        rf"\b(?:must|should|need(?:s)?\s+to)\s+(?:reside|live|be\s+based)\s+in\s+"
        rf"(?:the\s+)?(?:us|u s|usa|united states)\b"
    ),
    re.compile(rf"\b(?:candidates?|applicants?|developers?|employees?)\s+(?:must\s+)?"
               rf"(?:reside|live|be\s+based)\s+in\s+(?:the\s+)?(?:us|u s|usa|united states)\b"),
)

# "EU only" style restrictions are foreign regions, not named countries.
_EU_RESTRICTION_PATTERNS = (
    re.compile(r"\bremote\s*\(\s*(?:eu|europe|european union)\s*\)"),
    re.compile(r"\bremote\s*,\s*(?:eu|europe)\b"),
    re.compile(r"\bremote\s+within\s+(?:the\s+)?(?:eu|europe|european union)\b"),
    re.compile(rf"\bremote\s+(?:only\s+)?(?:from\s+|in\s+|for\s+|at\s+)?(?:the\s+)?(?:eu|europe|european union)\b"),
    re.compile(r"\bwithin\s+(?:the\s+)?(?:eu|europe|european union)\b"),
    re.compile(r"\b(?:eu|europe|european union)\s+only\b"),
    re.compile(r"\bonly\s+(?:eu|europe|european union)\b"),
    re.compile(
        rf"\b(?:must|should|need(?:s)?\s+to)\s+(?:reside|live|be\s+based)\s+in\s+"
        rf"(?:the\s+)?(?:eu|europe|european union)\b"
    ),
)

# Other foreign regions that exclude Argentina and name no country.
_REGION_RESTRICTION_PATTERNS = (
    re.compile(r"\bremote\s*\(\s*(?:emea|apac)\s*\)"),
    re.compile(r"\bremote\s*,\s*(?:emea|apac)\b"),
    re.compile(r"\bremote\s+within\s+(?:the\s+)?(?:emea|apac)\b"),
    re.compile(r"\bremote\s+(?:only\s+)?(?:from\s+|in\s+|for\s+|at\s+)?(?:the\s+)?(?:emea|apac)\b"),
    re.compile(r"\bwithin\s+(?:the\s+)?(?:emea|apac)\b"),
    re.compile(r"\b(?:emea|apac)\s+only\b"),
    re.compile(r"\bonly\s+(?:emea|apac)\b"),
)

_REGION_TO_COUNTRY = {
    "eu": "European Union",
    "europe": "European Union",
    "european union": "European Union",
    "emea": "EMEA",
    "apac": "APAC",
}


def _build_restriction_patterns() -> list[re.Pattern]:
    country = "(?:" + "|".join(
        re.escape(a)
        for a in sorted(
            (alias for aliases in _COUNTRY_ALIASES.values() for alias in aliases),
            key=len,
            reverse=True,
        )
    ) + ")"
    city = "(?:" + "|".join(
        re.escape(a)
        for a in sorted(
            (
                alias
                for entries in (_CITY_ENTRIES, _ARGENTINA_CITIES)
                for entry in entries
                for alias in entry[-1]
            ),
            key=len,
            reverse=True,
        )
    ) + ")"
    place = f"(?P<place>{country}|{city})"
    return [
        re.compile(rf"\bremote\s+(?:only\s+)?(?:from\s+|in\s+|for\s+|at\s+)?{place}\b"),
        re.compile(rf"\bremoto\s+(?:solo\s+)?(?:desde\s+|en\s+|para\s+)?{place}\b"),
        re.compile(rf"\b{place}\s+only\b"),
        re.compile(rf"\bonly\s+(?:for\s+|from\s+|in\s+)?{place}\b"),
        re.compile(
            rf"\b(?:must|should|need(?:s)?\s+to)\s+(?:reside|live|be\s+based)\s+in\s+{place}\b"
        ),
        re.compile(rf"\b(?:residing|residence|located|based)\s+in\s+{place}\b"),
        re.compile(rf"\b(?:candidates?|applicants?|developers?)\s+from\s+{place}\b"),
        re.compile(
            rf"\b(?:solo|exclusivo|exclusivamente|unicamente)\s+(?:para\s+|en\s+|desde\s+)?{place}\b"
        ),
        re.compile(rf"\b{place}\s+(?:residents?|based)\b"),
    ]


_RESTRICTION_PATTERNS = _build_restriction_patterns()


def _place_to_country(raw: str) -> Optional[str]:
    normalized = _normalize(raw)
    if normalized in _ALIAS_TO_COUNTRY:
        return _ALIAS_TO_COUNTRY[normalized]
    if normalized in _ALIAS_TO_CITY:
        return _ALIAS_TO_CITY[normalized][1]
    if normalized in _ALIAS_TO_ARG_CITY:
        return "Argentina"
    if normalized in _REGION_TO_COUNTRY:
        return _REGION_TO_COUNTRY[normalized]
    if normalized in ("us", "u s"):
        return "United States"
    return None


def _find_residence_restriction(text: str) -> Optional[str]:
    """
    Return the place named as a residence requirement, or None.

    Explicit openness keywords do NOT suppress a restriction: the classify flow
    gives an explicit residence requirement precedence over openness.
    """
    if not text:
        return None
    for pattern in _US_RESTRICTION_PATTERNS:
        if pattern.search(text):
            return "United States"
    for pattern in _EU_RESTRICTION_PATTERNS:
        if pattern.search(text):
            return "European Union"
    for pattern in _REGION_RESTRICTION_PATTERNS:
        if pattern.search(text):
            return "EMEA" if "emea" in pattern.pattern else "APAC"
    for pattern in _RESTRICTION_PATTERNS:
        match = pattern.search(text)
        if match:
            country = _place_to_country(match.group("place"))
            if country:
                return country
    return None


def _country_from_location(location_norm: str) -> Optional[str]:
    """
    Resolve the country from the structured location field.

    Job feeds conventionally put the country in the last comma-separated
    component, so "Villa Argentina, Canelones, Uruguay" resolves to Uruguay and
    the place name "Villa Argentina" never counts as the country. Returning None
    lets the caller fall back to scanning the wider anchor text.
    """
    if not location_norm:
        return None
    parts = [part.strip() for part in location_norm.split(",") if part.strip()]
    if not parts:
        return None
    countries = _detect_countries(parts[-1])
    return countries[0] if countries else None


def _has_openness(text: str) -> bool:
    """True when the listing explicitly opens itself to the candidate's region."""
    return _has_any(text, _OPENNESS_KEYWORDS)


# --- Main entry point -------------------------------------------------------

def classify_location(
    location: Optional[str],
    is_remote: bool = False,
    modality: Optional[str] = None,
    title: str = "",
    description: str = "",
    candidate_city: str = "Mar del Plata",
    candidate_country: str = "Argentina",
    allow_remote: bool = True,
    block_foreign_restricted_remote: bool = True,
) -> LocationVerdict:
    """
    Classify a listing as geographically eligible or blocked.

    Precedence: work mode, then an explicit residence requirement (which wins
    over any openness wording), then explicit openness to a region that includes
    the candidate's country, then the location anchor as the conservative
    default.

    Remote detection is text-first. The JobSpy ``is_remote`` flag is unreliable
    in production data (Barcelona listings arrive flagged remote), but it is
    still accepted on its own when there is no location text, because several
    legitimate remote listings ship with an empty location.
    """
    loc_norm = _normalize(location)
    title_norm = _normalize(title)
    desc_norm = _normalize(description)
    mod_norm = _normalize(modality)
    anchor = _normalize(f"{loc_norm} {title_norm}")
    full = _normalize(f"{loc_norm} {title_norm} {desc_norm}")

    candidate_country_name = _canonical_country(candidate_country) or _normalize(candidate_country)
    candidate_aliases = _candidate_city_aliases(candidate_city)
    in_candidate_city = _detect_candidate_city(anchor, candidate_aliases)

    # Work mode detection.
    remote_text = (
        _has_any(anchor, _REMOTE_KEYWORDS)
        or _has_any(mod_norm, _REMOTE_KEYWORDS)
        or _has_any(desc_norm, _REMOTE_KEYWORDS)
    )
    hybrid_text = _has_any(full, _HYBRID_KEYWORDS) or _has_any(mod_norm, _HYBRID_KEYWORDS)
    onsite_text = _has_any(full, _ONSITE_KEYWORDS) or _has_any(mod_norm, _ONSITE_KEYWORDS)

    if hybrid_text:
        work_mode = WorkMode.HYBRID
    elif remote_text or is_remote:
        work_mode = WorkMode.REMOTE
    elif onsite_text:
        work_mode = WorkMode.ONSITE
    elif loc_norm and _has_known_city(loc_norm, candidate_aliases):
        work_mode = WorkMode.ONSITE
    else:
        work_mode = WorkMode.UNKNOWN

    # Place detection. The structured location's country wins over title text so
    # a place name such as "Villa Argentina" cannot be mistaken for Argentina.
    country = _country_from_location(loc_norm)
    if country is None:
        anchor_countries = _detect_countries(anchor)
        anchor_countries.extend(
            found for _, _, found in _detect_cities(anchor) if found not in anchor_countries
        )
        country = anchor_countries[0] if anchor_countries else None
    arg_cities = [display for _, display in _detect_argentina_cities(anchor)]
    if country is None and arg_cities:
        country = "Argentina"
    city = _detect_city_display(anchor, candidate_aliases)
    if in_candidate_city:
        city = "Mar del Plata"

    openness = _has_openness(full)
    restriction = _find_residence_restriction(full)
    effective_country = country or restriction
    foreign_restriction = (
        restriction is not None and restriction != candidate_country_name
    )
    is_foreign = effective_country is not None and effective_country != candidate_country_name

    # 1. Remote disabled by configuration.
    if work_mode == WorkMode.REMOTE and not allow_remote:
        return LocationVerdict(
            eligible=False,
            reason=REASON_REMOTE_DISABLED,
            work_mode=work_mode.value,
            country=effective_country,
            city=city,
            human_reason="Remote work is disabled by policy (ALLOW_REMOTE=false).",
        )

    # 2. Explicit residence requirement wins over any openness wording.
    if block_foreign_restricted_remote and foreign_restriction:
        return LocationVerdict(
            eligible=False,
            reason=REASON_REMOTE_FOREIGN_RESTRICTED,
            work_mode=work_mode.value,
            country=effective_country,
            city=city,
            human_reason=(
                f"Listing requires residence in {restriction}, which is outside the "
                f"candidate's country ({candidate_country_name})."
            ),
        )

    # 3. Candidate city: on-site, hybrid, and remote are all acceptable locally.
    if in_candidate_city:
        reason = REASON_REMOTE_OK if work_mode == WorkMode.REMOTE else REASON_ONSITE_CANDIDATE_CITY
        return LocationVerdict(
            eligible=True,
            reason=reason,
            work_mode=work_mode.value,
            country=effective_country,
            city="Mar del Plata",
            human_reason=f"Job is in the candidate city ({candidate_city}) or remote.",
        )

    # 4. Candidate country, but a different city.
    if effective_country == candidate_country_name:
        if work_mode == WorkMode.REMOTE:
            return LocationVerdict(
                eligible=True,
                reason=REASON_REMOTE_OK,
                work_mode=work_mode.value,
                country=effective_country,
                city=city,
                human_reason="Remote job in the candidate's country.",
            )
        return LocationVerdict(
            eligible=False,
            reason=REASON_ONSITE_OTHER_ARGENTINA,
            work_mode=work_mode.value,
            country=effective_country,
            city=city,
            human_reason=(
                "On-site or hybrid job in another Argentine city; only Mar del Plata "
                "is acceptable on-site."
            ),
        )

    # 5. Foreign country anchored in the location. Explicit openness to a region
    #    that includes Argentina overrides the foreign anchor for remote roles.
    if is_foreign:
        if work_mode == WorkMode.REMOTE:
            if openness:
                return LocationVerdict(
                    eligible=True,
                    reason=REASON_REMOTE_OK,
                    work_mode=work_mode.value,
                    country=effective_country,
                    city=city,
                    human_reason=(
                        f"Remote listing anchored in {effective_country} but explicitly "
                        "open to the candidate's region."
                    ),
                )
            if block_foreign_restricted_remote:
                return LocationVerdict(
                    eligible=False,
                    reason=REASON_REMOTE_FOREIGN_RESTRICTED,
                    work_mode=work_mode.value,
                    country=effective_country,
                    city=city,
                    human_reason=(
                        f"Remote listing is anchored in {effective_country}, which implies a "
                        "foreign residence requirement."
                    ),
                )
            return LocationVerdict(
                eligible=True,
                reason=REASON_REMOTE_OK,
                work_mode=work_mode.value,
                country=effective_country,
                city=city,
                human_reason="Remote job; foreign residence restrictions are not enforced.",
            )
        if work_mode in (WorkMode.ONSITE, WorkMode.HYBRID):
            return LocationVerdict(
                eligible=False,
                reason=REASON_ONSITE_FOREIGN,
                work_mode=work_mode.value,
                country=effective_country,
                city=city,
                human_reason=(
                    f"On-site or hybrid job in {effective_country}; only Mar del Plata is "
                    "acceptable on-site."
                ),
            )
        return LocationVerdict(
            eligible=False,
            reason=REASON_UNKNOWN_WORK_MODE_FOREIGN,
            work_mode=work_mode.value,
            country=effective_country,
            city=city,
            human_reason=(
                f"Foreign location ({effective_country}) with an undetermined work mode."
            ),
        )

    # 6. No recognized country.
    if work_mode == WorkMode.REMOTE:
        return LocationVerdict(
            eligible=True,
            reason=REASON_REMOTE_OK,
            work_mode=work_mode.value,
            country=None,
            city=city,
            human_reason="Remote listing with no foreign residence restriction.",
        )
    return LocationVerdict(
        eligible=False,
        reason=REASON_UNKNOWN_LOCATION,
        work_mode=work_mode.value,
        country=effective_country,
        city=city,
        human_reason="Location and work mode could not be determined; failing closed.",
    )


def is_notifiable(
    location_eligible: bool,
    match_score: Optional[int],
    min_match_score: int = 70,
) -> bool:
    """
    Pure notification gate.

    A job may be notified only when it passed the location policy AND reached the
    minimum AI match score. ``is_suitable`` is intentionally not part of this
    predicate, so it can never bypass the threshold.
    """
    return (
        bool(location_eligible)
        and match_score is not None
        and match_score >= min_match_score
    )
