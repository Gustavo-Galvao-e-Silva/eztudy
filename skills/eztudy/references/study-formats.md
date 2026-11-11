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
  model solution (`code`, see below); for `numeric`, `cloze`, `ordering` and `matching` see "Exactly-checked items".
- MCQ: 4 options, one unambiguously correct; distractors plausible, similar length, drawn from
  related concepts in the sources; avoid "all/none of the above". Vary the correct position.
- `explanation`: why the answer is right *and* why the tempting distractor is wrong.
- `question`, `options`, `answer`, `explanation`, rubric text and flashcard faces render Markdown: `` `code` ``,
  `**bold**`, `*italic*`, `~~strike~~`, `[links](https://…)`, `-` / `1.` lists, `>` quotes, and ```` ``` ```` fences
  for code blocks (unfenced multi-line code is detected too). Line breaks are kept. A question's first paragraph is
  its heading; code or lists after it show below. Raw HTML is shown as text, never rendered.
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
- `rubric` (optional): what a full answer does. After submitting, the student can tick each criterion; the
  agent grading a served quiz marks each one met or not. `match` (optional, a regex) is a **hint**: the first line matching it gets a ✓ in the gutter and
  the criterion shows "hint: line N" or "hint: not found". Hints never grade; write them to match the key
  construct (a call, an exception, a comparison), not whole lines, and leave `match` out when no regex would
  be reliable.
- Use `code` when writing code is the skill being tested; use `short` for explanations that may quote code.
- Grading: served by `eztudy serve`, short and code answers are graded by the agent when the quiz ends (see
  below). Opened from disk they are self-graded ("I got it" / "I missed it"). Reports include the code and ticked criteria.

### Exactly-checked items (`numeric`, `cloze`, `ordering`, `matching`)
Graded in the page on **Confirm**: instant, offline, free, and never wrong. **Prefer them to `mcq` whenever the answer
is a number, a key term, a sequence or a pairing**: the student has to produce the answer instead of recognising it.
```json
{"id": "n1", "type": "numeric", "question": "g at sea level?", "answer": 9.81, "tolerance": 0.05, "unit": "m/s²", "...": "..."}
{"id": "c1", "type": "cloze", "question": "Complete the sentence.", "text": "ATP is made in the ___ by ___.",
 "answer": [["mitochondria", "mitochondrion"], {"accept": ["oxidative phosphorylation"], "regex": "ox(idative)? ?phos.*"}]}
{"id": "c2", "type": "cloze", "question": "Fill in the loop.", "text": "for i in ___(n):\n    print(i)", "answer": ["range"], "monospace": true}
{"id": "o1", "type": "ordering", "question": "Order the phases of mitosis.", "answer": ["Prophase", "Metaphase", "Anaphase", "Telophase"]}
{"id": "m1", "type": "matching", "question": "Match each organelle to its job.",
 "answer": [["Mitochondrion", "Makes ATP"], ["Ribosome", "Builds proteins"]], "distractors": ["Stores lipids"]}
```
- `numeric`: `answer` is a number. `tolerance` is absolute (`0.05`) or relative (`"2%"`); without it the student must
  match to the answer's last decimal place (9.81 accepts 9.805–9.815), so set it from the source's precision. `unit` is
  shown next to the box; the student types only the number. Accepted input: `3,5` or `3.5`, `1e-3`, `3/4`, `1 000`
  (a comma followed by exactly 3 digits is a thousands separator).
- `cloze`: `text` is the passage (Markdown inline), one `___` per blank; `answer[i]` is an accepted string, a list of
  them, or `{"accept": [...], "regex"?: "...", "case_sensitive"?: false}` (the regex must match the whole input).
  Matching ignores case, accents, extra spaces and surrounding punctuation. Blank the key terms, not filler words; 1–3
  blanks per item; list every common spelling and synonym. `"monospace": true` shows the passage as code.
- `ordering`: `answer` is the correct order (2–10 unique entries). The player shuffles it (never already solved) and
  the student moves rows up and down. Use real sequences: steps of a process, events in time, algorithm passes.
- `matching`: `answer` pairs `[left, right]`; lefts are unique, a right may repeat. Each left gets a dropdown of all
  rights plus `distractors` (add 1–2 plausible ones so the last pick isn't free). Keep it to 3–6 pairs.
- `result` is all-or-nothing (mastery stays simple), and feedback marks each blank / position / pair; the report adds
  `partial: {"right": 2, "total": 3}`. These are always `graded: "auto"`, never sent to a grader.

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
- Quiz `result`: `correct` | `wrong` | `pending`; `graded` is `auto` (choice items), `self`, `agent` or `claude`
  for short/code answers (`given` is the student's draft). `pending` means waiting for the agent; it carries no
  mastery signal. Agent-graded items gain `feedback`, optional `points`, and `met` / `note` on rubric criteria.

**Served mode.** Opened through `eztudy serve`, the player posts the report itself when the session ends (it is
imported at once). A quiz with short/code answers then waits on the results screen while a grader returns verdicts
through `eztudy report grade <session> -`:
```json
{"items": [{"id": "q2", "result": "correct", "feedback": "Right: ATP carries energy."},
           {"id": "q3", "result": "wrong", "points": 1, "feedback": "Misses the empty-list case.",
            "rubric": [{"index": 0, "met": true}, {"index": 1, "met": false, "note": "no check for []"}]}]}
```
One verdict per pending item; rubric criteria by 0-based `index` (or `id`). Graders: headless `claude -p` on a
cheap model first (default `haiku`, no tools, no API key; `[grading] model = "…"` picks the model,
`[grading] command = [...]` replaces it, `[grading] fallback = "none"` disables it), else the agent session blocked
in `eztudy report wait`. The server exits by itself about 2 minutes after the last player tab closes (`[grading]
linger_s`) while nothing is being graded, or after 2 hours with no requests. Files under
`.eztudy/progress/grading/` track each session (`job` → `claimed` → `result` / `failed`).
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
