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
- `answer`: 0-based option index (`mcq`), list of indices (`multi`), boolean (`true_false`), model answer string (`short`).
- MCQ: 4 options, one unambiguously correct; distractors plausible, similar length, drawn from
  related concepts in the sources; avoid "all/none of the above". Vary the correct position.
- `explanation`: why the answer is right *and* why the tempting distractor is wrong.

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
- `tags` drive the deck filter in the player — use topic names.

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
