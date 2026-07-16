# Quickstart

## Run the server

```sh
uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
```

## Open in an external desktop browser

- Go to http://localhost:$WEBSITE_EXTERNAL_PORT
  - e.g. http://localhost:11110/
- To preview different screen sizes, press `Ctrl+Shift+M` in the browser's
  developer tools

# Other commands

## Normalize line endings to LF

- `fdfind --type file --exec dos2unix {}`
- `git add --renormalize .`

## Claude

- `claude --version`
- `claude /login`
- `claude -p "Reply exactly: OK"`
