"""add influencer scoring breakdown

Revision ID: cdecff436aea
Revises: f6181c47244d
Create Date: 2026-01-28 22:08:27.930223

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cdecff436aea'
down_revision: Union[str, Sequence[str], None] = 'f6181c47244d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# def upgrade() -> None:
#     """Upgrade schema."""
#     pass


# def downgrade() -> None:
#     """Downgrade schema."""
#     pass

# from alembic import op
# import sqlalchemy as sa

# revision identifiers, used by Alembic.
# revision = "xxxx"
# down_revision = "yyyy"
# branch_labels = None
# depends_on = None


def upgrade():
    op.add_column("influencers", sa.Column("score_breakdown", sa.JSON(), nullable=True))
    op.add_column("influencers", sa.Column("score_updated_at", sa.DateTime(), nullable=True))
    op.add_column("influencers", sa.Column("discovered_source", sa.String(), nullable=True))
    op.alter_column(
        "influencers",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=True
    )


def downgrade():
    op.drop_column("influencers", "discovered_source")
    op.drop_column("influencers", "score_updated_at")
    op.drop_column("influencers", "score_breakdown")
