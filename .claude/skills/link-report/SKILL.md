---
name: link-report
description: Triage a Google Flights link that Fareflare refused or misread — decode it, find which check refused it, decide whether the rule is wrong or the limit is real, and fix it at the cause with the link as a test fixture. Use when someone reports "this flight link is not supported", sends a refused link or a screenshot of one, or a stored flight stops importing.
---

# A refused flight link

1. **Get the exact link.** Put it in `.fareflare/link-<name>/url.txt` (git-ignored). From a
   screenshot, type it carefully: Telegram's font draws `I` and `l` alike, and wrapped
   lines hide characters. Decode before trusting a transcription. A misread shows up as a
   token that will not decode, a text field holding a non-text byte, or a familiar value
   gone wrong (`'UOD'` where `'USD'` belongs).
2. **Decode it and run it through the importer.**

   ```bash
   PYTHONPATH=src .venv/bin/python scripts/decode_link.py .fareflare/link-<name>/url.txt
   ```

   It prints the parameters and every field of `tfs` and `tfu` (fields Fareflare does not
   read are marked), then what the importer and the collector say: the sentence people
   see, and its precise `check` and plain `reason` (the refusal vocabulary in `src/fareflare`
   maps each check to one reason).
3. **Classify the refusal.**
   - **Wrong rule:** the link prices a flight the collector can read, but a check refuses
     something that cannot change the price: what was searched (a city, several
     airports), letter case, browser or tracking parameters. Fix the rule, never the link:
     no special case for one shape. Audit the neighbouring checks for the same mistake.
   - **Real limit:** connections, cabin, passengers, currency, country, trip type. The
     refusal must name it plainly. Supporting it is collector work and needs captured
     pages, not a looser check.
   - **Broken link:** truncated or mistyped, a short link that did not open, a search with
     no flight chosen. The refusal tells the person what to copy instead.
4. **Prove a fixed rule end to end** with one live quote in the worker image, your source
   mounted over its package (newest image: `docker images fareflare-worker`):

   ```bash
   docker run --rm --platform linux/arm64 -e AWS_LAMBDA_FUNCTION_NAME=local-verify \
     -v "$PWD/src/fareflare:/var/task/fareflare:ro" --entrypoint python fareflare-worker:<tag> \
     -m fareflare.cli quote "$(cat .fareflare/link-<name>/url.txt)" \
     --chrome-binary /usr/bin/chromium --chromedriver /usr/bin/chromedriver
   ```

   `"ok": true` with `"identity_verified": true` means the page Google served re-imports
   to the same target. `provider_error` or a challenge is Google refusing the browser, not
   a verdict on the link: try once more later.
5. **Fixture and tests.** Add the link to `tests/fixtures/` as JSON with `captured_at`,
   `description` and `url` (anonymous links only; say if any part was transcribed).
   Test the outcome (accepted, or refused with the right reason) and that
   `import_link(target["url"]) == target`. Run the new tests against the old source
   (`git stash push -- <changed src files>`, run, `git stash pop`): they must fail there.
6. **Existing flights keep their identity.**
   `PYTHONPATH=src .venv/bin/python scripts/release/reimport.py` (read-only, production)
   must print `changed=0`; otherwise the change needs a migration of the listed targets.
7. `make check`, a CHANGELOG entry, push to `main`. Release with the `release` skill once
   the maintainer says to deploy, then ask the reporter to send the link again.
