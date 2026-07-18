# Quickstart

## Run the server

```sh
uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
```

## Open in an external desktop browser

- Go to `http://localhost:$WEBSITE_EXTERNAL_PORT`
  - e.g. <http://localhost:11110/>
- Interactive API docs (Swagger UI): `http://localhost:$WEBSITE_EXTERNAL_PORT/docs`
  - A dev tool: only served when `WEBSITE_ENABLE_DOCS=1`, which the dev
    container sets by default - don't set it in production
- To preview different screen sizes, press `Ctrl+Shift+M` in the browser's
  developer tools

## Other commands

- [Test & Lint](TEST_AND_LINT.md)
- [Cheatsheet](CHEATSHEET.md)

### Normalize line endings to LF

- `fdfind --type file --exec dos2unix {}`
- `git add --renormalize .`

### Claude

- `claude --version`
- `claude /login`
- `claude -p "Reply exactly: OK"`
