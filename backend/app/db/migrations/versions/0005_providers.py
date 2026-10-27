"""Migration 0005: the provider table, seeded from the Supporting File.

Revision ID: 0005
Revises: 0004"""
from __future__ import annotations
import datetime as dt

from alembic import op
import sqlalchemy as sa

from app.db.models import UtcDateTime

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

# BUSINESSREGID, PROVIDER ID, PROVIDER NAME, Provider Status, Provider Group
STARTING = [
    (218, 'Mesa Pharmacy', 'Mesa Pharmacy Inc.', 'Active', 'Mesa'),
    (229, 'Expert MRI', 'Expert MRI', 'Active', 'Credit Point'),
    (230, 'Safvi Medical', 'Safvi Medical Corportion', 'Active', 'Credit Point'),
    (231, 'West Valley MRI', 'West Valley MRI Inc', 'Active', 'Credit Point'),
    (232, 'Sati Wellness', 'Sati Wellness Inc.', 'Active', 'Credit Point'),
    (233, 'MHE Assets', 'MH Express Assets LLC', 'Active', 'MH Express'),
    (234, 'MHE Pharmacy', 'MH Express Pharmacy', 'Active', 'MH Express'),
    (235, 'Eagle Eye', 'Eagle Eye Imaging Center LLC', 'Active', 'POS'),
    (237, 'Novatech', 'Novatech Medical Devices LLC', 'Active', 'POS'),
    (238, 'Progressive Orthopedic', 'Progressive Orthopedic Solutions LLC', 'Active', 'POS'),
    (239, 'IMR', 'Ideal Medical Records Service Inc', 'Active', 'IMR'),
    (245, 'Inland Empire Healthcare', 'Inland Empire Healthcare Management Group Inc', 'Active', 'A Miles'),
    (246, 'Southern California Orthopedic', 'Southern California Orthopedic Medical Group Inc', 'Active', 'Southern California'),
    (247, 'Fardad Mogharabi', 'Fardad Mogharabi Chiropractic Services Inc', 'Active', 'Lakewood'),
    (248, 'Medvantage', 'Medvantage Orthocare LLC', 'Active', 'Medvantage'),
    (250, 'Pro Ivy', 'Pro Ivy Medical Group Professional Corp.', 'Active', 'Pro Ivy'),
    (251, 'United Interpreters', 'United Certified Interpreters LLC', 'Active', 'United'),
    (257, 'DIMG', 'Downey Industrial Medical Group Inc', 'Active', 'Russman'),
    (259, 'FMR', 'FMR Interventional Quality Pain Management APC', 'Active', 'Russman'),
    (260, 'Pledge Medical', 'Pledge Medical MSO', 'Active', 'Pledge'),
    (276, 'Thomas Curtis', 'Thomas Curtis M.D. Inc. DBA Hamlin Psyche Center Woodland Hills', 'Active', 'T Curtis'),
    (297, 'Advanced MD', 'Advanced MD Medical Group', 'Active', 'Advance MD'),
    (299, '365 MEDICAL', '365 Medical Corporation', 'Active', '365 Medical'),
    (300, 'Med-Legal', 'MedLegal Services LLC', 'Active', 'Med-Legal'),
    (302, 'BayCo LLC', 'BayCo Industrial LLC', 'Active', 'Bayco'),
    (303, 'DDM', 'Dash Diagnostic Medical', 'Active', 'DDM'),
    (305, 'Pro Ivy', 'Pro Ivy Medical Group Professional Corp.', 'Active', 'Pro Ivy'),
    (309, 'Defense Pro', 'Defense Pro LLC', 'Active', 'Med-Legal'),
    (324, 'Life Pharmacy', 'Life Pharmacy LLC', 'Active', 'Life Pharmacy'),
    (325, 'Stuart B Kramer', 'Stuart B Kramer', 'Active', 'Stuart B Kramer'),
    (328, 'Horus Multispecialty', 'Horus Multispecialty Medical Group', 'Active', 'Horus'),
    (329, 'FRF', 'First Responder First', 'Active', 'FRF'),
    (330, 'Basem A Attum', 'Basem A Attum APC', 'Active', 'Basem A Attum'),
    (331, 'Andrew Miles', 'Andrew Miles Chiropractic Corporation', 'Active', 'A Miles'),
    (332, 'Desert Care', 'Desert Care Medical Clinic PC', 'Active', 'Desert Care'),
    (333, 'Soheil Enterprise DBA Alexander Pharmacy', 'Alexander Pharmacy', 'Active', 'Alexander Pharmacy'),
    (335, 'Artheon Orthopedic', 'Artheon Orthopedic Devices Inc', 'Active', 'Artheon'),
    (336, 'Mesa Care', 'MesaCare Pharmacy DBA Sherman Care Enterprises Inc', 'Active', 'Mesa Care'),
    (338, 'Advance Care', 'Advance Care Specialist Medical Clinic Inc', 'Active', 'Advance Care'),
    (341, 'Concierge Diagnostics', 'Concierge Diagnostics', 'Active', 'Concierge'),
    (343, 'California Neuromedical', 'California Neuromedical Services', 'Active', 'California Neuromedical'),
    (344, 'Inland Empire Wellness', 'Inland Empire Wellness Medical Group INC', 'Active', 'Inland Empire Wellness'),
    (345, 'JL Calpar', 'JL Calpar Inc', 'Active', 'JL Calpar Inc'),
    (348, 'Koruon Daldalyan', 'Koruon Daldalyan', 'Active', 'Koruon Daldalyan'),
    (349, 'Accumen Healthcare', 'Accumen TMS Center DBA Accumen Healthcare', 'Active', 'Accumen Healthcare'),
    (352, 'St. John Medical Clinic', 'St. John Medical Clinic', 'Active', 'St. John Medical Clinic'),
    (354, 'EZ Health Care', 'EZ Health Care', 'Active', 'EZ Health Care'),
    (359, 'Coastal Care', 'Coastal Care DME, LLC', 'Active', 'Coastal Care'),
    (360, 'Tulip Radiology', 'Caridad Medical Clinic DB Tulip Radiology', 'Active', 'Tulip Radiology'),
    (361, 'Express Interpreters', 'Express Interpreters', 'Active', 'Express Interpreters'),
    (362, 'Azizi One & Only Chiro', 'One & Only Chiropractic', 'Active', 'One & Only Chiro'),
    (363, 'Medbridge Pharmacy', 'Medbridge Pharmacy', 'Active', 'Medbridge Pharmacy'),
    (372, 'SUPPORT CLAIM WEST', None, 'Active', 'SUPPORT CLAIMS WEST'),
    (376, 'United Services Plus', None, 'Active', 'United Services Plus'),
    (373, 'Prospice Med', None, 'Active', 'Prospice Med'),
    (377, 'BVHS', None, None, 'Dr Dorian'),
    (358, 'Form and Function Physical Therapy P.C.', None, None, 'Form and Function Physical Therapy P.C.'),
    (379, 'Dorian Chiropractic', None, None, 'Dr Dorian'),
    (380, 'Dorian Chiropractic 2', None, None, 'Dr Dorian'),
]


def upgrade() -> None:
    provider = op.create_table(
        "provider",
        sa.Column("regid", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("provider_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(255)),
        sa.Column("status", sa.String(32)),
        sa.Column("provider_group", sa.String(200), nullable=False),
        sa.Column("set_by", sa.String(320)),
        sa.Column("set_at", UtcDateTime(), nullable=False),
    )
    now = dt.datetime.now(dt.timezone.utc)
    op.bulk_insert(provider, [{"regid": r, "provider_id": p, "name": n, "status": s,
                               "provider_group": g, "set_by": None, "set_at": now}
                              for r, p, n, s, g in STARTING])


def downgrade() -> None:
    op.drop_table("provider")
