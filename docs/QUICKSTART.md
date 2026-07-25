# Quickstart

## Run the server

### Direct

- Open a terminal and run the following command

```sh
uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload
```

- Open an external desktop browser (in your host)
  - Go to `http://localhost:$WEBSITE_EXTERNAL_PORT`
    - e.g. <http://localhost:11110/>

### Through Caddy (reverse proxy)

- Open a terminal and run the following command

```sh
uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "$WEBSITE_INTERNAL_PORT_WITH_REVERSE_PROXY" \
  --reload \
  --root-path "$WEBSITE_REVERSE_PROXY_ROOT_PATH" \
  --proxy-headers \
  --forwarded-allow-ips="*"
```

- Open an external desktop browser (in your host)
  - Go to `https://proxy.localhost:$WEBSITE_EXTERNAL_HTTPS_PORT_WITH_REVERSE_PROXY$WEBSITE_REVERSE_PROXY_ROOT_PATH/`
    - e.g. <https://proxy.localhost:11121/prefix/>

## Good to know

- Interactive API docs (Swagger UI): `<url>/docs` is a dev tool and is only
  served when `WEBSITE_ENABLE_DOCS=1`, which the dev container sets by default.
  Therefore don't set it in production!
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
