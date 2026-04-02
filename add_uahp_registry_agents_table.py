"""Add UAHP Registry agents table

Revision ID: add_uahp_registry_agents_table
Revises:
Create Date: 2026-03-25 01:16:00.000000

This migration creates the core agents table for the UAHP Registry.
Includes JSONB GIN indexes for fast capability-based discovery —
the thermodynamic routing layer queries these constantly.
"""

from alembic import op
import sqlalchemy as sa

try:
    from sqlalchemy.dialects.postgresql import JSONB
    USE_JSONB = True
except ImportError:
    USE_JSONB = False

# revision identifiers
revision = 'add_uahp_registry_agents_table'
down_revision = None   # replace with your last migration ID if one exists
branch_labels = None
depends_on = None

JSON_TYPE = JSONB() if USE_JSONB else sa.JSON()


def upgrade():
    op.create_table(
        'agents',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('agent_id', sa.String(length=255), nullable=False, unique=True, index=True),
        sa.Column('pubkey', sa.String(length=255), nullable=False),

        # Timestamps
        sa.Column('registered_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),

        # Liveness — the core UAHP liveness proof tracking
        sa.Column('liveness_status',
                  sa.Enum('live', 'stale', 'dead', name='liveness_status_enum'),
                  server_default='live', nullable=False),

        # Capability and routing metadata
        sa.Column('capabilities', JSON_TYPE, nullable=False, server_default='[]'),
        sa.Column('thermo_profile', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('csp_hints', JSON_TYPE, nullable=False, server_default='{}'),
        sa.Column('endpoints', JSON_TYPE, nullable=False, server_default='{}'),

        # Trust chain
        sa.Column('sponsorship_cert', JSON_TYPE, nullable=True),
        sa.Column('death_cert', JSON_TYPE, nullable=True),

        # POLIS civil standing (Layer 5 integration)
        sa.Column('polis_did', sa.String(length=255), nullable=True),
        sa.Column('polis_standing_score', sa.Float(), nullable=True),
        sa.Column('polis_standing_tier', sa.String(length=50), nullable=True),

        # UAHP Beacon propagation tracking
        sa.Column('beacon_version', sa.String(length=20), nullable=True),
        sa.Column('beacon_carried', sa.Boolean(), server_default='false'),

        # Registry endorsement
        sa.Column('registry_signature', sa.Text(), nullable=True),

        sa.UniqueConstraint('agent_id', name='uq_agent_id'),
    )

    # GIN indexes for JSONB fast capability discovery
    # SMART-UAHP queries these for thermodynamic routing decisions
    if USE_JSONB:
        op.create_index(
            'ix_agents_capabilities_gin',
            'agents',
            ['capabilities'],
            postgresql_using='gin'
        )
        op.create_index(
            'ix_agents_thermo_profile_gin',
            'agents',
            ['thermo_profile'],
            postgresql_using='gin'
        )

    op.create_index('ix_agents_liveness_status', 'agents', ['liveness_status'])
    op.create_index('ix_agents_expires_at', 'agents', ['expires_at'])
    op.create_index('ix_agents_polis_standing_score', 'agents', ['polis_standing_score'])


def downgrade():
    if USE_JSONB:
        op.drop_index('ix_agents_capabilities_gin', table_name='agents')
        op.drop_index('ix_agents_thermo_profile_gin', table_name='agents')

    op.drop_index('ix_agents_liveness_status', table_name='agents')
    op.drop_index('ix_agents_expires_at', table_name='agents')
    op.drop_index('ix_agents_polis_standing_score', table_name='agents')
    op.drop_table('agents')
