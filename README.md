# Router Phase 1

An advanced AI assistant system with tool calling, routing, and research capabilities.

## Overview

Router Phase 1 provides a web-based interface for interacting with AI models, managing conversations, and performing deep research tasks. It integrates with Ollama for local model execution and supports various tools for enhanced functionality.

## Features

- **Web UI**: Chat interface with settings, sidebar for chat/model management
- **Model Support**: Integration with Ollama models (auto-fetching available models)
- **Chat Management**: Create, rename, delete, archive chats with summaries
- **Deep Research**: Multi-pass analysis with structured research flow
- **Settings**: Configurable temperature, context tokens, themes, auto-model switching
- **Tools**: File operations, web search, Kiwix integration

## Installation

1. Clone/setup the project
2. Install dependencies: `pip install -r requirements.txt`
3. Ensure Ollama is running on default host/port
4. Start services: `./start_servers.sh` or use systemd service

## Usage

- Web UI: http://localhost:8000
- Console chat: `./chat`
- Command line: `./agt run "query"`

## Current Status

- Backend: Functional with extended settings API, real model fetching, auto-model switching
- UI: Fully functional with working settings panel, sidebar navigation, chat management
- Deep Research: Backend supports, UI has research mode selection

## Development

- Environment: `make doctor` to check setup
- Linting: `make fmt`
- Testing: `make test`

## Architecture

- **Frontend**: Single-page app with vanilla JS, dynamic HTML generation
- **Backend**: FastAPI with JSON file storage
- **Models**: Ollama integration with worker classes
- **Tools**: Extensible tool system for various capabilities