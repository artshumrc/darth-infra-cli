"""Preview environment configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static, Switch

from ..step_rail import StepRail


class PreviewScreen(Screen):
    """Configure dynamic preview environments."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state

    def _preview(self) -> dict:
        return self._state.setdefault(
            "preview_environments",
            {
                "enabled": False,
                "base_environment": "prod",
                "name_pattern": "pr-{number}",
                "domain_template": None,
                "hosted_zone_name": None,
                "listener_priority_start": None,
                "listener_priority_end": None,
                "tags": {},
            },
        )

    def _draft(self) -> dict:
        draft = self._state.setdefault("_wizard_draft", {})
        return draft.setdefault("preview", {})

    def compose(self) -> ComposeResult:
        preview = self._preview()
        draft = self._draft()
        with VerticalScroll(classes="form-container"):
            yield StepRail("preview")
            yield Static("Preview Environments", classes="title")

            yield Label("Enable dynamic previews?", classes="section-label")
            yield Switch(
                id="preview_enabled",
                value=bool(draft.get("enabled", preview.get("enabled", False))),
            )

            yield Label("Base environment:", classes="section-label")
            yield Input(
                placeholder="prod",
                id="preview_base_environment",
                value=str(
                    draft.get("base_environment", preview.get("base_environment") or "prod")
                ),
            )

            yield Label("Name pattern:", classes="section-label")
            yield Input(
                placeholder="pr-{number}",
                id="preview_name_pattern",
                value=str(
                    draft.get("name_pattern", preview.get("name_pattern") or "pr-{number}")
                ),
            )

            yield Label("Domain template:", classes="section-label")
            yield Input(
                placeholder="pr-{number}.example.com",
                id="preview_domain_template",
                value=str(
                    draft.get(
                        "domain_template", preview.get("domain_template") or ""
                    )
                ),
            )

            yield Label("Route53 hosted zone:", classes="section-label")
            yield Input(
                placeholder="example.com",
                id="preview_hosted_zone_name",
                value=str(
                    draft.get(
                        "hosted_zone_name", preview.get("hosted_zone_name") or ""
                    )
                ),
            )

            yield Label("Listener priority range:", classes="section-label")
            yield Input(
                placeholder="30000",
                id="preview_listener_priority_start",
                value=str(
                    draft.get(
                        "listener_priority_start",
                        preview.get("listener_priority_start") or "",
                    )
                ),
            )
            yield Input(
                placeholder="39999",
                id="preview_listener_priority_end",
                value=str(
                    draft.get(
                        "listener_priority_end",
                        preview.get("listener_priority_end") or "",
                    )
                ),
            )

            yield Label("Preview tags:", classes="section-label")
            yield Static(
                "Comma-separated key=value pairs. These are separate from environment tags.",
            )
            yield Input(
                placeholder="ephemeral-cleanup-id={project}-{env}",
                id="preview_tags",
                value=str(draft.get("tags", self._format_tags(preview.get("tags", {})))),
            )

    def _capture_draft(self) -> None:
        self._draft().update(
            {
                "enabled": self.query_one("#preview_enabled", Switch).value,
                "base_environment": self.query_one(
                    "#preview_base_environment", Input
                ).value,
                "name_pattern": self.query_one("#preview_name_pattern", Input).value,
                "domain_template": self.query_one(
                    "#preview_domain_template", Input
                ).value,
                "hosted_zone_name": self.query_one(
                    "#preview_hosted_zone_name", Input
                ).value,
                "listener_priority_start": self.query_one(
                    "#preview_listener_priority_start", Input
                ).value,
                "listener_priority_end": self.query_one(
                    "#preview_listener_priority_end", Input
                ).value,
                "tags": self.query_one("#preview_tags", Input).value,
            }
        )

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._capture_draft()

    def on_switch_changed(self, _event: Switch.Changed) -> None:
        self._capture_draft()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id.startswith("step_nav_"):
            if self._apply_to_state():
                self.app.go_to_step(button_id.replace("step_nav_", "", 1))

    def before_step_navigation(self, _target: str) -> bool:
        return self._apply_to_state()

    def _persist_to_state(self) -> None:
        self._apply_to_state()

    def _apply_to_state(self) -> bool:
        self._capture_draft()
        draft = self._draft()
        enabled = bool(draft.get("enabled", False))
        start_raw = str(draft.get("listener_priority_start", "")).strip()
        end_raw = str(draft.get("listener_priority_end", "")).strip()
        if enabled and bool(start_raw) != bool(end_raw):
            self.notify("Both priority range values are required", severity="error")
            return False

        self._state["preview_environments"] = {
            "enabled": enabled,
            "base_environment": str(draft.get("base_environment") or "prod").strip(),
            "name_pattern": str(draft.get("name_pattern") or "pr-{number}").strip(),
            "domain_template": str(draft.get("domain_template") or "").strip()
            or None,
            "hosted_zone_name": str(draft.get("hosted_zone_name") or "").strip()
            or None,
            "listener_priority_start": int(start_raw) if start_raw else None,
            "listener_priority_end": int(end_raw) if end_raw else None,
            "tags": self._parse_tags(str(draft.get("tags") or "")),
        }
        return True

    @staticmethod
    def _format_tags(tags: dict) -> str:
        return ", ".join(f"{key}={value}" for key, value in sorted(tags.items()))

    @staticmethod
    def _parse_tags(value: str) -> dict[str, str]:
        tags: dict[str, str] = {}
        for part in value.split(","):
            raw = part.strip()
            if not raw or "=" not in raw:
                continue
            key, tag_value = raw.split("=", 1)
            key = key.strip()
            tag_value = tag_value.strip()
            if key and tag_value:
                tags[key] = tag_value
        return tags
