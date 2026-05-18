---
name: iterate-build
description: Build the next iteration of pt-p710bt-label-gui as a .deb, install it over the current installation for Daniel to review, and prep for the next round of feedback. Use this for every dev cycle on this repo.
---

# iterate-build

Daniel's preferred dev procedure on this repo is **progressive Debian iterations**: each round of feedback produces a new `.deb`, gets installed over the previous one, and he reviews it on his desktop. Releases are cut only when explicitly requested.

## When to invoke

- After any code change Daniel wants to try out ("install it", "let me see it", "build the next one", etc.)
- Whenever a feedback round closes and a new iteration begins
- NOT for tiny mid-flight tweaks while still drafting — wait until the change is coherent enough to look at

## Procedure (in order, no asking)

1. **Bump the version.** Pre-release iterations bump the Debian revision only:
   - `0.1.0-1` → `0.1.0-2` → `0.1.0-3` …
   - Bump the upstream version (`0.1.0` → `0.2.0`) only when Daniel says "cut a release" or when the change is large enough that he asks for it.
   - Update `debian/changelog` with `dch -i` style entries — one bullet per visible change. Use today's date (Jerusalem time, IST/IDT). Distribution stays `unstable`.
   - Keep `pyproject.toml`'s `version` in sync with the **upstream** part of the Debian version.

2. **Build the .deb:**
   ```
   dpkg-buildpackage -us -uc -b
   ```
   The output lands in the parent directory: `../pt-p710bt-label-gui_<version>_all.deb`.

3. **Install over the current installation:**
   ```
   sudo dpkg -i ../pt-p710bt-label-gui_<version>_all.deb
   ```
   `dpkg -i` upgrades in place — no need to remove first. If dependencies fail, fix `debian/control` and retry (don't `--force` past missing deps).

4. **Smoke-test** by launching headless to confirm no import / Qt startup errors:
   ```
   QT_QPA_PLATFORM=offscreen timeout 3 pt-p710bt-label-gui ; true
   ```
   Exit 143 (SIGTERM from timeout) = success. Any other non-zero exit = investigate before reporting done.

5. **Commit and push** the version bump + code in one commit:
   - Stage everything (`git add -A`)
   - Commit message: `vX.Y.Z-N: <one-line summary of what changed in this iteration>`
   - Push immediately (per Daniel's global git rules).

6. **Report back to Daniel** with:
   - New version string
   - `.deb` filename (just the basename)
   - One-line per change in this iteration
   - Prompt: "Installed — ready for your feedback."

## When Daniel says "cut a release"

1. Bump the upstream version (e.g. `0.1.0-3` → `0.2.0-1`). Sync `pyproject.toml`.
2. Add a release entry to `debian/changelog` summarising the release (not per-iteration churn).
3. Build the .deb, install it, smoke-test as above.
4. Tag the commit: `git tag -a v<upstream-version> -m "Release v<upstream-version>"` and push the tag (`git push --tags`).
5. Create a GitHub release with `gh release create v<version> ../pt-p710bt-label-gui_<version>_all.deb --notes "<changelog excerpt>"`.
6. Reset the iteration counter — the next pre-release goes back to `-1` on the new upstream version.

## Hard rules

- **Do not ask** before any of the steps above — this is the established procedure, just run it.
- **Do not bump the upstream version** on a regular iteration. Debian revision only until "cut a release".
- **Do not skip the smoke test.** If the headless launch fails, fix it before claiming the iteration is installed.
- **Do not `--force` dpkg.** Fix the underlying packaging problem.
- **Do not leave uncommitted state** after an iteration — every install corresponds to a pushed commit.

## Files this skill touches

- `debian/changelog` — version + iteration notes
- `pyproject.toml` — `version` (only on upstream bumps)
- Any source files in `src/pt_p710bt_label_gui/` relevant to the iteration
- Commits and tags
