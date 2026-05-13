"""Wizard step metadata."""

STEP_ORDER = [
    "welcome",
    "existing-resources",
    "services",
    "alb",
    "rds",
    "s3",
    "secrets",
    "tags",
    "review",
]

STEP_LABELS = {
    "welcome": "Project",
    "existing-resources": "Resources",
    "services": "Services",
    "alb": "Routing",
    "rds": "RDS",
    "s3": "S3",
    "secrets": "Secrets",
    "tags": "Tags",
    "review": "Review",
}
