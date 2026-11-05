---
description: Log every prompt/response pair to .chat-history/log.md
alwaysApply: true
---

# Chat History Logging

1. At the start of each session, read `.chat-history/log.md` for previous context.
2. After each response, append to `.chat-history/log.md` using this exact format:

```
---
- timestamp: "<ISO 8601 timestamp if available, otherwise estimate based on conversation order>"
- user_prompt: "<the user's original prompt>"
- assistant_response_summary: "<summary of what you generated or answered for this prompt>"
- files_affected: "<comma-separated list of files created or modified, or none>"
```

3. Create the file/folder if they don't exist. Never delete previous entries.
4. Do all of this silently — never ask for confirmation.

Rules:
- Be precise about Files Affected: only include files explicitly created or modified during this response.
- Never skip an exchange; every prompt/response pair must be logged.
- Keep Assistant Response Summary concise but specific: mention function names, endpoints, or key decisions made.
- Never write secrets to the log: replace API keys, tokens, passwords and .env values with *** in every field, including user_prompt.
