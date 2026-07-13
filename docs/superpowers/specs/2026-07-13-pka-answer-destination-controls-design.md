# PKA Answer Destination Controls Design

Date: 2026-07-13

Status: Approved by TZ for publishing-style implementation; functional wiring is explicitly deferred pending visual confirmation.

## Goal

Replace ambiguous post-answer controls with labels that state where an answer goes and whether it will affect future PKA retrieval.

## Confirmed Scope

- Remove the question-page `资料库` button because the shared Agent06 header already provides that destination.
- Keep `导出 Word`.
- Remove the question-page `导出 PPT` control; its backend endpoint may remain untouched in this styling-only slice.
- Replace the two ambiguous actions with three destination-specific controls:
  1. `保存到本地资料`
  2. `发布到 Obsidian`
  3. `加入 PKA 问答检索`
- Complete only the published question-page styling and static contract in this slice. Do not change the Agent06 or Agent10 persistence/indexing behavior.

## User-Facing Contract

| Control | Meaning | Styling-slice behavior |
|---|---|---|
| 导出 Word | Download a one-time Word copy. | Existing action remains enabled after a completed answer. |
| 保存到本地资料 | Save only in Agent06 local storage. | Displayed as a future destination control and disabled until its behavior is rewired to match the label. |
| 发布到 Obsidian | Publish a governed asset into the local Obsidian Vault. | Displayed and disabled; it must not call the old local-save endpoint. |
| 加入 PKA 问答检索 | Publish to Obsidian and make the answer retrievable by future PKA questions. | Displayed and disabled; it must not call the incomplete current add-generated endpoint. |

The disabled state makes the release truthful: new labels cannot accidentally activate legacy operations with different meanings.

## Visual Direction

The answer action rail is a compact destination strip, not a generic export toolbar. It uses the existing quiet pale panel and cyan outline vocabulary from the published page, but turns the actions into three readable destination groups:

```text
[ 导出 Word ] | [ 保存到本地资料 ] [ 发布到 Obsidian ] [ 加入 PKA 问答检索 ]
                local-only            Obsidian               Obsidian + RAG
```

- `导出 Word` remains visually separated as a one-off download.
- The three destination actions use direct single-line labels: `本地资料`, `Obsidian`, and `PKA 问答检索` are visible in the action text itself, so no low-contrast explanatory microcopy is needed.
- The strip uses compact 36px controls with a readable 14px label, strong dark teal text, and a clear cyan-gray border. Disabled state communicates unavailable behavior through cursor/interaction only, not faded text.
- The final action is visually strongest only after its function is implemented; in this slice every future destination control is disabled and carries an honest `功能准备中` note.
- No global Web shell, iframe framing, header, or unrelated Agent styles change.

## Deferred Functional Contract

After visual confirmation, a separate implementation slice will make the destination controls functional:

1. local save writes only Agent06 AnswerAsset storage;
2. Obsidian publication saves local source data then sends it to Agent10;
3. PKA retrieval promotion completes Obsidian publication and writes generated-secondary knowledge to FTS and vector indexes with provenance labels;
4. partial completion returns explicit local/Obsidian/indexed states; no action claims more than it completed.

## Acceptance

- The question page contains no `资料库` or `导出 PPT` action controls.
- `导出 Word` remains.
- All three destination controls use the confirmed labels and disclose their destination.
- The deferred destination controls cannot invoke the old APIs.
- Existing answer generation and Word export remain regression-tested.
