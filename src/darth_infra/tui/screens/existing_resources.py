"""Existing resources screen — fetch and select pre-existing AWS resources."""

from __future__ import annotations

import threading
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Select, SelectionList, Static

from ..steps import STEP_ORDER
from ..step_rail import StepRail


def should_auto_fetch_saved_alb(state: dict[str, Any]) -> bool:
    """Return True when Existing Resources should auto-fetch saved ALB options."""
    saved_alb_name = str(state.get("shared_alb_name") or "").strip()
    if not saved_alb_name:
        return False

    transit_target = str(state.get("_wizard_transit_target") or "").strip()
    if (
        transit_target
        and transit_target in STEP_ORDER
        and transit_target != "existing-resources"
    ):
        return False

    return True


class ExistingResourcesScreen(Screen):
    """Select VPC/subnets/shared ALB details using AWS lookups."""

    def __init__(self, state: dict) -> None:
        super().__init__()
        self._state = state
        self._albs: dict[str, dict[str, Any]] = {}
        self._fetching_subnets = False
        self._fetching_albs = False
        self._fetching_alb_details = False

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="form-container"):
            yield StepRail("existing-resources")
            yield Static("Existing Resources", classes="title")
            yield Static(
                "Fetch from AWS, then select existing subnet/ALB resources to use.",
            )

            yield Label("Private Subnets (multi-select):", classes="section-label")
            yield Button("Fetch Subnets for VPC", id="fetch_subnets", variant="default")
            yield SelectionList[str](id="private_subnet_select")

            yield Label("Public Subnets (multi-select):", classes="section-label")
            yield SelectionList[str](id="public_subnet_select")

            yield Label("Shared ALB (for shared mode):", classes="section-label")
            yield Button("Fetch ALBs", id="fetch_albs", variant="default")
            yield Select([], id="alb_select", prompt="Select ALB", allow_blank=True)
            yield Button(
                "Fetch Selected ALB Details", id="fetch_alb_details", variant="default"
            )

            yield Label("Shared listener ARN:", classes="section-label")
            yield Input(
                placeholder="arn:aws:elasticloadbalancing:...",
                id="shared_listener_arn",
                value=str(self._state.get("shared_listener_arn") or ""),
            )
            yield Label("Shared ALB security group ID:", classes="section-label")
            yield Input(
                placeholder="sg-0123456789abcdef0",
                id="shared_alb_sg_id",
                value=str(self._state.get("shared_alb_security_group_id") or ""),
            )

    def on_mount(self) -> None:
        # Seed manual values from prior state.
        private_selected = list(self._state.get("private_subnet_ids", []))
        public_selected = list(self._state.get("public_subnet_ids", []))
        if private_selected:
            self.query_one("#private_subnet_select", SelectionList).add_options(
                [(subnet_id, subnet_id, True) for subnet_id in private_selected]
            )
        if public_selected:
            self.query_one("#public_subnet_select", SelectionList).add_options(
                [(subnet_id, subnet_id, True) for subnet_id in public_selected]
            )

        saved_alb_name = str(self._state.get("shared_alb_name") or "").strip()
        if saved_alb_name and should_auto_fetch_saved_alb(self._state):
            self._start_fetch_albs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id.startswith("step_nav_"):
            target = event.button.id.replace("step_nav_", "", 1)
            self.app.go_to_step(target)
            return

        if event.button.id == "back":
            self._state["_wizard_last_screen"] = "welcome"
            self.app.pop_screen()
        elif event.button.id == "next":
            self._persist_to_state()
            self.app.advance_to("services")
        elif event.button.id == "fetch_subnets":
            self._start_fetch_subnets()
        elif event.button.id == "fetch_albs":
            self._start_fetch_albs()
        elif event.button.id == "fetch_alb_details":
            self._start_fetch_alb_details()

    def _aws_region(self) -> str:
        return str(self._state.get("aws_region", "us-east-1"))

    def _capture_form_scroll(self) -> tuple[float, float]:
        container = self.query_one(".form-container", VerticalScroll)
        scroll_x = float(getattr(container, "scroll_x", 0.0))
        scroll_y = float(getattr(container, "scroll_y", 0.0))
        return scroll_x, scroll_y

    def _restore_form_scroll(self, scroll: tuple[float, float]) -> None:
        container = self.query_one(".form-container", VerticalScroll)
        scroll_x, scroll_y = scroll
        self.call_after_refresh(
            lambda: container.scroll_to(
                x=scroll_x, y=scroll_y, animate=False, force=True
            )
        )

    @staticmethod
    def _is_select_empty(value: object) -> bool:
        null_sentinel = getattr(Select, "NULL", object())
        blank_sentinel = getattr(Select, "BLANK", object())
        return value in {None, "", False, null_sentinel, blank_sentinel}

    def _resolve_vpc_id(self) -> str | None:
        state_vpc_id = str(self._state.get("vpc_id") or "").strip()
        if state_vpc_id:
            return state_vpc_id

        vpc_name = str(self._state.get("vpc_name") or "").strip()
        if not vpc_name:
            return None

        ec2 = boto3.client("ec2", region_name=self._aws_region())
        vpcs = ec2.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        ).get("Vpcs", [])
        if not vpcs:
            return None
        return str(vpcs[0]["VpcId"])

    def _start_fetch_subnets(self) -> None:
        if self._fetching_subnets:
            return
        try:
            vpc_id = self._resolve_vpc_id()
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.notify(f"AWS lookup failed: {exc}", severity="error")
            return

        if not vpc_id:
            self.notify("No matching VPC found from Project settings", severity="error")
            return

        self._state["vpc_id"] = vpc_id
        self._fetching_subnets = True
        self.query_one("#fetch_subnets", Button).disabled = True
        threading.Thread(
            target=self._fetch_subnets_worker, args=(vpc_id,), daemon=True
        ).start()

    def _fetch_subnets_worker(self, vpc_id: str) -> None:
        try:
            ec2 = boto3.client("ec2", region_name=self._aws_region())
            subnets = ec2.describe_subnets(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            ).get("Subnets", [])
            private_entries: list[tuple[str, str]] = []
            public_entries: list[tuple[str, str]] = []
            for subnet in subnets:
                subnet_id = subnet["SubnetId"]
                az = subnet.get("AvailabilityZone", "?")
                cidr = subnet.get("CidrBlock", "?")
                name = self._tag(subnet.get("Tags", []), "Name") or "(no Name tag)"
                label = f"{name} ({subnet_id}, {az}, {cidr})"
                if subnet.get("MapPublicIpOnLaunch", False):
                    public_entries.append((label, subnet_id))
                else:
                    private_entries.append((label, subnet_id))
            private_entries.sort(key=lambda x: x[0])
            public_entries.sort(key=lambda x: x[0])
            self.app.call_from_thread(
                self._complete_fetch_subnets,
                vpc_id,
                private_entries,
                public_entries,
                None,
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(
                self._complete_fetch_subnets,
                vpc_id,
                [],
                [],
                str(exc),
            )

    def _complete_fetch_subnets(
        self,
        vpc_id: str,
        private_entries: list[tuple[str, str]],
        public_entries: list[tuple[str, str]],
        err: str | None,
    ) -> None:
        scroll = self._capture_form_scroll()
        self._fetching_subnets = False
        self.query_one("#fetch_subnets", Button).disabled = False
        if err:
            self.notify(f"AWS lookup failed: {err}", severity="error")
            self._restore_form_scroll(scroll)
            return

        self._state["vpc_id"] = vpc_id

        private_selected = set(self._state.get("private_subnet_ids", []))
        public_selected = set(self._state.get("public_subnet_ids", []))

        private_list = self.query_one("#private_subnet_select", SelectionList)
        private_list.clear_options()
        private_list.add_options(
            [
                (label, subnet_id, subnet_id in private_selected)
                for label, subnet_id in private_entries
            ]
        )

        public_list = self.query_one("#public_subnet_select", SelectionList)
        public_list.clear_options()
        public_list.add_options(
            [
                (label, subnet_id, subnet_id in public_selected)
                for label, subnet_id in public_entries
            ]
        )

        self.notify("Fetched subnets", severity="information")
        self._restore_form_scroll(scroll)

    def _start_fetch_albs(self) -> None:
        if self._fetching_albs:
            return
        self._fetching_albs = True
        self.query_one("#fetch_albs", Button).disabled = True
        threading.Thread(target=self._fetch_albs_worker, daemon=True).start()

    def _fetch_albs_worker(self) -> None:
        try:
            elbv2 = boto3.client("elbv2", region_name=self._aws_region())
            paginator = elbv2.get_paginator("describe_load_balancers")
            entries: list[tuple[str, str, dict[str, Any]]] = []
            for page in paginator.paginate():
                for alb in page.get("LoadBalancers", []):
                    if alb.get("Type") != "application":
                        continue
                    name = alb.get("LoadBalancerName", "?")
                    arn = alb["LoadBalancerArn"]
                    scheme = alb.get("Scheme", "?")
                    dns_name = alb.get("DNSName", "?")
                    label = f"{name} ({scheme}, {dns_name})"
                    entries.append((label, arn, alb))
            self.app.call_from_thread(self._complete_fetch_albs, entries, None)
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(self._complete_fetch_albs, [], str(exc))

    def _complete_fetch_albs(
        self,
        entries: list[tuple[str, str, dict[str, Any]]],
        err: str | None,
    ) -> None:
        scroll = self._capture_form_scroll()
        self._fetching_albs = False
        self.query_one("#fetch_albs", Button).disabled = False
        if err:
            self.notify(f"AWS lookup failed: {err}", severity="error")
            self._restore_form_scroll(scroll)
            return

        self._albs = {arn: alb for _, arn, alb in entries}
        select = self.query_one("#alb_select", Select)
        select.set_options([(label, arn) for label, arn, _ in entries])

        current_name = str(self._state.get("shared_alb_name") or "").strip()
        matched_saved = False
        for _, arn, alb in entries:
            if alb.get("LoadBalancerName") == current_name or arn == current_name:
                select.value = arn
                matched_saved = True
                break
        if not matched_saved and entries:
            select.value = entries[0][1]
            if current_name:
                self.notify(
                    f"Saved shared ALB '{current_name}' was not found; selected first available ALB",
                    severity="warning",
                )

        self.notify("Fetched ALBs", severity="information")
        self._restore_form_scroll(scroll)

    def _start_fetch_alb_details(self) -> None:
        if self._fetching_alb_details:
            return
        alb_arn = self.query_one("#alb_select", Select).value
        if self._is_select_empty(alb_arn):
            self.notify("Select an ALB first", severity="error")
            return
        self._fetching_alb_details = True
        self.query_one("#fetch_alb_details", Button).disabled = True
        threading.Thread(
            target=self._fetch_alb_details_worker,
            args=(str(alb_arn),),
            daemon=True,
        ).start()

    def _fetch_alb_details_worker(self, alb_arn: str) -> None:
        try:
            elbv2 = boto3.client("elbv2", region_name=self._aws_region())
            listeners = elbv2.describe_listeners(LoadBalancerArn=alb_arn).get(
                "Listeners", []
            )
            preferred = next(
                (
                    listener
                    for listener in listeners
                    if listener.get("Protocol") == "HTTPS"
                    and listener.get("Port") == 443
                ),
                None,
            )
            if not preferred:
                preferred = next(
                    (
                        listener
                        for listener in listeners
                        if listener.get("Port") in {80, 443}
                    ),
                    None,
                )
            if not preferred:
                raise RuntimeError("Could not find a listener on selected ALB")

            alb = self._albs.get(alb_arn, {})
            alb_name = alb.get("LoadBalancerName", "")
            alb_sg = (alb.get("SecurityGroups") or [""])[0]
            self.app.call_from_thread(
                self._complete_fetch_alb_details,
                alb_name,
                preferred["ListenerArn"],
                alb_sg,
                str(preferred.get("Protocol") or "").strip() or None,
                int(preferred.get("Port", 0)) or None,
                None,
            )
        except (ClientError, BotoCoreError, RuntimeError) as exc:
            self.app.call_from_thread(
                self._complete_fetch_alb_details, "", "", "", None, None, str(exc)
            )

    def _complete_fetch_alb_details(
        self,
        alb_name: str,
        listener_arn: str,
        alb_sg: str,
        listener_protocol: str | None,
        listener_port: int | None,
        err: str | None,
    ) -> None:
        scroll = self._capture_form_scroll()
        self._fetching_alb_details = False
        self.query_one("#fetch_alb_details", Button).disabled = False
        if err:
            self.notify(f"AWS lookup failed: {err}", severity="error")
            self._restore_form_scroll(scroll)
            return

        if alb_name:
            self._state["shared_alb_name"] = alb_name
        self.query_one("#shared_listener_arn", Input).value = listener_arn
        self.query_one("#shared_alb_sg_id", Input).value = alb_sg
        self._state["shared_listener_protocol"] = listener_protocol
        self._state["shared_listener_port"] = listener_port
        self.notify("Fetched selected ALB details", severity="information")
        self._restore_form_scroll(scroll)

    def _persist_to_state(self) -> None:
        self._state["private_subnet_ids"] = [
            str(subnet_id)
            for subnet_id in self.query_one(
                "#private_subnet_select", SelectionList
            ).selected
        ]
        self._state["public_subnet_ids"] = [
            str(subnet_id)
            for subnet_id in self.query_one(
                "#public_subnet_select", SelectionList
            ).selected
        ]
        self._state["shared_listener_arn"] = (
            self.query_one("#shared_listener_arn", Input).value.strip() or None
        )
        self._state["shared_alb_security_group_id"] = (
            self.query_one("#shared_alb_sg_id", Input).value.strip() or None
        )

        alb_arn = self.query_one("#alb_select", Select).value
        if not self._is_select_empty(alb_arn):
            alb = self._albs.get(str(alb_arn))
            if alb:
                self._state["shared_alb_name"] = alb.get(
                    "LoadBalancerName", self._state.get("shared_alb_name", "")
                )

    def before_step_navigation(self, _target: str) -> bool:
        self._persist_to_state()
        return True

    @staticmethod
    def _tag(tags: list[dict[str, str]], key: str) -> str | None:
        for tag in tags:
            if tag.get("Key") == key:
                return tag.get("Value")
        return None
