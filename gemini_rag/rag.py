import time

from google import genai

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    STORE_DISPLAY_NAME,
    STORE_CONFIG_FILE,
)


client = genai.Client(api_key=GEMINI_API_KEY)


def get_or_create_store():
    if STORE_CONFIG_FILE.exists():
        name = STORE_CONFIG_FILE.read_text(encoding="utf-8").strip()

        if name:
            try:
                return client.file_search_stores.get(name=name)
            except Exception:
                pass

    store = client.file_search_stores.create(
        config={
            "display_name": STORE_DISPLAY_NAME,
            "embedding_model": "models/gemini-embedding-2",
        }
    )

    STORE_CONFIG_FILE.write_text(
        store.name,
        encoding="utf-8",
    )

    return store


def upload_file(path, store_name):
    operation = client.file_search_stores.upload_to_file_search_store(
        file=str(path),
        file_search_store_name=store_name,
        config={
            "display_name": path.name,
        },
    )

    while not operation.done:
        time.sleep(2)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise RuntimeError(str(operation.error))

    return getattr(operation, "response", None)


def query_rag(question, store_name):
    prompt = f"""
You are a document-grounded assistant.

Answer the user's question using the documents retrieved from the
File Search knowledge base.

Rules:
1. Prefer information from the retrieved documents.
2. Do not invent facts.
3. If the answer is not found, clearly say so.
4. Mention relevant source documents when useful.
5. Combine information from multiple documents carefully.
6. Perform calculations carefully when the question requires them.

Question:
{question}
"""

    interaction = client.interactions.create(
        model=GEMINI_MODEL,
        input=prompt,
        tools=[
            {
                "type": "file_search",
                "file_search_store_names": [store_name],
            }
        ],
    )

    text = []
    citations = []

    for step in getattr(interaction, "steps", []):
        if getattr(step, "type", None) != "model_output":
            continue

        for block in getattr(step, "content", []):
            if getattr(block, "type", None) != "text":
                continue

            if getattr(block, "text", None):
                text.append(block.text)

            for annotation in getattr(block, "annotations", None) or []:
                if hasattr(annotation, "model_dump"):
                    citations.append(annotation.model_dump())
                else:
                    citations.append(str(annotation))

    if not text and getattr(interaction, "output_text", None):
        text = [interaction.output_text]

    return {
        "answer": "\n".join(text).strip(),
        "citations": citations,
    }
