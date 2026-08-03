"""P2 production constraints, immutable ledger and provider indexes.

Revision ID: 0004_p2_production_hardening
Revises: 0003_p2_platform
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_p2_production_hardening"
down_revision = "0003_p2_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    with op.batch_alter_table("reservation_orders") as batch:
        batch.create_check_constraint("ck_reservation_amount_positive", "amount > 0")
    with op.batch_alter_table("payment_intents") as batch:
        batch.create_check_constraint("ck_payment_intent_amount_positive", "amount > 0")
    with op.batch_alter_table("payment_transactions") as batch:
        batch.create_check_constraint("ck_payment_transaction_amount_positive", "amount > 0")
    with op.batch_alter_table("refund_requests") as batch:
        batch.create_check_constraint("ck_refund_amount_positive", "amount > 0")
    with op.batch_alter_table("ledger_entries") as batch:
        batch.create_check_constraint("ck_ledger_amount_positive", "amount > 0")
        batch.create_check_constraint("ck_ledger_direction", "direction IN ('debit','credit')")

    op.create_index(
        "uq_payment_intent_provider_reference",
        "payment_intents",
        ["provider", "provider_intent_id"],
        unique=True,
    )
    op.create_index(
        "ix_payment_transaction_intent_type_status",
        "payment_transactions",
        ["intent_id", "transaction_type", "status"],
        unique=False,
    )
    op.create_index(
        "ix_contract_envelope_provider_status",
        "contract_envelopes",
        ["provider", "status"],
        unique=False,
    )

    if dialect == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION reject_ledger_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'ledger_entries is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ledger_entries_no_update
            BEFORE UPDATE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ledger_entries_no_delete
            BEFORE DELETE ON ledger_entries
            FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();
            """
        )
    elif dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_ledger_entries_no_update
            BEFORE UPDATE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledger_entries is append-only'); END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_ledger_entries_no_delete
            BEFORE DELETE ON ledger_entries
            BEGIN SELECT RAISE(ABORT, 'ledger_entries is append-only'); END;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_no_delete ON ledger_entries")
        op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_no_update ON ledger_entries")
        op.execute("DROP FUNCTION IF EXISTS reject_ledger_mutation()")
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_ledger_entries_no_update")

    op.drop_index("ix_contract_envelope_provider_status", table_name="contract_envelopes")
    op.drop_index("ix_payment_transaction_intent_type_status", table_name="payment_transactions")
    op.drop_index("uq_payment_intent_provider_reference", table_name="payment_intents")

    with op.batch_alter_table("ledger_entries") as batch:
        batch.drop_constraint("ck_ledger_direction", type_="check")
        batch.drop_constraint("ck_ledger_amount_positive", type_="check")
    with op.batch_alter_table("refund_requests") as batch:
        batch.drop_constraint("ck_refund_amount_positive", type_="check")
    with op.batch_alter_table("payment_transactions") as batch:
        batch.drop_constraint("ck_payment_transaction_amount_positive", type_="check")
    with op.batch_alter_table("payment_intents") as batch:
        batch.drop_constraint("ck_payment_intent_amount_positive", type_="check")
    with op.batch_alter_table("reservation_orders") as batch:
        batch.drop_constraint("ck_reservation_amount_positive", type_="check")
