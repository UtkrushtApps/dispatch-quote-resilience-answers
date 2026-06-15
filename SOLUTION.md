# Solution Steps

1. Keep the worker agents as the boundary that converts downstream tool exceptions into AgentResult statuses: ToolUnavailable becomes AGENT_UNAVAILABLE and ToolError becomes AGENT_INVALID.

2. In DispatchManager, add per-conversation state storage so each build_quote call creates a ConversationState, stores it by conversation id, and exposes it through last_state/get_state/get_events for traceability.

3. Wrap each individual agent attempt in a caller-side timeout. Run the blocking agent.handle call in a daemon thread, join only for the remaining per-agent budget, and synthesize an AGENT_TIMEOUT AgentResult if the thread does not finish in time.

4. Make the per-agent timeout a total budget across all attempts, not a timeout that resets forever. This keeps slow workers from consuming unbounded request time.

5. Implement retry classification. Treat AGENT_UNAVAILABLE and AGENT_TIMEOUT as transient classes, but retry only AGENT_UNAVAILABLE while attempts and timeout budget remain. Never retry AGENT_INVALID permanent failures.

6. For every attempt, write structured LogEvent records containing the conversation id, agent name, attempt number, status, latency, error, retryable flag, and whether another retry will be made.

7. Always call all three agents so the manager can determine whether the final outcome has zero, one, or multiple failed agents.

8. If all final agent results are OK, return the original successful quote shape and values exactly as before with status OK and an empty degraded_agents list.

9. If exactly one final agent result failed or timed out, apply that agent’s documented fallback contribution: EtaAgent uses eta_minutes=90, CapacityAgent uses vehicles_available=0, and WeatherAgent uses delay_risk='unknown'. Return the same response fields with status DEGRADED and the failed agent name in degraded_agents.

10. If more than one final agent result failed, return a safe rejection with status REJECTED. Preserve the public response field names but set quote values to None so the API does not return a misleading quote.

11. Record final structured events for fallback_applied, quote_built, or quote_rejected so logs show the final degraded versus escalated decision.

