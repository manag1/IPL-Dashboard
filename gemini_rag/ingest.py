import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    DOCUMENT_FOLDER,
    IGNORED_EXTENSIONS,
    IGNORED_DIRECTORIES,
    MAX_RETRIES,
    MAX_WORKERS,
    RETRY_BASE_SECONDS,
)
from database import (
    initialize_database,
    get_file,
    save_file,
)
from rag import get_or_create_store, upload_file


def sha256(path):
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(chunk)

    return digest.hexdigest()


def ignored(path):
    if path.suffix.lower() in IGNORED_EXTENSIONS:
        return True

    return any(
        part in IGNORED_DIRECTORIES
        for part in path.parts
    )


def find_files():
    if not DOCUMENT_FOLDER.exists():
        raise FileNotFoundError(
            f"Document folder does not exist: {DOCUMENT_FOLDER}"
        )

    if not DOCUMENT_FOLDER.is_dir():
        raise NotADirectoryError(
            f"Document path is not a directory: {DOCUMENT_FOLDER}"
        )

    return [
        path.resolve()
        for path in DOCUMENT_FOLDER.rglob("*")
        if path.is_file() and not ignored(path)
    ]


def prepare_file(path):
    stat = path.stat()
    file_hash = sha256(path)
    existing = get_file(path)

    if (
        existing
        and existing["file_hash"] == file_hash
        and existing["status"] == "indexed"
    ):
        return None

    return {
        "path": path,
        "hash": file_hash,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }


def index_one(item, store_name):
    path = item["path"]

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = upload_file(path, store_name)
            gemini_name = getattr(result, "name", None) if result else None

            save_file(
                path=path,
                name=path.name,
                h=item["hash"],
                size=item["size"],
                mtime=item["mtime"],
                gemini=gemini_name,
                status="indexed",
                error=None,
            )

            return {
                "status": "indexed",
                "path": str(path),
                "error": None,
            }

        except Exception as exc:
            last_error = str(exc)

            if attempt < MAX_RETRIES:
                delay = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
                time.sleep(delay)

    save_file(
        path=path,
        name=path.name,
        h=item["hash"],
        size=item["size"],
        mtime=item["mtime"],
        status="failed",
        error=last_error,
    )

    return {
        "status": "failed",
        "path": str(path),
        "error": last_error,
    }


def main():
    print("=" * 70)
    print("GEMINI RAG INDEXER")
    print("=" * 70)
    print(f"Folder      : {DOCUMENT_FOLDER}")
    print(f"Workers     : {MAX_WORKERS}")
    print(f"Max retries : {MAX_RETRIES}")
    print()

    initialize_database()
    store = get_or_create_store()
    store_name = store.name

    files = find_files()

    print(f"Found {len(files)} files.")
    print("Calculating hashes...")

    pending = []
    unchanged = 0

    for path in files:
        try:
            item = prepare_file(path)

            if item is None:
                unchanged += 1
            else:
                pending.append(item)

        except Exception as exc:
            print(f"FAILED TO READ: {path} -> {exc}")

    print(f"Unchanged : {unchanged}")
    print(f"To index  : {len(pending)}")
    print()

    if not pending:
        print("Nothing to index.")
        return

    indexed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(index_one, item, store_name): item
            for item in pending
        }

        total = len(futures)

        for completed, future in enumerate(
            as_completed(futures),
            start=1,
        ):
            result = future.result()

            if result["status"] == "indexed":
                indexed += 1
                print(
                    f"[{completed}/{total}] INDEXED: "
                    f"{result['path']}"
                )
            else:
                failed += 1
                print(
                    f"[{completed}/{total}] FAILED: "
                    f"{result['path']} -> {result['error']}"
                )

    print()
    print("=" * 70)
    print("INDEXING COMPLETE")
    print("=" * 70)
    print(f"Indexed/updated : {indexed}")
    print(f"Unchanged       : {unchanged}")
    print(f"Failed          : {failed}")
    print(f"Workers used    : {MAX_WORKERS}")
    print(f"Store           : {store_name}")


if __name__ == "__main__":
    main()
