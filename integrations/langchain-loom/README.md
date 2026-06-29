# langchain-loom

LangChain memory integration for **Loom OS** — the unified agent memory fabric.

## Install

```bash
pip install langchain-loom
```

## Quick Start

```python
from langchain_loom import LoomMemory
from langchain.chains import ConversationChain
from langchain_openai import ChatOpenAI

memory = LoomMemory(
    project="my-app",
    agent="langchain-agent",
    project_path="/path/to/project",
)

chain = ConversationChain(
    llm=ChatOpenAI(),
    memory=memory,
)

response = chain.predict(input="What does the auth module do?")
```

## How It Works

- **`save_context`** writes a finding to `~/.loom/inbox/<project>/` — the daemon processes it, runs extractors, and regenerates the shared context.
- **`load_memory_variables`** reads `SHARED_CONTEXT.md` from the project directory, giving the agent the full knowledge graph overview, recent findings, and agent roster.
- **`clear`** is a no-op — Loom findings are durable (they persist across sessions).

## Why Loom Memory?

- **Multi-agent**: findings written by this agent are visible to all other agents (Claude Code, Codex, etc.)
- **Local-first**: no cloud, no API — writes to the local filesystem
- **Knowledge graph**: the daemon builds and queries a code-graph from your project
