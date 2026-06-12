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

## Notes field

Each topic has an optional `notes` field — a short free-text annotation that helps the LLM search more precisely during roundups. It is not searched directly; it is guidance for you, the AI assistant.

Use notes to record:
- **Angle or focus**: what the user actually cares about within a broad story ("user interested in regulatory implications, not stock price")
- **Search hints**: alternate names, case numbers, or specific entities that improve retrieval ("also known as United States v. Google; docket 23-cv-03985")
- **Exclusions**: terms to avoid or distinguish from ("Portland OR not Portland ME")
- **Context**: why the story matters to this user ("user's employer is directly affected")

Good notes examples:
- "Focus on FDA response, not the initial filing"
- "Track Multnomah County specifically; ignore statewide ballot coverage"
- "DOJ antitrust case; docket 1:20-cv-03010; user wants market-structure angle"

Bad notes (don't do this):
- A full summary of the story — that belongs in search results, not here
- Repetition of information already in the title
- Personal opinions unrelated to search guidance

Notes are optional. When absent, the title alone drives search. Notes are shown in `list_topics` output so you can review them before a roundup.

If a roundup turns up a sharper framing, an alternate name, or a key entity that would help future searches, consider calling `update_topic` to refine the notes — small refinements over time keep search guidance current as a story evolves.

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

## Cadence

Each topic has a `cadence` field that controls how often it is eligible for inclusion in a roundup. In roundup mode the server filters out topics still within their cadence cooldown before applying the rotation/limit, so slow-moving stories don't crowd out faster-moving ones (or genuinely new search territory).

### Values

- `rare` — stories that update every couple weeks or less; long-running investigations, slow regulatory processes, periodic reports.
- `occasional` — weekly-ish stories; ongoing legal cases between hearings, multi-week negotiations, gradually unfolding situations.
- `regular` — every few days; the default. Use this when you don't have a strong reason to pick another value.
- `frequent` — daily-ish; active campaigns, breaking-but-paced stories, fast-moving product launches, ongoing conflicts.
- `always` — no minimum interval; the topic is eligible for every roundup. Reserve for stories where every roundup should re-check (e.g. a high-priority crisis the user explicitly wants tracked closely).

### Choosing a cadence

Default to `regular`. Step up to `frequent` for breaking or fast-moving stories, step down to `occasional` or `rare` for stories that update slowly. Use `always` sparingly — it bypasses the cooldown entirely and can crowd out other tracked topics.

Cadence can be changed at any time via `update_topic`. As a story's tempo changes (a court case wraps, an investigation goes quiet, a regulator schedules new hearings), revise its cadence so the rotation matches the actual pace of new developments.

## Topic status

Each topic has a `status` of either `"active"` (default) or `"archived"`. Archived topics are excluded from `list_topics` and roundups by default. Use `archive_topic` when a story has concluded rather than deleting it — archiving preserves history and allows reactivation if the story resurfaces.

## Tool reference

### `get_instructions_tool`
Parameters: none.

Returns detailed instructions and notes on how to use these tools.

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
- `title` (string, required): Printable ASCII, non-empty, max 128 chars. No control characters.
- `scope` (string, optional): Must be a known scope (see `list_scopes`). Defaults to `"world"`. Pick the narrowest known scope that contains the story.
- `notes` (string, optional): Printable ASCII, max 512 chars. Search guidance for the AI assistant — see Notes field section above. Omit if no guidance is needed.
- `cadence` (string, optional): One of `rare`, `occasional`, `regular`, `frequent`, `always`. Defaults to `regular`. See the Cadence section above for what each value means.

Returns: `{"id": "...", "title": "...", "scope": "...", "added_at": "...", "last_checked_at": null, "notes": null, "status": "active", "cadence": "regular"}`

Confirm addition briefly to the user, including the scope so they can correct it. Do not surface the UUID unless asked.

### `list_topics`
Parameters:
- `scope` (string, optional): If provided, must be a known scope (see `list_scopes`). Returns only topics whose stored scope equals the requested scope or is contained within it (see Filtering rule above). Omit or pass empty string to return all topics.
- `roundup` (boolean, optional, default `false`): Set to `true` when calling as part of a news roundup. See rotation behavior below.
- `include_archived` (boolean, optional, default `false`): Set to `true` to include archived topics in the result. Normally omit this — archived topics should not appear in roundups.

**Without `roundup=true`:** Returns all matching active topics sorted by title. Cadence does not affect this mode.

**With `roundup=true` (rotation mode):** Returns at most 6 active topics, prioritizing those least recently checked — topics with `last_checked_at = null` first, then oldest checked, with random tiebreaking among equals. Topics still within their cadence cooldown are filtered out before the rotation/limit runs, so the result may contain fewer than 6 topics — or be empty — when everything tracked has been checked recently. The server records `last_checked_at` for every returned topic. This ensures that over successive roundup calls, all tracked topics are visited in rotation rather than the same topics being returned every time.

Returns: JSON array of `{id, title, scope, added_at, last_checked_at, notes, status, cadence}` objects. Empty array if nothing is tracked or if all eligible topics are still within their cadence cooldown.
- `added_at`: ISO 8601 UTC timestamp set when the topic was added; `null` for topics added before this field existed.
- `last_checked_at`: ISO 8601 UTC timestamp of the last `roundup=true` call that returned this topic; `null` if the topic has never been included in a roundup query. This records when the topic was last queried as part of a roundup — not whether new information was found.
- `notes`: Search guidance string, or `null` if no notes were recorded. Review notes before searching — they refine your query angle.
- `status`: `"active"` or `"archived"`. Under default parameters only `"active"` topics are returned.
- `cadence`: One of `rare`, `occasional`, `regular`, `frequent`, `always`. See the Cadence section above.

### `update_topic`
Parameters:
- `id` (string, required): UUID of the topic to update. Copy from `list_topics` or `add_topic` output.
- `title` (string, optional): New title. Omit or pass empty string to leave unchanged. Same format rules as `add_topic`.
- `scope` (string, optional): New scope. Must be a known scope (see `list_scopes`). Omit or pass empty string to leave unchanged.
- `notes` (string, optional): New notes. Omit or pass empty string to leave unchanged. Same format rules as `add_topic`. Mutually exclusive with `clear_notes`.
- `cadence` (string, optional): New cadence. Must be one of `rare`, `occasional`, `regular`, `frequent`, `always`. Omit or pass empty string to leave unchanged. Adjust as a story's pace changes.
- `clear_notes` (boolean, optional, default false): Pass `true` to remove existing notes entirely. Mutually exclusive with `notes`.

At least one of `title`, `scope`, `notes`, `cadence`, or `clear_notes` must be provided.

Returns: `{id, title, scope, added_at, last_checked_at, notes, status, cadence}` reflecting the updated state. `added_at`, `last_checked_at`, and `status` are never modified by this call.

### `archive_topic`
Parameters:
- `id` (string, required): UUID from `list_topics` or `add_topic`. Case-sensitive, exact match required.
- `archived` (boolean, optional, default `true`): Pass `false` to reactivate an archived topic.

Returns: `{id, title, scope, added_at, last_checked_at, notes, status}` with the updated status. Error if the ID is not found.

Use `archive_topic` when a story has concluded or is no longer relevant. This removes the topic from normal rotation and roundups without deleting history. If the story resurfaces, call `archive_topic(id, archived=false)` to reactivate it.

Do not archive a topic just because it has been quiet — use `last_checked_at` to assess staleness. Archive when the user explicitly says the story is over, or when you judge the story has genuinely concluded (verdict reached, product released, person left office, etc.).

### `remove_topic`
Parameters:
- `id` (string, required): UUID from `list_topics` or `add_topic`. Case-sensitive, exact match required.

Returns: `"OK"` on success. Error if the ID is not found.

Prefer `archive_topic` over `remove_topic` when a story has concluded — archiving preserves history. Use `remove_topic` only when the topic was added in error or is genuinely irrelevant and its history has no value.

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
| "track X", "follow up on X", "keep an eye on X" | `add_topic` | Apply title and scope rules above; offer to add notes if the user has a specific angle |
| "what am I tracking?", "show my topics" | `list_topics` | No scope or `roundup` needed |
| "stop tracking X", "drop X", "remove X from my list" | `archive_topic` | Prefer archive over remove to preserve history; use `remove_topic` only for topics added in error |
| "X story is over / concluded / resolved" | `archive_topic` | Archive rather than remove |
| "reactivate X", "X is back in the news" | `archive_topic(id, archived=false)` | Reactivate an archived topic |
| "add context to X", "note that X focuses on Y" | `update_topic` with notes | Record search guidance in the notes field; use `clear_notes=true` to remove notes |
| "check X more / less often", "X is heating up / quieting down" | `update_topic` with cadence | Adjust cadence to match the story's tempo |

### News Roundup

**Trigger:** `news {scope} {timeframe}` (scope defaults to `us`, timeframe defaults to `48h`)

| Parameter | Options | Default |
|-----------|---------|---------|
| scope | `pdx` / `us` / `world` | `us` |
| timeframe | `Xh` or `Xd` (hours/days) | `48h` |

**Workflow:**
1. Call `list_topics(scope=<requested_scope>, roundup=true)` to retrieve a rotation batch of tracked stories filtered to the requested scope. The server returns at most 6 active topics (those least recently checked) after filtering out any still within their cadence cooldown, applies the containment rule (see Filtering rule above), and records `last_checked_at` for each returned topic. Not all tracked topics will appear in every roundup — this is by design. The result may contain fewer than 6 topics, or be empty, when everything tracked has been checked recently.
2. For each returned topic, review its `notes` field before searching. Use notes to sharpen the search query — adjust angle, include alternate names, exclude irrelevant terms.
3. Search for new developments on each returned tracked topic within the requested timeframe.
4. For tracked topics with no significant new development, skip rather than re-summarizing. When something material has changed, present the update and context, not a full recap.
5. Search for additional stories matching the requested scope and user interest profile.
6. Use the `recent_chats` tool (if available) to avoid re-presenting stories already covered; if there is no new information, omit the story entirely.

The tracked topic list is the source of truth for follow-up stories. Do not use `recent_chats` or conversation memory alone to reconstruct what the user cares about across sessions.
