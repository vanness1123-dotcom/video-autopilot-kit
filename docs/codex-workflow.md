# Codex Workflow

This project works best when Codex is used as a careful engineering partner:
first for read-only orientation, then for narrow changes, and finally with a
human review before any Git operation.

## Recommended Flow

1. Fork the repository

   Create your own fork before making changes. Treat the upstream repository as
   the source of truth and keep your work isolated until it is reviewed.

2. Clone to your local machine

   Clone your fork locally and open the repository in Codex from the repository
   root.

   ```powershell
   git clone <your-fork-url>
   cd video-autopilot-kit
   ```

3. Ask Codex for read-only analysis first

   Before requesting edits, ask Codex to inspect the repository without changing
   files. A good first prompt is:

   ```text
   Please analyze this repository. Do not modify files, install packages,
   commit, or push. Identify the project purpose, structure, entry points,
   dependencies, smoke test commands, and risks.
   ```

4. Run the smoke test

   Run the Windows smoke test before making code changes. See
   `docs/windows-smoke-test.md` for the full command list.

   Minimum sequence:

   ```powershell
   $env:PYTHONIOENCODING="utf-8"
   chcp 65001
   git status --short
   python --version
   ffmpeg -version
   ffprobe -version
   python examples/02_caption_broll_match.py
   python examples/01_vertical_short.py
   ```

5. Identify environment problems

   If the smoke test fails, first decide whether the failure is caused by local
   environment setup or by repository code. Common local issues include:

   - Windows terminal output using `cp950` instead of UTF-8
   - `ffmpeg` or `ffprobe` missing from `PATH`
   - Running commands outside the repository root

6. Fix local dependencies yourself

   Fix machine-level dependencies outside the repository before asking Codex to
   change code. For example:

   - Set PowerShell UTF-8 output for the current session.
   - Add `C:\Tools\ffmpeg\bin` or your FFmpeg install path to Windows `PATH`.
   - Open a new terminal after changing `PATH`.

   Do not commit local machine setup changes into the repository unless the
   project intentionally needs documentation or configuration updates.

7. Let Codex modify documentation or code

   Once the baseline smoke test passes, ask Codex for a narrow change. Be
   explicit about the allowed files and forbidden actions.

   Example:

   ```text
   Please update only docs/windows-smoke-test.md. Do not modify other files,
   install packages, commit, or push. After editing, summarize the diff.
   ```

8. Review the diff manually

   Before staging anything, inspect the changes yourself.

   ```powershell
   git status --short
   git diff
   ```

   Check that:

   - Only expected files changed.
   - The change matches the request.
   - No generated media, temp files, personal paths, or credentials were added.
   - Smoke tests still pass when the change affects code or runtime behavior.

9. Stage, commit, and push

   After manual review, use normal Git workflow.

   ```powershell
   git add <changed-files>
   git commit -m "docs: add Windows smoke test guide"
   git push origin <branch-name>
   ```

   Keep commits focused. Avoid mixing docs, refactors, environment cleanup, and
   behavior changes in one commit.

10. Merge through a Pull Request

    Open a Pull Request from your branch or fork. Use the PR to review the
    intent, diff, smoke test result, and any known limitations before merging.

    A useful PR checklist:

    - What changed?
    - Why was it needed?
    - Which commands were run?
    - Did the smoke test pass?
    - Are there any follow-up tasks?

## Practical Rules for Codex Use

- Start with read-only analysis when entering an unfamiliar area.
- Give Codex a tight file scope when requesting edits.
- Ask Codex to stop on errors instead of guessing through environment failures.
- Keep local dependency fixes separate from repository changes.
- Always review `git diff` before `git add`.
- Let Pull Requests be the merge boundary, even for small changes.
