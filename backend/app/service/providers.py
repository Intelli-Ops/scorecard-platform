"""The provider list - provider to group - as admins keep it on the Providers
screen."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Provider
from ..reports.reading import PROVIDER_COLUMNS


def as_dict(p: Provider) -> dict:
    return {key: getattr(p, key) for key in PROVIDER_COLUMNS}


def with_providers(s: Session, rules: dict) -> dict:
    """`rules` with the provider list as it stands now."""
    rules["providers"] = [as_dict(p) for p in
                          s.scalars(select(Provider).order_by(Provider.regid))]
    return rules
