# Study formats

Output goes in `study/<kind>/<slug>.*`. Quizzes and flashcards are JSON (source of truth) rendered by
`eztudy render` into `.md` (printable, with answer key) and `.html` (self-contained interactive player,
works offline, saves progress in the browser). Everything else is Markdown.

## Universal quality rules
- **Grounded only**: every item comes from the sources and carries `citations`. No outside facts.
- **Coverage**: spread items across topics proportional to their weight in the sources; don't
  cluster on the first document. Plan from `wiki/index.md` or `eztudy sources`.
- **Test understanding, not trivia**: prefer why/how/compare/apply over "which year". Mix difficulty
  (roughly 30% easy, 50% medium, 20% hard unless asked).
- **Self-contained**: questions make sense without the source in front of you; no "according to
  the passage".
- Check every answer against the cited chunk before writing it.

## Citation object
```json
{"cid": "3fa9c2d1:12", "source": "bio/cells.pdf", "location": "page 4"}
```
`cid` and `location` come straight from `eztudy search` output. A plain string (`"cells.pdf p.4"`) is
also accepted.

## Quiz — `study/quizzes/<slug>.json`
```json
{
  "type": "quiz",
  "id": "cell-bio-ch1",
  "title": "Cell Biology — Chapter 1",
  "description": "10 questions on organelles and energy",
  "items": [
    {
      "id": "q1",
      "type": "mcq",
      "question": "Which organelle produces most of a cell's ATP?",
      "options": ["Nucleus", "Mitochondrion", "Ribosome", "Golgi apparatus"],
      "answer": 1,
      "explanation": "Mitochondria generate ATP via oxidative phosphorylation.",
      "difficulty": "easy",
      "topic": "Organelles",
      "citations": [{"cid": "a8cbb175:0", "source": "bio/cells.pdf", "location": "page 1"}]
    },
    {"id": "q2", "type": "multi", "question": "Select all that are organelles.", "options": ["..."], "answer": [0, 2], "...": "..."},
    {"id": "q3", "type": "true_false", "question": "…", "answer": false, "...": "..."},
    {"id": "q4", "type": "short", "question": "Explain …", "answer": "Model answer the learner self-grades against.", "...": "..."}
  ]
}
```
- `answer`: 0-based option index (`mcq`), list of indices (`multi`), boolean (`true_false`), model answer string (`short`),
  model solution (`code`, see below).
- MCQ: 4 options, one unambiguously correct; distractors plausible, similar length, drawn from
  related concepts in the sources; avoid "all/none of the above". Vary the correct position.
- `explanation`: why the answer is right *and* why the tempting distractor is wrong.
- Multi-line `answer` / `explanation` text keeps its line breaks; wrap code in ```` ``` ```` fences for
  a monospace block (unfenced multi-line code is detected too).
- Player (click-only, no keyboard shortcuts): clicking an option only selects it; **Confirm** grades it.
  Set top-level `"instant_feedback": true` to grade single-answer items on click instead.

### Code items (`"type": "code"`)
For questions where the student writes code. The player gives them a real editor (CodeMirror, offline):
syntax colours that follow the skin, line numbers, bracket matching, auto-indent, Tab to indent (Esc then Tab
leaves the editor), local completions, conservative live lint, and an optional **Vim keys** toggle in the ⋯ menu.
```json
{
  "id": "heap-remove", "type": "code", "language": "java", "topic": "Heaps", "difficulty": "medium",
  "question": "Implement remove() for an array-backed MinHeap (root at index 1).",
  "starter": "public T remove() {\n    $0\n}",
  "context": {"identifiers": ["backingArray", {"name": "size", "kind": "field", "detail": "int"},
                              {"name": "downHeap", "kind": "method", "detail": "(int i)"}]},
  "answer": "public T remove() {\n    if (size == 0) throw new NoSuchElementException();\n    …\n}",
  "rubric": [{"id": "empty", "text": "Throws NoSuchElementException when empty", "points": 2, "match": "NoSuchElementException"},
             {"id": "down", "text": "Restores heap order with downHeap", "points": 2, "match": "downHeap\\("}],
  "explanation": "…", "citations": [{"cid": "…", "source": "ds/heaps.pdf", "location": "page 3"}]
}
```
- `language`: `java`, `python`, `c`/`cpp`, `javascript`/`typescript` (`js`, `ts`, `jsx`, `tsx`), `sql` (`postgresql`,
  `mysql`, `sqlite`), `go`, `rust`. Anything else is edited as plain text. Only the languages a quiz uses are
  bundled into its page; quizzes without code items carry no editor at all.
- `starter` (optional): pre-filled code; `$0` marks where the cursor starts.
- `context.identifiers` (optional): names from the surrounding code (class fields, helper methods, types) offered
  as completions with their kind (`field`, `method`, `function`, `type`, `variable`, `constant`). Completions are
  local only (keywords, these identifiers, words in the file, snippets); the popup says so.
- `answer`: the model solution, shown highlighted after the student submits.
- `rubric` (optional): what a full answer does. After submitting, the student ticks each criterion to grade
  themselves. `match` (optional, a regex) is a **hint**: the first line matching it gets a ✓ in the gutter and
  the criterion shows "hint: line N" or "hint: not found". Hints never grade; write them to match the key
  construct (a call, an exception, a comparison), not whole lines, and leave `match` out when no regex would
  be reliable.
- Use `code` when writing code is the skill being tested; use `short` for explanations that may quote code.
- Grading is self-graded ("I got it" / "I missed it"); performance reports include the code and ticked criteria.

## Flashcards — `study/flashcards/<slug>.json`
```json
{
  "type": "flashcards",
  "id": "cell-bio-cards",
  "title": "Cell Biology — key terms",
  "items": [
    {"id": "c1", "front": "Mitochondrion", "back": "Organelle that produces ATP by oxidative phosphorylation.",
     "tags": ["organelles"], "citations": [{"cid": "a8cbb175:0", "source": "bio/cells.pdf", "location": "page 1"}]}
  ]
}
```
- One fact per card (minimum information principle). Back ≤ ~40 words.
- Mix directions: term→definition, question→answer, cause→effect, cloze (`front: "ATP is made by ___"`).
- `tags` drive the deck filter in the player's ⋯ menu — use topic names.
- Player: tap the card to flip it; ‹ / › move between cards; ✗ "Still learning" / ✓ "Know it" mark
  the current card (marks are remembered per browser).

## Performance report (written by the player, read by `eztudy report import`)
At the end of a quiz (results screen) or a deck (Done screen) the player offers **Save report** and **Copy
report**. One report covers one session; Retry missed and Start over begin a new one.
```json
{"eztudy_report": 1, "kind": "quiz", "deck": {"id": "cell-bio-ch1", "title": "Cell Biology — Chapter 1"},
 "session": "mw9jik93-8g1q4c", "started_at": "2026-11-09T17:20:01Z", "finished_at": "2026-11-09T17:33:39Z",
 "score": {"right": 7, "total": 10},
 "items": [{"id": "q1", "type": "mcq", "topic": "Organelles", "tags": [], "difficulty": "easy",
            "question": "Which organelle…", "result": "wrong", "graded": "auto",
            "given": "Nucleus", "correct_answer": "Mitochondrion"}]}
```
- Quiz `result`: `correct` | `wrong`; `graded` is `self` for short answers (`given` is the student's draft).
- Flashcards: `score` is `{know, learn, unmarked}`; items carry `front`, `tags`, `correct_answer` (the back) and
  `result` `know` | `learn` | `unmarked`. Only cards viewed in that session are included.
- Mastery groups by item `topic` plus `tags`, so give every quiz item a `topic` and every card `tags`, and
  reuse the same topic names across decks (use the wiki topic page titles).
- Keep item `id`s stable when you revise a deck, so history follows the item.

## Player skins
The `.html` player has five skins on the same layout: `focus` (default), `editorial`, `terminal`,
`system7`, `typewriter`. Each has light and dark. Viewers switch skin and light/dark from the ⋯ menu,
and their choice is remembered. Set the default with `eztudy render x.json --theme editorial`, or for the
whole notebook in `.eztudy/config.toml`:
```toml
[ui]
theme = "editorial"
```

## Markdown kinds (`study/guides/<slug>.md` unless noted)
All start with `# Title`, a one-line scope (which sources), and end with a `## Sources` list.

| Kind | Content |
|---|---|
| **Study guide** | Key concepts per topic, short-answer review questions, essay prompts, glossary of terms. |
| **Briefing doc** | Executive summary; main themes with the most important supporting quotes (quoted verbatim, cited); open questions. |
| **FAQ** | 10–20 questions a learner would actually ask, answered from the sources. |
| **Glossary** | Alphabetical terms with 1–2 sentence definitions and citations. |
| **Timeline** | Chronological table (`Date | Event | Source`) plus a cast of characters. |
| **Mind map** | A Mermaid `mindmap` block (root = notebook/topic, ≤ 4 levels) followed by a short legend. |
| **Audio overview script** (`study/audio/<slug>.md`) | Two-host conversational script (HOST A curious, HOST B expert), 5–12 min (~800–1800 words): hook, 3–5 segments, recap. Natural speech, analogies; facts stay sourced. |
| **Practice exam** | A larger quiz JSON (`type: quiz`, 20–50 items, mixed types) — render it. |

When the user asks for something not listed (cheat sheet, comparison table, lesson plan, essay
outline), follow the same rules: grounded, cited, Markdown in `study/`.
