-- "All FOMC news in the last 7 days, ranked by relevance"
SELECT n.*, t.relevance
FROM fin_markets.news n
JOIN fin_markets.news_topic_news t USING (id)
JOIN fin_markets.news_topics tp ON tp.id = t.topic_id
WHERE tp.path <@ 'macro.central_bank.fomc'
  AND n.published_at > NOW() - INTERVAL '7 days'
ORDER BY t.relevance DESC, n.published_at DESC;

-- "Topic activity heatmap over time" (the full grid)
SELECT tp.path, date_trunc('day', n.published_at) AS day, count(*)
FROM fin_markets.news_topic_news t
JOIN fin_markets.news n ON n.id = t.news_ext_id
JOIN fin_markets.news_topics tp ON tp.id = t.topic_id
GROUP BY tp.path, day;