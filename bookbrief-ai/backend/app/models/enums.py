from enum import Enum


def sqlalchemy_enum_values(enum_class: type[Enum]) -> list[str]:
    """Persist str Enum `.value` (not name) in VARCHAR columns."""
    return [member.value for member in enum_class]


class PlanTier(str, Enum):
    free = "free"
    pro = "pro"
    growth = "growth"


class SubscriptionStatus(str, Enum):
    active = "active"
    canceled = "canceled"
    past_due = "past_due"
    trialing = "trialing"
    incomplete = "incomplete"


class BookSourceType(str, Enum):
    paste = "paste"
    pdf = "pdf"
    title_author = "title_author"


class SummaryStyle(str, Enum):
    ultra_short = "ultra_short"
    standard = "standard"
    detailed = "detailed"
    takeaways = "takeaways"
    personalized = "personalized"


class SummaryJobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class VideoJobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"
