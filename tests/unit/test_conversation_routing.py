"""Tests for inexpensive social-message routing before documentary RAG."""

from real_estate_agent.conversation import local_conversation_reply


def test_common_social_messages_receive_friendly_replies():
    assert "Bonjour" in local_conversation_reply("bonjour")
    assert "plaisir" in local_conversation_reply("Merci beaucoup !")
    assert "prêt" in local_conversation_reply("C'est OK.")
    assert "Au revoir" in local_conversation_reply("Au revoir")


def test_capability_question_explains_current_agent_scope():
    answer = local_conversation_reply("Tu peux faire quoi ?")
    assert answer is not None
    assert "DPE" in answer
    assert "PostgreSQL" in answer
    assert "arrondissements" in answer


def test_documentary_question_is_left_to_rag():
    assert local_conversation_reply("Combien de temps un DPE est-il valable ?") is None
