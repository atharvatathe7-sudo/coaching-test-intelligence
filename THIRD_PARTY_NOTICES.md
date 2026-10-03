# Third-party notices

This product includes the following third-party software. It is not
original to this project.

## OMRChecker

- **What it is:** an optical mark recognition (OMR) engine. This product
  uses it to read marked bubbles from PNG and JPEG images of answer sheets.
- **Upstream:** https://github.com/Udayraj123/OMRChecker
- **Exact version used:** commit `5cf44a5a9c7a49e2e541c6e19aefd09a41a4d494`
  (`5cf44a5`, branch `master`, 2026-09-04, "docs: fix typo noticible ->
  noticeable (#301)").
- **Licence:** MIT, at this commit. (Upstream's tagged release `v1.1.0`
  is GPL-3.0 and is **not** used.)
- **Where:** `third_party/omrchecker/`, copied unmodified. Only `LICENSE`,
  `main.py` and `src/` (without `src/tests`) are included. Upstream's
  sample images, documentation and tests are deliberately not included.
- **Verification:** `third_party/omrchecker/UPSTREAM.json` lists the git
  blob id of every included file; `python scripts/verify_omrchecker.py`
  checks them (add `--upstream <clone>` to compare with upstream itself),
  and the test suite fails if any file changes.
- **Run as:** a separate child process (see `backend/app/omr/checker.py`),
  never imported into the web application.

Its dependencies for image input are listed, with exact versions, in
`backend/requirements-omr.txt`. PyMuPDF (AGPL-3.0 or commercial licence;
PDF input only) is deliberately **not** used.

The licence text below is reproduced from `third_party/omrchecker/LICENSE`.

---

MIT License

Copyright (c) 2024-present Udayraj Deshmukh and other contributors

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the
"Software"), to deal in the Software without restriction, including
without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to
permit persons to whom the Software is furnished to do so, subject to
the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
