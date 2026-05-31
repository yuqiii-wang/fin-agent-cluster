"""do_emb — NodeTask: generate embeddings for raw news articles from get_news output.

Runs in parallel with ``do_summary``.  Receives the raw ``news_articles`` list from
``get_news`` and generates a 768-dim vector embedding of ``title + content`` for each
article, keyed by ``url_hash`` (sha256 of the article URL or title).

Failure behaviour
-----------------
Per-item embedding failure → warning logged, item skipped.
Embedder init failure → warning logged, empty embeddings returned.
The task always completes as ``completed``; it is a soft-failure task.
Delegation failures (Celery infrastructure down) propagate to seq.py for
warning-level handling there.

Execution layers
----------------
LangGraph layer (``_do_emb_task`` decorated with ``@task``):
    Delegates to the Celery completion worker.

Celery layer (``_handler``):
    For each article: sha256 url/title → embed ``title + content`` via
    ``embedder.embed_documents([text])``.  Catches per-item exceptions.

Public exports
--------------
``do_emb``   — ``NodeTask`` instance.
``HANDLERS`` — dict slice for registration in ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from langgraph.func import task
from pydantic import BaseModel, Field

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_news import NewsStatsSQL
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    NEWS_TASK_EMBED_ERROR,
    NEWS_TASK_EMB_WARN,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask
from backend.llm.factory import get_embedder

logger = logging.getLogger(__name__)

_TASK_NAME = "do_emb"


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class DoEmbInput(BaseModel):
    """Input for the do_emb task.

    Attributes:
        input_raw_id:   FK to the ``input_raw`` row (for provenance tracking).
        news_articles:  Raw article dicts from ``get_news`` output.  Each dict
                        must contain at minimum a ``title`` field; ``url`` and
                        ``content`` are used when present.  When empty the
                        handler returns immediately with empty embeddings.
    """

    input_raw_id: int | None = Field(default=None, description="FK to input_raw row.")
    news_articles: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Raw article dicts from get_news output.",
    )


class DoEmbOutput(BaseModel):
    """Output from the do_emb task.

    Attributes:
        embeddings:    Mapping of ``url_hash`` → 768-dim embedding vector for
                       each successfully embedded article summary.
        skipped_count: Number of items that failed embedding (warnings logged).
        from_cache:    ``True`` when embeddings were loaded from existing
                       ``news_stats`` rows (embedding call was skipped).
    """

    embeddings: dict[str, list[float]] = Field(
        default_factory=dict,
        description="url_hash → embedding vector for each embedded summary.",
    )
    skipped_count: int = Field(
        default=0, description="Items that failed embedding (warned and skipped)."
    )
    from_cache: bool = Field(default=False, description="True when loaded from existing news_stats rows.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TARGET_DIM = 768
# Fixed seed guarantees the same projection matrix is used across all calls
# for a given source dimension, making stored and freshly-computed embeddings
# comparable even across process restarts.
_PROJECTION_SEED = 42
# Module-level cache: src_dim → (src_dim × TARGET_DIM) projection matrix.
# Populated lazily on first call per unique source dimension.
_PROJECTION_CACHE: dict[int, Any] = {}


def _get_projection_matrix(src_dim: int) -> Any:
    """Return (or build) the fixed random Gaussian projection matrix for *src_dim*.

    The Johnson-Lindenstrauss construction uses a standard-normal random matrix
    whose columns are L2-normalised.  Column normalisation ensures each target
    dimension receives equal aggregate weight regardless of source dimensionality.
    The matrix is built once per (src_dim → _TARGET_DIM) pair and cached for
    the process lifetime.

    Args:
        src_dim: Dimensionality of the source embedding vector.

    Returns:
        NumPy array of shape ``(src_dim, _TARGET_DIM)`` with unit-norm columns.
    """
    if src_dim not in _PROJECTION_CACHE:
        import numpy as np  # available via pandas transitive dep
        rng = np.random.default_rng(_PROJECTION_SEED)
        mat = rng.standard_normal((src_dim, _TARGET_DIM)).astype(np.float32)
        col_norms = np.linalg.norm(mat, axis=0, keepdims=True)
        col_norms = np.where(col_norms > 0, col_norms, 1.0)
        mat /= col_norms
        _PROJECTION_CACHE[src_dim] = mat
    return _PROJECTION_CACHE[src_dim]


def _unify_dim(vec: list[float]) -> list[float]:
    """Unify an embedding vector to :data:`_TARGET_DIM` (768) dimensions.

    Uses a Johnson-Lindenstrauss random Gaussian projection for both
    reduction and increase:

    * ``len(vec) == 768``: returned unchanged.
    * ``len(vec) != 768``: projected via a fixed-seed random matrix of shape
      ``(src_dim, 768)``, then L2-normalised.

    Compared with truncation/padding, random projection:

    * **Reduction**: draws on *all* source dimensions (not just the first 768),
      and provably preserves pairwise distances (JL lemma).
    * **Increase**: distributes the low-dim signal uniformly across all 768
      target dimensions instead of leaving most as zeros.

    The projection matrix is deterministic (fixed seed) so the same source
    vector always maps to the same target vector, making cached and freshly
    computed embeddings directly comparable.

    Args:
        vec: Raw float vector from any embedding provider.

    Returns:
        A 768-dimensional float list with unit L2-norm (or all-zeros when the
        input norm is zero).
    """
    import numpy as np
    dim = len(vec)
    if dim == _TARGET_DIM:
        return vec
    mat = _get_projection_matrix(dim)
    arr = np.array(vec, dtype=np.float32)
    projected: list[float] | Any = arr @ mat  # shape: (_TARGET_DIM,)
    norm = float(np.linalg.norm(projected))
    if norm > 0.0:
        projected = projected / norm
    return projected.tolist()


# ---------------------------------------------------------------------------
# Celery handler
# ---------------------------------------------------------------------------


def _url_hash(url: str | None, title: str) -> str:
    """Compute sha256 of URL, falling back to title when url is absent."""
    key = url or title
    return hashlib.sha256(key.encode()).hexdigest()


async def _handler(payload: dict) -> dict:
    """Celery-layer business logic for do_emb.

    Generates embeddings for each article's ``title + content`` text.
    Per-item failures are logged as warnings and skipped; the batch always
    returns a valid :class:`DoEmbOutput`.

    Args:
        payload: Serialised :class:`DoEmbInput` fields.

    Returns:
        Serialised :class:`DoEmbOutput` dict.
    """
    inp = DoEmbInput.model_validate(payload)

    if not inp.news_articles:
        return DoEmbOutput().model_dump(mode="json")

    embedder = get_embedder()

    embeddings: dict[str, list[float]] = {}
    skipped_count = 0

    for article in inp.news_articles:
        title: str = article.get("title") or ""
        url: str | None = article.get("url")
        content: str = article.get("content") or ""
        if not title:
            continue
        url_hash_val = _url_hash(url, title)
        text = f"{title} {content}".strip()
        try:
            vecs = embedder.embed_documents([text])
            if vecs:
                embeddings[url_hash_val] = _unify_dim(vecs[0])
        except Exception as exc:
            logger.warning(
                "[%s] do_emb embed failed url_hash=%s: %s",
                NEWS_TASK_EMBED_ERROR, url_hash_val[:16], exc,
            )
            skipped_count += 1

    return DoEmbOutput(embeddings=embeddings, skipped_count=skipped_count).model_dump(mode="json")


# ---------------------------------------------------------------------------
# PG cache function
# ---------------------------------------------------------------------------


async def _do_emb_pg_cache(
    inp: DoEmbInput, ctx: NodeContext
) -> DoEmbOutput | None:
    """Check pg for existing embeddings in news_stats for the given input_raw_id.

    Returns cached embeddings when the linked ``input_raw`` row is within the
    4-hour TTL (implicitly guaranteed by ``get_news.pg_cache_fn``).

    Args:
        inp: Typed task input containing the ``input_raw_id``.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        ``DoEmbOutput`` with ``from_cache=True`` on a cache hit, or ``None``.
    """
    if inp.input_raw_id is None:
        return None
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(NewsStatsSQL.GET_EMBEDDINGS_BY_INPUT_RAW_ID, (inp.input_raw_id,))
        cached_rows = await cur.fetchall()
    if not cached_rows:
        return None
    cached_embeddings: dict[str, list[float]] = {}
    for row in cached_rows:
        emb_text: str | None = row["summary_embedding"]
        if emb_text:
            try:
                cached_embeddings[row["url_hash"]] = _unify_dim(json.loads(emb_text))
            except Exception:
                pass
    if not cached_embeddings:
        return None
    return DoEmbOutput(embeddings=cached_embeddings, from_cache=True)


# ---------------------------------------------------------------------------
# LangGraph layer — @task orchestration
# ---------------------------------------------------------------------------


@task
async def _do_emb_task(
    task_input: TaskInput[DoEmbInput],
) -> TaskOutput[DoEmbOutput]:
    """LangGraph @task: delegates do_emb to the Celery completion worker.

    The Celery handler catches per-item errors internally and always returns
    a valid output.  If ``delegate_completion`` itself raises (Celery
    infrastructure failure), the task is marked ``failed`` and the exception
    propagates so that the seq-level wrapper can log a warning and continue.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`DoEmbInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`DoEmbOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="Json",
    )
    try:
        result = await delegate_completion(
            ctx.thread_id, ctx.task_id, ctx.node_id, ctx.node_name, ctx.task_name, payload,
        )
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            failed=True, error=str(exc),
        )
        raise
    output = DoEmbOutput.model_validate(result)
    return TaskOutput(ctx=ctx, content=output)


do_emb: NodeTask[DoEmbInput, DoEmbOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Generate 768-dim vector embeddings for the AI summaries produced by do_summary. "
        "Soft-failure task — per-item failures emit warnings but do not fail the task."
    ),
    input_type=DoEmbInput,
    output_type=DoEmbOutput,
    task_fn=_do_emb_task,
    handler=_handler,
    pg_cache_fn=_do_emb_pg_cache,
)

HANDLERS: dict[str, object] = {_TASK_NAME: _handler}

__all__ = ["DoEmbInput", "DoEmbOutput", "do_emb", "HANDLERS"]
