"""Response construction from already-loaded records (no database access)."""


def thread_dict(thread):
    return dict(
        id=thread.id,
        title=thread.title,
        status=thread.status,
        head_id=thread.head_id,
        createdAt=thread.created_at,
    )


def run_dict(run):
    return dict(
        id=run.id,
        thread_id=run.thread_id,
        user_message_id=run.user_message_id,
        assistant_message_id=run.assistant_message_id,
        status=run.status,
        error=run.error,
    )


def message_dict(message, sources):
    return dict(
        id=message.id,
        parent_id=message.parent_id,
        role=message.role,
        text=message.text,
        status=message.status,
        createdAt=message.created_at,
        citations=[
            dict(
                doc_id=c.doc_id,
                chunk_id=c.doc_chunk_id,
                version_id=v.id,
                file_name=v.file_name,
                folder=c.company,
                source_url=f"/v1/documents/{c.doc_id}/versions/{v.id}/source",
                provenance=c.provenance,
            )
            for _, c, v in sources
        ],
    )
