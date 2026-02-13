"""S3 bucket configuration screen."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, ListItem, ListView, Static, Switch


class S3Screen(Screen):
    """Optional: configure S3 buckets."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._editing_index: int | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="screen-layout"):
            with Vertical(classes="sidebar"):
                yield Static("Added Buckets", classes="title")
                yield ListView(id="item-list")
            with VerticalScroll(classes="form-container"):
                yield Static("S3 Bucket Details (Optional)", classes="title")

                yield Label("Bucket name (logical):", classes="section-label")
                yield Input(placeholder="media", id="bucket_name")

                yield Label("Enable CloudFront?", classes="section-label")
                yield Switch(id="bucket_cf", value=False)

                yield Label("Enable CORS?", classes="section-label")
                yield Switch(id="bucket_cors", value=False)

                yield Label("Public read?", classes="section-label")
                yield Switch(id="bucket_public", value=False)

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
        for bucket in self._state.get("s3_buckets", []):
            lv.append(ListItem(Static(bucket["name"])))

    def _update_mode(self) -> None:
        """Toggle button visibility based on add vs edit mode."""
        editing = self._editing_index is not None
        self.query_one("#add", Button).display = not editing
        self.query_one("#save", Button).display = editing
        self.query_one("#remove", Button).display = editing

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Load a bucket into the form for editing."""
        idx = event.list_view.index
        buckets = self._state.get("s3_buckets", [])
        if idx is not None and idx < len(buckets):
            self._editing_index = idx
            bucket = buckets[idx]
            self.query_one("#bucket_name", Input).value = bucket.get("name", "")
            self.query_one("#bucket_cf", Switch).value = bucket.get("cloudfront", False)
            self.query_one("#bucket_cors", Switch).value = bucket.get("cors", False)
            self.query_one("#bucket_public", Switch).value = bucket.get(
                "public_read", False
            )
            self._update_mode()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        elif event.button.id == "add":
            self._add_bucket()
        elif event.button.id == "save":
            self._save_bucket()
        elif event.button.id == "remove":
            self._remove_bucket()
        elif event.button.id == "next":
            name = self.query_one("#bucket_name", Input).value.strip()
            if name and self._editing_index is None:
                self._add_bucket()
            self.app.advance_to("alb")

    def _read_form(self) -> dict | None:
        """Read and validate the form fields."""
        name = self.query_one("#bucket_name", Input).value.strip()
        if not name:
            self.notify("Bucket name is required", severity="error")
            return None

        return {
            "name": name,
            "cloudfront": self.query_one("#bucket_cf", Switch).value,
            "cors": self.query_one("#bucket_cors", Switch).value,
            "public_read": self.query_one("#bucket_public", Switch).value,
        }

    def _add_bucket(self) -> None:
        bucket = self._read_form()
        if bucket is None:
            return
        self._state.setdefault("s3_buckets", []).append(bucket)
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Added bucket '{bucket['name']}'")

    def _save_bucket(self) -> None:
        if self._editing_index is None:
            return
        bucket = self._read_form()
        if bucket is None:
            return
        self._state["s3_buckets"][self._editing_index] = bucket
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Updated bucket '{bucket['name']}'")

    def _remove_bucket(self) -> None:
        if self._editing_index is None:
            return
        name = self._state["s3_buckets"][self._editing_index]["name"]
        del self._state["s3_buckets"][self._editing_index]
        self._clear_form()
        self._refresh_sidebar()
        self.notify(f"Removed bucket '{name}'")

    def _clear_form(self) -> None:
        """Reset form to add mode."""
        self._editing_index = None
        self.query_one("#bucket_name", Input).value = ""
        self.query_one("#bucket_cf", Switch).value = False
        self.query_one("#bucket_cors", Switch).value = False
        self.query_one("#bucket_public", Switch).value = False
        self._update_mode()
