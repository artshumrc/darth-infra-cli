"""Secrets configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    RadioButton,
    RadioSet,
    Static,
)


class SecretsScreen(Screen):
    """Configure additional secrets (env vars injected into containers)."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_index: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Added Secrets", classes="title")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield Static("Secret Details (Optional)", classes="title")

                yield Label("Secret name (env var):", classes="section-label")
                yield Input(placeholder="DJANGO_SECRET_KEY", id="sec_name")

                yield Label("Source:", classes="section-label")
                with RadioSet(id="sec_source"):
                    yield RadioButton(
                        "Generate (random value)", value=True, id="src_gen"
                    )
                    yield RadioButton("Environment variable", id="src_env")

                yield Label("Length (for generated):", classes="section-label")
                yield Input(placeholder="50", id="sec_length", value="50")

                with Vertical(classes="button-row"):
                    yield Button("← Back", id="back", variant="default")
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")
                    yield Button("Next →", id="next", variant="primary")

    def on_mount(self) -> None:
        self._refresh_sidebar()
        self._update_mode()

    def _refresh_sidebar(self) -> None:
        """Rebuild the sidebar list from current state."""
        lv = self.query_one("#item-list", ListView)
        lv.clear()
        for secret in self._state.get("secrets", []):
            lv.append(ListItem(Static(secret["name"])))

    def _update_mode(self) -> None:
        """Toggle button visibility based on add vs edit mode."""
        editing = self._editing_index is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Load a secret into the form for editing."""
        idx = event.list_view.index
        secrets = self._state.get("secrets", [])
        if idx is not None and idx < len(secrets):
            self._editing_index = idx
            secret = secrets[idx]
            self.query_one("#sec_name", Input).value = secret.get("name", "")
            self.query_one("#sec_length", Input).value = str(secret.get("length", 50))
            # Select the correct radio button
            radio_set = self.query_one("#sec_source", RadioSet)
            if secret.get("source") == "env":
                radio_set.pressed_index = 1
            else:
                radio_set.pressed_index = 0
            self._update_mode()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "add":
            self._add_secret()
        elif event.button.id == "save":
            self._save_secret()
        elif event.button.id == "remove":
            self._remove_secret()
        elif event.button.id == "next":
            name = self.query_one("#sec_name", Input).value.strip()
            if name and self._editing_index is None:
                self._add_secret()
            self.app.advance_to("review")

    def _read_form(self) -> dict | None:
        """Read and validate the form fields."""
        name = self.query_one("#sec_name", Input).value.strip()
        if not name:
            self.notify("Secret name is required", severity="error")
            return None

        radio_set = self.query_one("#sec_source", RadioSet)
        pressed = radio_set.pressed_button
        source = "env" if pressed and pressed.id == "src_env" else "generate"

        length = int(self.query_one("#sec_length", Input).value.strip() or "50")

        return {
            "name": name,
            "source": source,
            "length": length,
            "generate_once": True,
        }

    def _add_secret(self) -> None:
        secret = self._read_form()
        if secret is None:
            return
        self._state.setdefault("secrets", []).append(secret)
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Added secret '{secret['name']}'")

    def _save_secret(self) -> None:
        if self._editing_index is None:
            return
        secret = self._read_form()
        if secret is None:
            return
        self._state["secrets"][self._editing_index] = secret
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Updated secret '{secret['name']}'")

    def _remove_secret(self) -> None:
        if self._editing_index is None:
            return
        name = self._state["secrets"][self._editing_index]["name"]
        del self._state["secrets"][self._editing_index]
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Removed secret '{name}'")

    def _clear_form(self) -> None:
        """Reset form to add mode."""
        self._editing_index = None
        self.query_one("#sec_name", Input).value = ""
        self.query_one("#sec_length", Input).value = "50"
        self._update_mode()
