from llama_index.core.llms import ChatMessage

from app.rag.prompts import build_classifier_prompt, parse_intent


def classify(message: str, llm) -> dict:
    """Ask the LLM for the intent. Returns {"intent", "confidence", "urgent"}."""
    response = llm.chat(
        [
            ChatMessage(role="system", content=build_classifier_prompt()),
            ChatMessage(role="user", content=message),
        ]
    )
    return parse_intent(response.message.content)
