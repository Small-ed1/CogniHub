#!/usr/bin/env python3
"""
Router Phase 1 - Terminal User Interface (TUI)
Full-featured CLI/TUI with same functionality as web GUI.
"""

import asyncio, sys, os, json
from datetime import datetime
import httpx

from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Static, Input, Button,
    DataTable, Tabs, Tab, RichLog
)
from textual.binding import Binding
from rich.text import Text

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")

# State as a dictionary wrapper
_state = {
    "current_chat_id": None,
    "chats": [],
    "messages": [],
    "docs": [],
    "models": [],
    "current_model": ""
}

def get_state(key, default=None):
    return _state.get(key, default)

def set_state(key, value):
    _state[key] = value

# API functions
async def api_get(path):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API_BASE}{path}")
        r.raise_for_status()
        return r.json()

async def api_post(path, data=None, json=None):
    async with httpx.AsyncClient(timeout=60) as client:
        if json is not None:
            r = await client.post(f"{API_BASE}{path}", json=json)
        elif data is not None:
            r = await client.post(f"{API_BASE}{path}", data=data)
        else:
            r = await client.post(f"{API_BASE}{path}")
        r.raise_for_status()
        return r.json()

# Format messages
def format_message(msg):
    role = msg.get("role", "").upper()
    content = msg.get("content", "")
    ts = msg.get("created_at", "")
    model = msg.get("model", "")
    
    role_colors = {
        "USER": "bold blue",
        "ASSISTANT": "bold green",
        "SYSTEM": "bold yellow"
    }
    color = role_colors.get(role, "dim")
    
    timestamp = ""
    if ts:
        dt = datetime.fromtimestamp(ts)
        timestamp = dt.strftime("%H:%M")
    
    header = f"[{color}]{role}[/{color}] [{timestamp}]"
    if model:
        header = header + f" ({model})"
    
    return f"{header}\n{content}\n"

# Sidebar
class Sidebar(Vertical):
    def __init__(self, main_screen):
        super().__init__(id="sidebar")
        self.main = main_screen

    def compose(self):
        yield Tabs(
            Tab("Chats", id="tab-chats"),
            Tab("Help", id="tab-help"),
        )
        yield Vertical(id="sidebar-content")

    async def on_mount(self):
        await self.refresh_content()

    async def refresh_content(self):
        from typing import cast
        from textual.widgets import Tabs as TabsWidget
        content = self.query_one("#sidebar-content")
        if not content:
            return
        content.remove_children()
        tabs = cast(TabsWidget, self.query_one("Tabs"))
        if not tabs:
            return
        active = tabs.active
        if active == "tab-chats":
            await self._render_chats(content)
        elif active == "tab-help":
            await self._render_help(content)

    async def _render_chats(self, container):
        container.mount(Static("[bold]Chats[/bold]", classes="header"))
        chats = get_state("chats", [])
        current_id = get_state("current_chat_id")
        
        table = DataTable()
        table.add_column("Title", key="title")
        table.add_column("Status", key="status", width=20)
        rows = []
        for chat in chats[:25]:
            is_current = chat.get("id") == current_id
            marker = "* " if is_current else "  "
            title = f"[cyan]{marker}[/cyan]{chat.get('title', 'Untitled')}"
            status_parts = []
            if chat.get("archived"):
                status_parts.append("[dim]A[/dim]")
            if chat.get("pinned"):
                status_parts.append("[yellow]P[/yellow]")
            rows.append({
                "title": title,
                "status": " ".join(status_parts) or "Active"
            })
        table.add_rows(rows)
        container.mount(table)

    async def _render_help(self, container):
        help_text = """
[bold]Slash Commands:[/bold]

 [cyan]/find <query>[/cyan]       Search current chat
 [cyan]/search <query>[/cyan]      Search all chats
 [cyan]/pin[/cyan]                  Toggle chat pin
 [cyan]/archive[/cyan]               Toggle archive
 [cyan]/summary[/cyan]               Generate summary
 [cyan]/jump <msg_id>[/cyan]        Jump to message
 [cyan]/status[/cyan]                Show system status
 [cyan]/clear[/cyan]                 Clear current chat
 [cyan]/help[/cyan]                  Show this help

[bold]Keys:[/bold]
  [cyan]Ctrl+Q:[/cyan] Quit            [cyan]Ctrl+N:[/cyan] New Chat
  [cyan]Ctrl+S:[/cyan] Toggle Sidebar  [cyan]F5:[/cyan] Refresh
  [cyan]Ctrl+T:[/cyan] Switch Tab
"""
        container.mount(Static(help_text))

# Main Screen
class MainScreen(Screen):
    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+s", "toggle_sidebar", "Toggle Sidebar"),
        Binding("f5", "refresh", "Refresh"),
        Binding("ctrl+n", "new_chat", "New Chat"),
        Binding("ctrl+t", "next_tab", "Next Tab"),
    ]

    def __init__(self, app):
        super().__init__()
        self.is_generating = False

    def compose(self):
        yield Header()
        with Horizontal():
            yield Sidebar(self)
            with Vertical():
                yield ChatMessages(id="messages")
                yield ChatInput(id="input")
        yield Footer()

    async def on_mount(self):
        await self.load_models()
        await self.load_chats()
        chats = get_state("chats", [])
        if chats and not get_state("current_chat_id"):
            set_state("current_chat_id", chats[0].get("id"))
        current_id = get_state("current_chat_id")
        if current_id:
            await self.load_chat(current_id)
        self.query_one("#input").focus()

    async def load_models(self):
        try:
            data = await api_get("/api/models")
            models = data.get("models", [])
            set_state("models", models)
            if models and not get_state("current_model"):
                set_state("current_model", models[0])
            elif not models:
                self.app.notify("No models available - check Ollama", severity="warning")
        except Exception as e:
            self.app.notify(f"Failed to load models: {e}", severity="error")

    async def load_chats(self):
        from typing import cast
        try:
            data = await api_get("/api/chats")
            set_state("chats", data.get("chats", []))
            sidebar = cast(Sidebar, self.query_one("#sidebar"))
            if sidebar:
                await sidebar.refresh_content()
        except Exception as e:
            self.app.notify(f"Failed to load chats: {e}", severity="error")

    async def load_chat(self, chat_id):
        try:
            data = await api_get(f"/api/chats/{chat_id}")
            set_state("messages", data.get("messages", []))
            set_state("current_chat_id", chat_id)
            self.refresh_messages()
        except Exception as e:
            self.app.notify(f"Failed to load chat: {e}", severity="error")

    def refresh_messages(self):
        from typing import cast
        messages = cast(ChatMessages, self.query_one("#messages"))
        if messages:
            messages.clear()
            msgs = get_state("messages", [])
            for msg in msgs:
                messages.write(format_message(msg))
            messages.scroll_end()

    async def on_new_chat(self):
        try:
            data = await api_post("/api/chats", json={"title": "New Chat"})
            new_chat = data.get("chat", {})
            chats = get_state("chats", [])
            chats.insert(0, new_chat)
            set_state("chats", chats)
            set_state("current_chat_id", new_chat.get("id"))
            set_state("messages", [])
            self.refresh_messages()
            from typing import cast
            sidebar = cast(Sidebar, self.query_one("#sidebar"))
            if sidebar:
                await sidebar.refresh_content()
        except Exception as e:
            self.app.notify(f"Failed to create chat: {e}", severity="error")

    async def send_message(self, text):
        global _state
        text = text.strip()
        if not text:
            return
        if self.is_generating:
            self.app.notify("Please wait for current response to complete", severity="warning")
            return

        if text.startswith("/"):
            await self.handle_slash_command(text)
            return

        self.is_generating = True
        from typing import cast
        messages = cast(ChatMessages, self.query_one("#messages"))
        
        messages.write(format_message({
            "role": "user",
            "content": text,
            "created_at": int(datetime.now().timestamp())
        }))
        messages.scroll_end()

        current_model = get_state("current_model", "")
        msgs = get_state("messages", [])
        
        try:
            await api_post(f"/api/chats/{get_state('current_chat_id')}/append", json={
                "messages": [{"role": "user", "content": text, "model": current_model}]
            })
        except Exception as e:
            self.app.notify(f"Failed to save message: {e}", severity="error")

        messages.write("[bold green]ASSISTANT[/bold green] [dim](thinking...)[/dim]\n")
        messages.scroll_end()

        assistant_content = ""
        try:
            messages_to_send = []
            for m in msgs[-40:]:
                if m.get("role") in ("user", "assistant"):
                    messages_to_send.append({"role": m.get("role"), "content": m.get("content")})
            messages_to_send.append({"role": "user", "content": text})

            payload = {
                "model": current_model,
                "messages": messages_to_send,
                "options": {
                    "temperature": 0.7,
                    "num_ctx": 4096
                },
                "keep_alive": "5m",
                "rag": {
                    "enabled": False,
                    "top_k": 6,
                    "doc_ids": None,
                    "use_mmr": False,
                    "mmr_lambda": 0.75
                }
            }

            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("POST", f"{API_BASE}/api/chat", json=payload) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if line.strip():
                            try:
                                data = json.loads(line)
                                if data.get("type") == "error":
                                    raise Exception(data.get("error", "Unknown error"))
                                if data.get("type") == "sources":
                                    sources = data.get("sources", [])
                                    if sources:
                                        messages.write(f"[dim cyan]Using {len(sources)} source(s) from knowledge base[/dim cyan]\n")
                                        messages.scroll_end()
                                    continue
                                message = data.get("message", {})
                                content = message.get("content", "")
                                if content:
                                    assistant_content += content
                                    messages.write(content)
                                    messages.scroll_end()
                            except json.JSONDecodeError:
                                pass
                            except Exception as e:
                                raise

        except Exception as e:
            error_msg = str(e)
            if "connection" in error_msg.lower() or "timeout" in error_msg.lower():
                error_msg = "Connection error - check if Ollama is running and accessible"
            elif "model" in error_msg.lower():
                error_msg = f"Model error - check if model is available: {error_msg}"
            else:
                error_msg = f"Chat error: {error_msg}"

            self.app.notify(error_msg, severity="error")
            assistant_content += f"\n\n[red]Error: {error_msg}[/red]"

        msgs.append({
            "role": "assistant",
            "content": assistant_content,
            "model": current_model
        })

        try:
            await api_post(f"/api/chats/{get_state('current_chat_id')}/append", json={
                "messages": [{"role": "assistant", "content": assistant_content, "model": current_model}]
            })
            await self.load_chats()
        except Exception as e:
            self.app.notify(f"Failed to save response: {e}", severity="error")

        self.is_generating = False
        messages.scroll_end()

    async def handle_slash_command(self, text):
        global _state
        from typing import cast
        parts = text.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        messages = cast(ChatMessages, self.query_one("#messages"))

        try:
            if cmd == "/find":
                if not rest:
                    self.app.notify("Usage: /find <query>", severity="warning")
                    return
                data = await api_get(f"/api/chats/{get_state('current_chat_id')}/search?q={rest}&limit=25")
                hits = data.get("hits", [])
                if hits:
                    messages.write(f"[cyan]**/find** results for '{rest}' ({len(hits)}):[/cyan]\n\n")
                    for h in hits[:10]:
                        ts = datetime.fromtimestamp(h.get('created_at', 0)).strftime('%H:%M')
                        messages.write(f"- #{h.get('msg_id')} [bold]{h.get('role')}[/bold] @ {ts} — {h.get('snippet')}\n")
                    messages.scroll_end()
                else:
                    self.app.notify(f"No hits for: {rest}", severity="information")

            elif cmd == "/search":
                if not rest:
                    self.app.notify("Usage: /search <query>", severity="warning")
                    return
                data = await api_get(f"/api/search?q={rest}&limit=25")
                hits = data.get("hits", [])
                if hits:
                    messages.write(f"[cyan]**/search** results for '{rest}' ({len(hits)}):[/cyan]\n\n")
                    for h in hits[:10]:
                        messages.write(f"- [bold]{h.get('chat_title')}[/bold] (#{h.get('msg_id')}) [bold]{h.get('role')}[/bold] — {h.get('snippet')}\n")
                    messages.scroll_end()
                else:
                    self.app.notify(f"No hits for: {rest}", severity="information")

            elif cmd == "/pin":
                data = await api_post(f"/api/chats/{get_state('current_chat_id')}/toggle_pin")
                await self.load_chats()
                self.app.notify(f"Pinned: {data.get('pinned', False)}", severity="information")

            elif cmd == "/archive":
                data = await api_post(f"/api/chats/{get_state('current_chat_id')}/toggle_archive")
                await self.load_chats()
                self.app.notify(f"Archived: {data.get('archived', False)}", severity="information")

            elif cmd == "/summary":
                data = await api_post(f"/api/chats/{get_state('current_chat_id')}/summary")
                summary = data.get("summary", "")
                messages.write(f"[cyan]{summary}[/cyan]\n")
                messages.scroll_end()

            elif cmd == "/jump":
                msg_id_str = rest.strip()
                if not msg_id_str or not msg_id_str.isdigit():
                    self.app.notify("Usage: /jump <msg_id>", severity="warning")
                    return
                msg_id = int(msg_id_str)
                data = await api_get(f"/api/chats/{get_state('current_chat_id')}/jump?msg_id={msg_id}&span=20")
                set_state("messages", data.get("messages", []))
                self.refresh_messages()

            elif cmd == "/help":
                from typing import cast
                from textual.widgets import Tabs as TabsWidget
                sidebar = cast(Sidebar, self.query_one("#sidebar"))
                if sidebar:
                    tabs = cast(TabsWidget, sidebar.query_one("Tabs"))
                    if tabs:
                        tabs.active = "tab-help"
                        await sidebar.refresh_content()

            elif cmd == "/status":
                try:
                    status = await api_get("/health")
                    messages.write(f"[cyan]System Status:[/cyan]\n")
                    messages.write(f"CPU: {status.get('system', {}).get('cpu_percent', 'N/A')}%\n")
                    messages.write(f"Memory: {status.get('system', {}).get('memory_percent', 'N/A')}%\n")
                    ollama_ok = status.get('services', {}).get('ollama', {}).get('ok', False)
                    messages.write(f"Ollama: {'OK' if ollama_ok else 'DOWN'}\n")
                    messages.scroll_end()
                except Exception as e:
                    messages.write(f"[red]Status check failed: {e}[/red]\n")
                    messages.scroll_end()

            elif cmd == "/clear":
                if await self.confirm_action("Clear all messages in this chat?"):
                    try:
                        await api_post(f"/api/chats/{get_state('current_chat_id')}/clear", json={})
                        set_state("messages", [])
                        self.refresh_messages()
                        messages.write("[green]Chat cleared[/green]\n")
                        messages.scroll_end()
                    except Exception as e:
                        messages.write(f"[red]Failed to clear chat: {e}[/red]\n")
                        messages.scroll_end()

            else:
                self.app.notify(f"Unknown command: {cmd}", severity="error")
                messages.write(f"[red]Unknown command: {cmd}. Type /help for commands.[/red]\n")
                messages.scroll_end()

        except Exception as e:
            self.app.notify(f"Command failed: {e}", severity="error")
            messages.write(f"[red]Error: {e}[/red]\n")
            messages.scroll_end()

    def action_quit(self):
        self.app.exit()

    def action_toggle_sidebar(self):
        from typing import cast
        sidebar = cast(Sidebar, self.query_one("#sidebar"))
        if sidebar:
            if sidebar.display:
                sidebar.display = False
            else:
                sidebar.display = True

    def action_refresh(self):
        asyncio.create_task(self.load_chats())

    def action_new_chat(self):
        asyncio.create_task(self.on_new_chat())

    def action_next_tab(self):
        from typing import cast
        from textual.widgets import Tabs as TabsWidget
        sidebar = cast(Sidebar, self.query_one("#sidebar"))
        if sidebar:
            tabs = cast(TabsWidget, sidebar.query_one("Tabs"))
            if tabs:
                current = tabs.active
                new_tab = "tab-chats" if current == "tab-help" else "tab-help"
                tabs.active = new_tab
                asyncio.create_task(sidebar.refresh_content())

    async def confirm_action(self, message: str) -> bool:
        """Simple confirmation - for now just return True."""
        # In a full implementation, this would show a modal dialog
        return True

# Widgets
class ChatMessages(RichLog):
    def on_mount(self):
        self.auto_scroll = True

class ChatInput(Input):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.placeholder = "Type a message (use / for commands)..."

    async def on_submit(self):
        text = self.value
        self.value = ""
        if text:
            screen = self.app.screen
            if isinstance(screen, MainScreen):
                await screen.send_message(text)

# Main App
class RouterTUI(App):
    CSS = """
    #messages {
        height: 1fr;
        border: solid $primary;
        background: $background;
    }
    #input {
        height: 3;
        dock: bottom;
    }
    #sidebar {
        width: 40;
        border: solid $primary;
        background: $surface;
    }
    .header {
        text-style: bold;
        padding: 0 1;
        background: $panel;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def on_mount(self):
        self.push_screen(MainScreen(self))

def main():
    app = RouterTUI()
    app.run()

if __name__ == "__main__":
    main()
