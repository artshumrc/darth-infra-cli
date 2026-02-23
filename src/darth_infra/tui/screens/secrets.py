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
    SelectionList,
    Static,
)

from ..step_rail import StepRail


class SecretsScreen(Screen):
    """Configure additional secrets (env vars injected into containers)."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_index: int | None = None
        self._expose_to: list[str] = []

    def _draft(self) -> dict:
        d = self._state.setdefault("_wizard_draft", {})
        return d.setdefault("secrets", {})

    def _service_names(self) -> list[str]:
        names: list[str] = []
        for svc in self._state.get("services", []):
            name = str(svc.get("name", "")).strip()
            if not name or name in names:
                continue
            names.append(name)
        return names

    def compose(self) -> ComposeResult:
        draft = self._draft()
        expose_draft = {str(v) for v in draft.get("sec_expose_to", [])}
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Added Secrets", classes="title")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield StepRail("secrets")
                yield Static("Secret Details (Optional)", classes="title")

                yield Label("Secret name (env var):", classes="section-label")
                yield Input(
                    placeholder="DJANGO_SECRET_KEY",
                    id="sec_name",
                    value=str(draft.get("sec_name", "")),
                )

                yield Label("Source:", classes="section-label")
                with RadioSet(id="sec_source"):
                    yield RadioButton(
                        "Generate (random value)",
                        value=draft.get("sec_source", "generate") == "generate",
                        id="src_gen",
                    )
                    yield RadioButton(
                        "Environment variable",
                        value=draft.get("sec_source", "generate") == "env",
                        id="src_env",
                    )

                yield Label("Length (for generated):", classes="section-label")
                yield Input(
                    placeholder="50",
                    id="sec_length",
                    value=str(draft.get("sec_length", "50")),
                )

                yield Label("Expose to services:", classes="section-label")
                yield Static(
                    "No services yet. Add services first, then return here.",
                    id="sec-expose-empty",
                )
                yield SelectionList[str](id="sec-expose-services")

                with Vertical(classes="button-row"):
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")

    def on_mount(self) -> None:
        self._restore_from_draft()
        self._refresh_expose_services()
        self._refresh_sidebar()
        self._update_mode()

    def _restore_from_draft(self) -> None:
        draft = self._draft()
        if isinstance(draft.get("sec_expose_to"), list):
            self._expose_to = [str(v) for v in draft.get("sec_expose_to", [])]

    def _capture_draft(self) -> None:
        self._expose_to = self._read_expose_checkboxes()
        radio_set = self.query_one("#sec_source", RadioSet)
        pressed = radio_set.pressed_button
        source = "env" if pressed and pressed.id == "src_env" else "generate"
        self._draft().update(
            {
                "sec_name": self.query_one("#sec_name", Input).value,
                "sec_source": source,
                "sec_length": self.query_one("#sec_length", Input).value,
                "sec_expose_to": list(self._expose_to),
            }
        )

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_radio_set_changed(self, _event: RadioSet.Changed) -> None:
        self._capture_draft()

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
            self._expose_to = [str(s) for s in secret.get("expose_to", [])]
            self._refresh_expose_services()
            # Select the correct radio button
            if secret.get("source") == "env":
                self.query_one("#src_env", RadioButton).value = True
                self.query_one("#src_gen", RadioButton).value = False
            else:
                self.query_one("#src_gen", RadioButton).value = True
                self.query_one("#src_env", RadioButton).value = False
            self._update_mode()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return
        if event.button.id == "back":
            self._state["_wizard_last_screen"] = "s3"
            self.app.pop_screen()
        elif event.button.id == "add":
            self._add_secret()
        elif event.button.id == "save":
            self._save_secret()
        elif event.button.id == "remove":
            self._remove_secret()
        elif event.button.id == "next":
            self._persist_for_navigation()
            self.app.advance_to("review")

    def before_step_navigation(self, _target: str) -> bool:
        self._persist_for_navigation()
        return True

    def _persist_for_navigation(self) -> None:
        self._capture_draft()
        name = self.query_one("#sec_name", Input).value.strip()
        if self._editing_index is not None:
            self._save_secret()
        elif name:
            self._add_secret()

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
        self._expose_to = self._read_expose_checkboxes()

        return {
            "name": name,
            "source": source,
            "length": length,
            "generate_once": True,
            "expose_to": list(self._expose_to),
        }

    def _read_expose_checkboxes(self) -> list[str]:
        selection = self.query_one("#sec-expose-services", SelectionList)
        return [str(v) for v in selection.selected]

    def _refresh_expose_services(self) -> None:
        service_names = self._service_names()
        selected = set(self._expose_to)
        empty = self.query_one("#sec-expose-empty", Static)
        selection = self.query_one("#sec-expose-services", SelectionList)
        selection.clear_options()
        if service_names:
            selection.add_options(
                [(name, name, name in selected) for name in service_names]
            )
            selection.display = True
            empty.display = False
        else:
            selection.display = False
            empty.display = True

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
        self.query_one("#src_gen", RadioButton).value = True
        self.query_one("#src_env", RadioButton).value = False
        self._expose_to = []
        self._refresh_expose_services()
        self._update_mode()
