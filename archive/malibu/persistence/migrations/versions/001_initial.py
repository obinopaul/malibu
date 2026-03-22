"""Initial schema — sessions, messages, tool_calls, plans, auth_tokens, command_allowlist.

Revision ID: 001
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Sessions
    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("cwd", sa.Text, nullable=False),
        sa.Column("mode_id", sa.String(64), nullable=True),
        sa.Column("model_id", sa.String(128), nullable=True),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("config_json", JSONB, nullable=True),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Messages
    op.create_table(
        "messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])

    # Tool calls
    op.create_table(
        "tool_calls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("tool_call_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("input_json", JSONB, nullable=True),
        sa.Column("output_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tool_calls_session", "tool_calls", ["session_id"])

    # Plans
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("entries_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_plans_session", "plans", ["session_id"])

    # Auth tokens
    op.create_table(
        "auth_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False, index=True),
        sa.Column("method_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_revoked", sa.Boolean, default=False),
    )

    # Command allowlist
    op.create_table(
        "command_allowlist",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("sessions.session_id", ondelete="CASCADE")),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("command_signature", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_command_allowlist_session", "command_allowlist", ["session_id"])


def downgrade() -> None:
    op.drop_table("command_allowlist")
    op.drop_table("auth_tokens")
    op.drop_table("plans")
    op.drop_table("tool_calls")
    op.drop_table("messages")
    op.drop_table("sessions")
