# Reference: interesting MCP Server

The `interesting` MCP server provides persistent, cross-session tracking of news stories the user wants to follow. This doc covers what each tool does and how to format its inputs. Triggers for when to call each tool are in the project instructions.

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

More scopes may be added over time. If you see a scope you don't recognize, infer its containment from context or ask the user.

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

### `add_topic`
Parameters:
- `title` (string, required): ASCII, non-empty, max 128 chars.
- `scope` (string, optional): ASCII, max 32 chars. Defaults to `"world"`. Pick the narrowest known scope that contains the story.

Returns: `{"id": "...", "title": "...", "scope": "..."}`

Confirm addition briefly to the user, including the scope so they can correct it. Do not surface the UUID unless asked.

### `list_topics`
Parameters: none.

Returns: JSON array of `{id, title, scope}` objects. Empty array if nothing is tracked.

### `remove_topic`
Parameters:
- `id` (string, required): UUID from `list_topics` or `add_topic`. Case-sensitive, exact match required.

Returns: `"OK"` on success. Error if the ID is not found.

To remove by user description rather than ID, call `list_topics` first to find the match. If more than one topic could match, ask which to remove rather than guessing. If none match, say so; do not invent an ID.

## Notes

- IDs are server-generated UUIDs. Always copy them from tool output; never construct or guess one.
- The server stores scope verbatim. Spelling and case must be consistent across topics for filtering to work ("US" and "us" will not match each other; prefer lowercase).
- An empty topic list is a valid state. Do not fabricate entries.
- If a call fails unexpectedly, report the error to the user rather than retrying silently or substituting a different action.
- There is not function to update an existing topic. To update, you must remove and re-add, getting a new ID.