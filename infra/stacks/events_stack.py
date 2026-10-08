"""Events stack provisioning the custom EventBridge bus for asynchronous events."""

from aws_cdk import (
    Stack,
)
from aws_cdk import (
    aws_events as events,
)
from constructs import Construct

from ..config import AroConfig


class EventsStack(Stack):
    """EventBridge resources for asynchronous case and event distribution."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: AroConfig,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.config = config

        self.event_bus = events.EventBus(
            self,
            "AroEventBus",
            event_bus_name=config.event_bus_name,
        )
