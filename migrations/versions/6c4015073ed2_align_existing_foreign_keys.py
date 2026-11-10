"""Align existing report and review foreign keys with model metadata.

Revision ID: 6c4015073ed2
Revises: 07abe9ce39eb
"""
from alembic import op
import sqlalchemy as sa


revision = "6c4015073ed2"
down_revision = "07abe9ce39eb"
branch_labels = None
depends_on = None

_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
}


def _foreign_key_name(table_name, column_name, referred_table):
    matches = [
        foreign_key
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
        if foreign_key["constrained_columns"] == [column_name]
        and foreign_key["referred_table"] == referred_table
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one foreign key for {table_name}.{column_name} "
            f"to {referred_table}; found {len(matches)}."
        )
    return matches[0]["name"] or (
        f"fk_{table_name}_{column_name}_{referred_table}"
    )


def upgrade():
    request_fk = _foreign_key_name("review", "skill_request_id", "skill_request")
    session_fk = _foreign_key_name("review", "session_id", "skill_session")

    with op.batch_alter_table(
        "review", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(request_fk, type_="foreignkey")
        batch_op.create_foreign_key(
            request_fk,
            "skill_request",
            ["skill_request_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.drop_constraint(session_fk, type_="foreignkey")
        batch_op.create_foreign_key(
            session_fk,
            "skill_session",
            ["session_id"],
            ["id"],
            ondelete="CASCADE",
        )

    moderator_fks = [
        foreign_key
        for foreign_key in sa.inspect(op.get_bind()).get_foreign_keys("user_report")
        if foreign_key["constrained_columns"] == ["moderator_id"]
        and foreign_key["referred_table"] == "user"
    ]
    if len(moderator_fks) > 1:
        raise RuntimeError("Found multiple user_report.moderator_id foreign keys.")
    moderator_constraint_name = (
        moderator_fks[0]["name"]
        if moderator_fks and moderator_fks[0]["name"]
        else "fk_user_report_moderator_id_user"
    )
    with op.batch_alter_table(
        "user_report", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        if moderator_fks:
            batch_op.drop_constraint(moderator_constraint_name, type_="foreignkey")
        batch_op.create_foreign_key(
            moderator_constraint_name,
            "user",
            ["moderator_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    request_fk = _foreign_key_name("review", "skill_request_id", "skill_request")
    session_fk = _foreign_key_name("review", "session_id", "skill_session")
    moderator_fk = _foreign_key_name("user_report", "moderator_id", "user")

    with op.batch_alter_table(
        "user_report", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(moderator_fk, type_="foreignkey")

    with op.batch_alter_table(
        "review", naming_convention=_NAMING_CONVENTION
    ) as batch_op:
        batch_op.drop_constraint(request_fk, type_="foreignkey")
        batch_op.create_foreign_key(
            request_fk,
            "skill_request",
            ["skill_request_id"],
            ["id"],
        )
        batch_op.drop_constraint(session_fk, type_="foreignkey")
        batch_op.create_foreign_key(
            session_fk,
            "skill_session",
            ["session_id"],
            ["id"],
        )
