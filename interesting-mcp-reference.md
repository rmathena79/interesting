# Reference: interesting MCP Server

The `interesting` MCP server provides persistent, cross-session tracking of news stories the user wants to follow. This doc covers what each tool does, how to format its inputs, and when to call it.

## What is a "topic"?

A topic is a distinct, ongoing news story - broader than a single article but narrower than a subject area. The title must be useful to inform LLM search queries.

Good:
- "Bondi subpoenaed about Epstein files"
- "Warhammer 40K 11th edition release"
- "OpenAI vs NYT copyright lawsuit"

Bad:
- "Politics" (subject area, not a story)
- "NYT article from Tuesday about AI" (single article, not a story)
- "Trump" (person, not a story)
- "that crypto thing" (not searchable)

When creating titles, include distinctive nouns, entities, or events. Vague phrasing degrades results.

## Scope

Each topic has a `scope` field indicating its geographic or domain footprint. The server does not interpret scope - it only stores and returns it. The client uses scope to decide which topics to include when the user asks for news.

### Known scopes

Scopes form a containment hierarchy. Narrower scopes are contained within broader ones.

    world   -> everything
      us    -> United States
        pdx -> Portland, Oregon

The server validates scope values on every write and filter call; unknown scopes are rejected. Call `list_scopes` to get the current list of valid scopes and their containment relationships.

### Filtering rule

When the user asks for news within some requested scope, include topics whose stored scope equals the request OR is contained within it.

    request "pdx"   -> include: pdx
    request "us"    -> include: us, pdx
    request "world" -> include: world, us, pdx

When the user asks for news with no scope qualifier, default to all topics.

### Choosing a scope for new topics

When calling `add_topic`, pick the narrowest scope the story fits in. A Portland city council vote is `pdx`, not `us`. A federal subpoena is `us`, not `world`. A foreign conflict or international treaty is `world`.

If you are unsure, ask the user or default to `world` and let them correct it.

## Tool reference

### `list_scopes`
Parameters: none.

Returns:
```json
{
  "scopes": ["pdx", "us", "world"],
  "default": "world",
  "containment": {
    "world": ["pdx", "us", "world"],
    "us": ["pdx", "us"],
    "pdx": ["pdx"]
  }
}
```
`scopes` lists every valid scope value. `containment` shows which stored scopes are included when filtering `list_topics` by a given scope.

### `add_topic`
Parameters:
- `title` (string, required): ASCII, non-empty, max 128 chars.
- `scope` (string, optional): Must be a known scope (see `list_scopes`). Defaults to `"world"`. Pick the narrowest known scope that contains the story.

Returns: `{"id": "...", "title": "...", "scope": "...", "added_at": "..."}`

Confirm addition briefly to the user, including the scope so they can correct it. Do not surface the UUID unless asked.

### `list_topics`
Parameters:
- `scope` (string, optional): If provided, must be a known scope (see `list_scopes`). Returns only topics whose stored scope equals the requested scope or is contained within it (see Filtering rule above). Omit or pass empty string to return all topics.
- `roundup` (boolean, optional, default `false`): Set to `true` when calling as part of a news roundup. The server records `last_checked_at` for every returned topic.

Returns: JSON array of `{id, title, scope, added_at, last_checked_at}` objects. Empty array if nothing is tracked.
- `added_at`: ISO 8601 UTC timestamp set when the topic was added; `null` for topics added before this field existed.
- `last_checked_at`: ISO 8601 UTC timestamp of the last `roundup=true` call that returned this topic; `null` if the topic has never been included in a roundup query. This records when the topic was last queried as part of a roundup — not whether new information was found.

### `update_topic`
Parameters:
- `id` (string, required): UUID of the topic to update. Copy from `list_topics` or `add_topic` output.
- `title` (string, optional): New title. Omit or pass empty string to leave unchanged. Same format rules as `add_topic`.
- `scope` (string, optional): New scope. Must be a known scope (see `list_scopes`). Omit or pass empty string to leave unchanged.

At least one of `title` or `scope` must be provided.

Returns: `{id, title, scope, added_at, last_checked_at}` reflecting the updated state. `added_at` and `last_checked_at` are never modified by this call.

### `remove_topic`
Parameters:
- `id` (string, required): UUID from `list_topics` or `add_topic`. Case-sensitive, exact match required.

Returns: `"OK"` on success. Error if the ID is not found.

To remove by user description rather than ID, call `list_topics` first to find the match. If more than one topic could match, ask which to remove rather than guessing. If none match, say so; do not invent an ID.

## Notes

- IDs are server-generated UUIDs. Always copy them from tool output; never construct or guess one.
- The server stores scope verbatim and validates it against the known scope list on every write. Use only values returned by `list_scopes`.
- An empty topic list is a valid state. Do not fabricate entries.
- If a call fails unexpectedly, report the error to the user rather than retrying silently or substituting a different action.
- `last_checked_at` means "last included in a roundup query," not "last yielded new results." Do not treat a recent `last_checked_at` as evidence that the topic is fully up to date.

---

## Operational Context

How the chat application is expected to use these tools.

### Topic Tracking

The user can add, list, and remove tracked topics conversationally. Map natural language to tools as follows:

| User intent | Tool | Notes |
|-------------|------|-------|
| "track X", "follow up on X", "keep an eye on X" | `add_topic` | Apply title and scope rules above |
| "what am I tracking?", "show my topics" | `list_topics` | No scope or `roundup` needed |
| "stop tracking X", "drop X", "remove X from my list" | `remove_topic` | Call `list_topics` first to resolve the ID; if multiple topics could match, ask the user rather than guessing |

### News Roundup

**Trigger:** `news {scope} {timeframe}` (scope defaults to `us`, timeframe defaults to `48h`)

| Parameter | Options | Default |
|-----------|---------|---------|
| scope | `pdx` / `us` / `world` | `us` |
| timeframe | `Xh` or `Xd` (hours/days) | `48h` |

**Workflow:**
1. Call `list_topics(scope=<requested_scope>, roundup=true)` to retrieve tracked stories filtered to the requested scope. The server applies the containment rule (see Filtering rule above) and records `last_checked_at` for each returned topic.
2. Search for new developments on each returned tracked topic within the requested timeframe.
4. For tracked topics with no significant new development, skip rather than re-summarizing. When something material has changed, present the update and context, not a full recap.
5. Search for additional stories matching the requested scope and user interest profile.
6. Use the `recent_chats` tool (if available) to avoid re-presenting stories already covered; if there is no new information, omit the story entirely.

The tracked topic list is the source of truth for follow-up stories. Do not use `recent_chats` or conversation memory alone to reconstruct what the user cares about across sessions.