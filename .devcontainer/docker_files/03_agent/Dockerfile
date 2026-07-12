# Use the locally built image (see ../README.md for the build order)
FROM fastapi-website-blueprint-dev-image

# The agent CLIs float deliberately: they self-update, their vendors only
# support the current release, and there is no lockfile Dependabot could bump.

# Install Claude Code
RUN curl -fsSL https://claude.ai/install.sh | bash

# Install OpenAI Codex
RUN curl -fsSL https://chatgpt.com/codex/install.sh | sh

# Claude CLI is installed in /root/.local/bin/claude
ENV PATH="/root/.local/bin:${PATH}"
