"""Environment-level resource tag configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static

from ..step_rail import StepRail


class TagsScreen(Screen):
    """Configure arbitrary tags for a selected environment."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_key: str | None = None
        self._selected_env = self._initial_env()
        self._tag_keys: list[str] = []
        self._env_button_ids = {
            f"env_select_{index}": env_name
            for index, env_name in enumerate(self._environment_names())
        }

    def _draft(self) -> dict:
        draft = self._state.setdefault("_wizard_draft", {})
        return draft.setdefault("tags", {})

    def _environment_names(self) -> list[str]:
        names = [str(env).strip() for env in self._state.get("environments", [])]
        return [name for name in names if name] or ["prod"]

    def _initial_env(self) -> str:
        draft_env = str(self._draft().get("selected_env", "")).strip()
        env_names = self._environment_names()
        if draft_env in env_names:
            return draft_env
        return env_names[0]

    def _environment_override(self, env_name: str) -> dict:
        overrides = self._state.setdefault("environment_overrides", {})
        raw_override = overrides.setdefault(env_name, {})
        if not isinstance(raw_override, dict):
            raw_override = {}
            overrides[env_name] = raw_override
        tags = raw_override.get("tags")
        if not isinstance(tags, dict):
            raw_override["tags"] = {}
        return raw_override

    def _tags_for_env(self, env_name: str) -> dict[str, str]:
        override = self._environment_override(env_name)
        tags = override.setdefault("tags", {})
        return {str(key): str(value) for key, value in tags.items()}

    def compose(self) -> ComposeResult:
        draft = self._draft()
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Env Tags", classes="title")
                yield Static("", id="selected-env-summary")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield StepRail("tags")
                yield Static("Environment Tags", classes="title")
                yield Label("Choose environment:", classes="section-label")
                with Horizontal(classes="button-row"):
                    for button_id, env_name in self._env_button_ids.items():
                        yield Button(
                            env_name,
                            id=button_id,
                            variant=(
                                "primary"
                                if env_name == self._selected_env
                                else "default"
                            ),
                            compact=True,
                        )

                yield Static(
                    "Tags defined here apply to every supported resource in the selected environment.",
                    id="selected-env-help",
                )

                yield Label("Tag key:", classes="section-label")
                yield Input(
                    placeholder="cost-center",
                    id="tag_key",
                    value=str(draft.get("tag_key", "")),
                )

                yield Label("Tag value:", classes="section-label")
                yield Input(
                    placeholder="sandbox",
                    id="tag_value",
                    value=str(draft.get("tag_value", "")),
                )

                with Vertical(classes="button-row"):
                    yield Button("+ Add", id="add", variant="success")
                    yield Button("Update", id="save", variant="success")
                    yield Button("Remove", id="remove", variant="error")

    def on_mount(self) -> None:
        for env_name in self._environment_names():
            self._environment_override(env_name)
        self._refresh_env_buttons()
        self._refresh_sidebar()
        self._update_mode()
        self._capture_draft()

    def _capture_draft(self) -> None:
        self._draft().update(
            {
                "selected_env": self._selected_env,
                "tag_key": self.query_one("#tag_key", Input).value,
                "tag_value": self.query_one("#tag_value", Input).value,
            }
        )

    def _refresh_env_buttons(self) -> None:
        for button_id, env_name in self._env_button_ids.items():
            button = self.query_one(f"#{button_id}", Button)
            is_selected = env_name == self._selected_env
            button.variant = "primary" if is_selected else "default"
            button.disabled = is_selected

    def _refresh_sidebar(self) -> None:
        tags = self._tags_for_env(self._selected_env)
        self._tag_keys = sorted(tags)

        summary = self.query_one("#selected-env-summary", Static)
        summary.update(f"{self._selected_env} ({len(self._tag_keys)} tags)")

        help_text = self.query_one("#selected-env-help", Static)
        help_text.update(
            f"Tags defined here apply to every supported resource in the '{self._selected_env}' environment."
        )

        list_view = self.query_one("#item-list", ListView)
        list_view.clear()
        for key in self._tag_keys:
            list_view.append(ListItem(Static(f"{key}={tags[key]}")))

    def _update_mode(self) -> None:
        editing = self._editing_key is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "item-list":
            return
        idx = event.list_view.index
        if idx is None or idx >= len(self._tag_keys):
            return
        key = self._tag_keys[idx]
        value = self._tags_for_env(self._selected_env).get(key, "")
        self._editing_key = key
        self.query_one("#tag_key", Input).value = key
        self.query_one("#tag_value", Input).value = value
        self._update_mode()
        self._capture_draft()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("step_nav_"):
            target = button_id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return

        if button_id in self._env_button_ids:
            self._selected_env = self._env_button_ids[button_id]
            self._clear_form()
            self._refresh_env_buttons()
            self._refresh_sidebar()
            self._capture_draft()
            return

        if button_id == "add":
            self._add_tag()
        elif button_id == "save":
            self._save_tag()
        elif button_id == "remove":
            self._remove_tag()

    def before_step_navigation(self, _target: str) -> bool:
        self._persist_for_navigation()
        return True

    def _persist_for_navigation(self) -> None:
        self._capture_draft()
        key = self.query_one("#tag_key", Input).value.strip()
        value = self.query_one("#tag_value", Input).value.strip()
        if self._editing_key is not None:
            self._save_tag()
        elif key and value:
            self._add_tag()

    def _read_form(self) -> tuple[str, str] | None:
        key = self.query_one("#tag_key", Input).value.strip()
        value = self.query_one("#tag_value", Input).value.strip()
        if not key:
            self.notify("Tag key is required", severity="error")
            return None
        if not value:
            self.notify("Tag value is required", severity="error")
            return None
        return key, value

    def _add_tag(self) -> None:
        payload = self._read_form()
        if payload is None:
            return
        key, value = payload
        override = self._environment_override(self._selected_env)
        tags = override.setdefault("tags", {})
        action = "Updated" if key in tags else "Added"
        tags[key] = value
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"{action} tag '{key}' for {self._selected_env}")

    def _save_tag(self) -> None:
        if self._editing_key is None:
            return
        payload = self._read_form()
        if payload is None:
            return
        key, value = payload
        override = self._environment_override(self._selected_env)
        tags = override.setdefault("tags", {})
        if key != self._editing_key:
            tags.pop(self._editing_key, None)
        tags[key] = value
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Updated tag '{key}' for {self._selected_env}")

    def _remove_tag(self) -> None:
        if self._editing_key is None:
            return
        override = self._environment_override(self._selected_env)
        tags = override.setdefault("tags", {})
        removed_key = self._editing_key
        tags.pop(removed_key, None)
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Removed tag '{removed_key}' from {self._selected_env}")

    def _clear_form(self) -> None:
        self._editing_key = None
        self.query_one("#tag_key", Input).value = ""
        self.query_one("#tag_value", Input).value = ""
        self._update_mode()
        self._capture_draft()
