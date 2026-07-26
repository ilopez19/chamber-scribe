# Shared helper for turning a MongoDB document into a JSON-safe dict.
# Every list/get route needs the same conversion (Mongo's _id -> a plain
# "id" string) — one function here instead of near-identical copies in
# jobs.py/transcripts.py/tasks.py. Job/Transcript/Task documents are plain
# dicts with no fixed schema, so this stays simple: rename the field,
# return everything else untouched.


# Returns a copy of doc with _id replaced by a string "id" field.
def serialize_document(doc: dict) -> dict:
    result = dict(doc)
    result["id"] = str(result.pop("_id"))
    return result
