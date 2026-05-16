# Split Context Strategies: Summarization vs Sliding Window

TopicSession uses LLM summarization to compress older messages; FreeChatSession uses a sliding window of recent messages. We considered unifying to a single strategy but kept them split because the session lifecycles differ fundamentally — topic discussions are long-running and need semantic compression, while IM-style chats benefit from simple recency.

## Considered Options

1. **Unified summarization for both** — rejected: summarization adds latency and LLM cost that harms the real-time feel of FreeChatSession. IM conversations are shorter-lived and benefit from the full verbatim context of recent messages.
2. **Unified sliding window for both** — rejected: topic discussions can span dozens of rounds. A sliding window would silently drop critical context (early agreements, voted-out options) that summarization preserves.
3. **Split strategies (chosen)**: TopicSession gets smart compression, FreeChatSession gets simple recency. FreeChatSession adds a hard memory cap (500 messages) with cold-storage archival to prevent unbounded memory growth.
