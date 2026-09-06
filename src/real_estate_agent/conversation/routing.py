"""Deterministic replies for social messages that do not require RAG."""

from __future__ import annotations

import re
import unicodedata


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
    "je vous remercie",
    "thanks",
    "thank you",
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


def local_conversation_reply(message: str) -> str | None:
    """Return a friendly local answer, or ``None`` when RAG should handle it."""
    normalized = _normalize(message)
    if normalized in _GREETINGS or normalized in {"ca va", "comment allez vous"}:
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
    return None
