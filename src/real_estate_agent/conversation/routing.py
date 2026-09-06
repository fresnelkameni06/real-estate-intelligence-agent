"""Deterministic replies for social messages that do not require RAG."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from difflib import SequenceMatcher


def _normalize(message: str) -> str:
    decomposed = unicodedata.normalize("NFKD", message.casefold())
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    words_only = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return " ".join(words_only.split())


_GREETINGS = {
    "bonjour",
    "bonjour a vous",
    "bonjour comment allez vous",
    "bonsoir",
    "coucou",
    "hello",
    "hey",
    "salut",
    "salut ca va",
}
_THANKS = {
    "merci",
    "merci a vous",
    "merci beaucoup",
    "merci pour ton aide",
    "merci pour votre aide",
    "merci c est clair",
    "je vous remercie",
    "thanks",
    "thanks for your help",
    "thank you",
    "thank you for your help",
}
_ACKNOWLEDGEMENTS = {
    "c est bon",
    "c est ok",
    "ca marche",
    "compris",
    "d accord",
    "ok",
    "okay",
    "parfait",
    "tres bien",
}
_GOODBYES = {
    "a bientot",
    "a plus",
    "au revoir",
    "bonne journee",
    "bonne soiree",
}
_CAPABILITY_QUESTIONS = {
    "a quoi sers tu",
    "que peux tu faire",
    "qui es tu",
    "tu es qui",
    "tu peux faire quoi",
}

_REAL_ESTATE_MARKERS = (
    "achat",
    "acheter",
    "agence immobiliere",
    "agent immobilier",
    "appartement",
    "apartment",
    "arrondissement",
    "audit energetique",
    "bail",
    "bien immobilier",
    "building",
    "buy",
    "charges",
    "copropriete",
    "credit immobilier",
    "diagnostic",
    "dpe",
    "dvf",
    "emprunt",
    "energy rating",
    "energy performance",
    "frais de notaire",
    "home",
    "housing",
    "house",
    "immeuble",
    "immobilier",
    "immobiliere",
    "immobilieres",
    "immobiliers",
    "investissement",
    "landlord",
    "location",
    "locataire",
    "locatif",
    "logement",
    "loyer",
    "m2",
    "maison",
    "marche residentiel",
    "median",
    "mediane",
    "metre carre",
    "mortgage",
    "neighborhood",
    "notaire",
    "prix",
    "property",
    "property tax",
    "proprietaire",
    "quartier",
    "real estate",
    "rent",
    "rendement",
    "renovation",
    "sale",
    "studio",
    "surface",
    "taxe fonciere",
    "tenant",
    "transaction",
    "travaux",
    "valeur fonciere",
    "vente",
)
_SECURITY_PATTERNS = (
    r"ignore .*instruction",
    r"instructions? (systeme|system)",
    r"system prompt",
    r"api key",
    r"cle api",
    r"mot de passe",
    r"password",
    r"drop table",
    r"delete from",
    r"execute .*sql",
    r"revele .*secret",
    r"affiche .*secret",
    r"(?:montre|affiche|revele|donne).*"
    r"(?:instruction|prompt|secret|cle api|mot de passe|password|token)",
    r"(?:select|insert|update|delete|drop|alter|truncate|create).*"
    r"(?:from|into|table|database|schema)",
)
_CURRENT_TIME_PATTERNS = (
    r"quel(?:le)? heure",
    r"heure (?:a|de|en) paris",
    r"heure paris",
    r"heure est il",
    r"heure actuelle",
    r"heure maintenant",
    r"il est quelle heure",
    r"quel jour sommes nous",
    r"quelle date sommes nous",
    r"sommes nous en ete",
    r"sommes nous en hiver",
    r"saison sommes nous",
)
_WEATHER_MARKERS = (
    "meteo",
    "neiger",
    "neige demain",
    "pleuvoir",
    "pluie demain",
    "prevision du temps",
    "temperature demain",
    "temps demain",
    "weather",
)
_LOCATION_PATTERNS = (
    r"dans quelle ville suis je",
    r"ou suis je",
    r"ma position actuelle",
    r"ma localisation",
    r"mon gps",
)
_FOLLOWUP_PREFIXES = (
    "alors",
    "continue",
    "detaille",
    "et ",
    "explique",
    "mais",
    "non",
    "oui",
    "pourquoi",
    "precise",
    "vas y",
    "allez y",
)

_RESPONSE_INSTRUCTION_MARKERS = (
    "answer",
    "brief",
    "court",
    "detail",
    "explain",
    "please",
    "repond",
    "reply",
    "resume",
    "tradui",
)
_RESPONSE_LANGUAGE_MARKERS = (
    "anglais",
    "english",
    "francais",
    "french",
)

_PARIS_CLARIFICATION_PATTERNS = (
    r"(?:a )?paris",
    r"(?:la )?ville (?:c est|est) paris",
    r"ville paris",
    r"(?:c est|ce sera|je choisis|je veux) paris",
    r"paris (?:entier|intra muros)",
)

_OUT_OF_SCOPE_REPLY = (
    "Je suis spécialisé dans l’analyse immobilière résidentielle à Paris. "
    "Je peux vous aider sur les prix, les transactions DVF, les arrondissements, "
    "le DPE et la réglementation immobilière associée."
)


def _contains_real_estate_context(message: str) -> bool:
    normalized = _normalize(message)
    if any(
        re.search(rf"\b{re.escape(marker)}\b", normalized)
        for marker in _REAL_ESTATE_MARKERS
    ):
        return True
    return bool(re.search(r"\b(?:[1-9]|1[0-9]|20)(?:e|eme|er)\b", normalized))


def _is_paris_clarification(message: str) -> bool:
    normalized = _normalize(message)
    return any(
        re.fullmatch(pattern, normalized)
        for pattern in _PARIS_CLARIFICATION_PATTERNS
    )


def _is_short_social_typo(normalized: str, candidates: set[str]) -> bool:
    if len(normalized.split()) != 1 or len(normalized) < 4:
        return False
    return any(
        " " not in candidate
        and SequenceMatcher(None, normalized, candidate).ratio() >= 0.82
        for candidate in candidates
    )


def _is_contextual_followup(message: str) -> bool:
    normalized = _normalize(message)
    if len(normalized.split()) > 12:
        return False
    return _is_paris_clarification(message) or normalized.startswith(
        _FOLLOWUP_PREFIXES
    ) or bool(
        re.search(r"\b(?:[1-9]|1[0-9]|20)(?:e|eme|er)\b", normalized)
    )


def _is_response_instruction(message: str) -> bool:
    """Recognize short requests that change language, length or answer style."""
    normalized = _normalize(message)
    if len(normalized.split()) > 12:
        return False
    tokens = normalized.split()
    has_language = any(
        SequenceMatcher(None, token, language).ratio() >= 0.8
        for token in tokens
        for language in _RESPONSE_LANGUAGE_MARKERS
    )
    has_instruction = any(
        marker in normalized for marker in _RESPONSE_INSTRUCTION_MARKERS
    )
    return has_language and has_instruction


def local_conversation_reply(
    message: str,
    *,
    history: Sequence[str] = (),
) -> str | None:
    """Handle social, unsupported and out-of-scope requests before the model."""
    normalized = _normalize(message)
    if any(re.search(pattern, normalized) for pattern in _SECURITY_PATTERNS):
        return (
            "Je ne peux pas ignorer mes règles de sécurité, révéler des secrets, "
            "exécuter du SQL libre ou utiliser un outil non autorisé. Je peux en "
            "revanche vous aider avec une analyse immobilière agrégée et sécurisée."
        )
    if any(re.search(pattern, normalized) for pattern in _CURRENT_TIME_PATTERNS):
        return (
            "Je n’ai pas accès à une horloge en temps réel. Je suis spécialisé dans "
            "l’analyse immobilière parisienne et je préfère ne pas inventer une "
            "heure, une date ou une saison actuelle."
        )
    if any(marker in normalized for marker in _WEATHER_MARKERS):
        return (
            "Je n’ai pas accès aux prévisions météorologiques en temps réel. "
            "Consultez Météo-France pour la météo ; je peux analyser le marché "
            "immobilier parisien, le DPE et la réglementation associée."
        )
    if any(re.search(pattern, normalized) for pattern in _LOCATION_PATTERNS):
        return (
            "Je n’ai accès ni à votre position, ni à votre GPS, ni à votre adresse. "
            "Je peux uniquement vous accompagner sur l’immobilier résidentiel parisien."
        )
    if (
        normalized in _GREETINGS
        or normalized in {"ca va", "comment allez vous"}
        or _is_short_social_typo(normalized, _GREETINGS)
    ):
        return (
            "Bonjour 👋 Je vais bien, merci ! Je peux répondre à vos questions "
            "sur le DPE, la réglementation énergétique, les audits et les données DVF."
        )
    if normalized in _THANKS:
        return "Avec plaisir ! N’hésitez pas à poser une autre question immobilière."
    if normalized in _ACKNOWLEDGEMENTS:
        return "Parfait 👍 Je suis prêt pour votre prochaine question."
    if normalized in _GOODBYES:
        return "Au revoir 👋 À bientôt pour une nouvelle analyse immobilière."
    if normalized in _CAPABILITY_QUESTIONS:
        return (
            "Je suis l’Analyste IA immobilier de Paris. Je peux analyser les prix, "
            "les volumes, les tendances et les arrondissements avec les données "
            "PostgreSQL, étudier les statistiques DPE et répondre aux questions "
            "réglementaires à partir de sources officielles."
        )
    if _contains_real_estate_context(message):
        return None
    if (
        _is_contextual_followup(message)
        and history
        and (
            _contains_real_estate_context(history[-1])
            or _is_paris_clarification(history[-1])
        )
    ):
        return None
    if (
        _is_response_instruction(message)
        and history
        and _contains_real_estate_context(history[-1])
    ):
        return None
    if _is_paris_clarification(message):
        return (
            "Vous avez indiqué Paris. Que souhaitez-vous analyser : le marché "
            "global, un arrondissement, les prix, les transactions ou le DPE ?"
        )
    return _OUT_OF_SCOPE_REPLY
