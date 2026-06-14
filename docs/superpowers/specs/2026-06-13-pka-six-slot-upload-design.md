# PKA Six Slot Upload Design

## Scope

Agent06/PKA ingest replaces the open-ended upload picker with a fixed six-slot upload board. The change is limited to the embedded PKA ingest page and does not change backend ingest APIs.

## User Problem

The current file upload area is a large generic picker followed by a list. It does not show capacity up front, and it spends too much visual area before any file is selected. A fixed slot board makes the upload limit explicit, keeps the layout stable, and makes per-file status easier to read after parsing.

## Interaction Contract

- The upload board always renders six slots.
- Empty slots show only a `+` affordance and the label `添加文件`; they must not repeat supported file formats inside each slot.
- Clicking any empty slot opens the native file picker.
- Selected slots show:
  - file type badge: `PDF`, `DOCX`, `PPTX`, `XLSX`, `TXT`, `MD`, `IMG`, or `FILE`;
  - one-line truncated filename with full name in `title`;
  - file size or upload result status;
  - a remove button.
- The maximum selected file count is six.
- When six files are selected, the file input is disabled and additional selections are ignored with the feedback text `最多上传 6 个文件，请先移除一个文件。`
- Upload submit remains disabled by behavior, not by hiding: if no files are selected, submit writes `请选择文件。`
- After upload:
  - success files show `完成`;
  - failed files show `失败`;
  - total upload summary remains in the short `file-feedback` status row;
  - if all files succeed, the slots keep the completed state instead of immediately clearing, so the user can confirm what was ingested.

## Layout Contract

- Slots use a stable `2 x 3` grid on desktop inside the existing upload pane.
- Each slot has a fixed minimum height and must not change row height because of long filenames.
- The slot board must hide horizontal overflow. Supported formats are enforced by the native file input `accept` attribute, not repeated as visible slot text.
- The upload board owns the scroll pressure; button and feedback rows stay below the board with a visible gap.
- On narrow widths, the board may become a single-column or two-column grid, but still renders six slots.

## Data Flow

- `selectedFiles` remains the source of truth for pending files.
- `fileUploadResults` remains the source of truth for per-file post-upload status.
- The frontend submits only `selectedFiles` to the existing `POST api/ingest/files` endpoint.
- No server API changes are required.

## Tests

- File contract test: ingest HTML contains `data-upload-slot-board`, `data-upload-max-files="6"`, and no large `upload-picker` label.
- File contract test: JS declares `MAX_UPLOAD_FILES = 6`, renders six upload slots, disables the input at the cap, and reports the cap feedback text.
- File contract test: CSS defines `.upload-slot-board`, `.upload-slot`, `.upload-slot.is-empty`, `.upload-slot.is-filled`, and `.upload-slot.is-complete`.
- Existing PKA tests must still pass.
