# Gemini Folder RAG

Folder-based RAG using Gemini File Search and Gemini 3.5 Flash-Lite.

## Setup

1. Create a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env`:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

4. Edit `config.py` and set:

```python
DOCUMENT_FOLDER = Path(r"D:\MyDocuments\RAG_Files")
```

5. Index the folder:

```bash
python ingest.py
```

6. Start the API:

```bash
python app.py
```

## Query

POST JSON to:

`http://127.0.0.1:5000/query`

```json
{
  "question": "What does the documentation say about authentication?"
}
```

## Large collections

The indexer uses concurrent uploads with `MAX_WORKERS = 10` and automatic retries.

If you hit rate limits, reduce `MAX_WORKERS` to 5 or lower.
