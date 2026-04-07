"""Pipeline: Compute news extensions (sentiment analysis via LLM).

Transform: fin_markets.news → fin_markets.news_exts (with sentiment_level)
"""

import json
import logging
from typing import Any

from app.pipelines.base import BasePipeline
from app.llm.factory import create_llm_client
from app.llm.base import LLMMessage

logger = logging.getLogger(__name__)


class ComputeNewsExtsPipeline(BasePipeline):
    """Analyse news articles via LLM and populate news_exts with sentiment."""

    async def run(self, batch_size: int = 20, **kwargs: Any) -> int:
        """Process unanalysed news articles.

        Args:
            batch_size: Max articles per batch (default 20).

        Returns:
            Number of news_exts rows created.
        """
        llm = create_llm_client()

        try:
            # Get news rows that have no news_exts yet
            articles = await self._execute(
                """
                SELECT n.id, n.title, n.body
                FROM fin_markets.news n
                WHERE NOT EXISTS (
                    SELECT 1 FROM fin_markets.news_exts ne WHERE ne.news_id = n.id
                )
                ORDER BY n.published_at DESC NULLS LAST
                LIMIT %s
                """,
                (batch_size,),
            )

            if not articles:
                logger.info("No unprocessed news articles found")
                return 0

            count = 0
            for article in articles:
                title = article["title"] or ""
                body = (article["body"] or "")[:2000]  # truncate long bodies

                prompt = (
                    "Analyze the following financial news article and return a JSON object with:\n"
                    '- "sentiment_level": one of "VERY_NEGATIVE", "NEGATIVE", "NEUTRAL", "POSITIVE", "VERY_POSITIVE"\n'
                    '- "summary": 1-2 sentence summary of financial impact\n'
                    '- "keywords": list of up to 5 keywords\n\n'
                    f"Title: {title}\n\n"
                    f"Body: {body}\n\n"
                    "Return ONLY valid JSON."
                )

                try:
                    response = await llm.chat(messages=[
                        LLMMessage(role="system", content="You are a financial news analyst. Return JSON only."),
                        LLMMessage(role="user", content=prompt),
                    ])

                    parsed = json.loads(response.content)
                    sentiment = parsed.get("sentiment_level", "NEUTRAL")
                    summary = parsed.get("summary", "")

                    # Validate sentiment value
                    valid_sentiments = {"VERY_NEGATIVE", "NEGATIVE", "NEUTRAL", "POSITIVE", "VERY_POSITIVE"}
                    if sentiment not in valid_sentiments:
                        sentiment = "NEUTRAL"

                    await self._execute(
                        """
                        INSERT INTO fin_markets.news_exts
                            (news_id, published_at, sentiment_level, summary, extra)
                        VALUES (%s, NOW(), %s, %s, %s::jsonb)
                        ON CONFLICT (news_id) DO NOTHING
                        """,
                        (article["id"], sentiment, summary,
                         json.dumps({"keywords": parsed.get("keywords", [])})),
                    )
                    count += 1

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Failed to parse LLM response for news_id=%d: %s", article["id"], e)
                except Exception as e:
                    logger.warning("LLM call failed for news_id=%d: %s", article["id"], e)

            logger.info("Created %d news_exts from %d articles", count, len(articles))
            return count

        finally:
            await llm.close()
            await self.close()
