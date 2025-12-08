"""chat rollup functions + indexes

Revision ID: 20250910b_chat_rollups
Revises: 20250910_create_chat_analytics
Create Date: 2025-09-10 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

# --- Alembic identifiers ---
revision = "20250910b_chat_rollups"
down_revision = "20250910_create_chat_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Helpful indexes on chat_event for common filters
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_event_plan_ts ON chat_event (plan, ts)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_event_model_ts ON chat_event (model, ts)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_event_user_plan_ts ON chat_event (user_id, plan, ts)")

    # --- Function: Update chat_session_metrics from chat_event ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_update_chat_session_metrics()
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        BEGIN
          INSERT INTO chat_session_metrics AS t (
            chat_session_id,
            user_id,
            plan,
            started_at,
            ended_at,
            messages,
            input_tokens,
            output_tokens,
            total_cost,
            latency_p50_ms,
            latency_p90_ms,
            rag_hit_rate,
            thumbs_up_rate,
            csat_avg,
            errors
          )
          SELECT
            ce.chat_session_id,
            MAX(ce.user_id)        AS user_id,   -- last non-null seen in session
            MAX(ce.plan)           AS plan,
            MIN(ce.ts)             AS started_at,
            MAX(ce.ts)             AS ended_at,
            COUNT(*)               AS messages,
            COALESCE(SUM(ce.input_tokens), 0)   AS input_tokens,
            COALESCE(SUM(ce.output_tokens), 0)  AS output_tokens,
            COALESCE(SUM(ce.total_cost), 0)     AS total_cost,
            PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p50_ms,
            PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p90_ms,
            CASE WHEN COUNT(*) FILTER (WHERE ce.retrieved) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.retrieved AND ce.rag_hit))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.retrieved), 1)
                 ELSE NULL
            END AS rag_hit_rate,
            CASE WHEN COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.thumb = 1))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0), 1)
                 ELSE NULL
            END AS thumbs_up_rate,
            AVG(ce.csat)::numeric(5,2) AS csat_avg,
            COUNT(*) FILTER (WHERE ce.error_kind IS NOT NULL OR ce.response_code >= 400) AS errors
          FROM chat_event ce
          GROUP BY ce.chat_session_id
          ON CONFLICT (chat_session_id) DO UPDATE
          SET user_id         = EXCLUDED.user_id,
              plan            = EXCLUDED.plan,
              started_at      = EXCLUDED.started_at,
              ended_at        = EXCLUDED.ended_at,
              messages        = EXCLUDED.messages,
              input_tokens    = EXCLUDED.input_tokens,
              output_tokens   = EXCLUDED.output_tokens,
              total_cost      = EXCLUDED.total_cost,
              latency_p50_ms  = EXCLUDED.latency_p50_ms,
              latency_p90_ms  = EXCLUDED.latency_p90_ms,
              rag_hit_rate    = EXCLUDED.rag_hit_rate,
              thumbs_up_rate  = EXCLUDED.thumbs_up_rate,
              csat_avg        = EXCLUDED.csat_avg,
              errors          = EXCLUDED.errors;
        END;
        $$;
        """
    )

    # --- Function: Update chat_agg_day over a window ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_update_chat_agg_day(_start timestamptz, _end timestamptz)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        BEGIN
          -- by day + plan + model
          INSERT INTO chat_agg_day AS d (
            day, user_id, plan, model,
            messages, sessions, input_tokens, output_tokens, total_cost,
            latency_p50_ms, latency_p90_ms, rag_hit_rate, thumbs_up_rate, csat_avg, errors
          )
          SELECT
            (ce.ts AT TIME ZONE 'UTC')::date AS day,
            NULL::uuid                       AS user_id,
            ce.plan                          AS plan,
            ce.model                         AS model,
            COUNT(*)                         AS messages,
            COUNT(DISTINCT ce.chat_session_id) AS sessions,
            COALESCE(SUM(ce.input_tokens), 0)    AS input_tokens,
            COALESCE(SUM(ce.output_tokens), 0)   AS output_tokens,
            COALESCE(SUM(ce.total_cost), 0)      AS total_cost,
            PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p50_ms,
            PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p90_ms,
            CASE WHEN COUNT(*) FILTER (WHERE ce.retrieved) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.retrieved AND ce.rag_hit))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.retrieved), 1)
                 ELSE NULL
            END AS rag_hit_rate,
            CASE WHEN COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.thumb = 1))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0), 1)
                 ELSE NULL
            END AS thumbs_up_rate,
            AVG(ce.csat)::numeric(5,2) AS csat_avg,
            COUNT(*) FILTER (WHERE ce.error_kind IS NOT NULL OR ce.response_code >= 400) AS errors
          FROM chat_event ce
          WHERE ce.ts >= _start AND ce.ts < _end
          GROUP BY day, plan, model
          ON CONFLICT ON CONSTRAINT pk_chat_agg_day_composite DO UPDATE
          SET messages       = EXCLUDED.messages,
              sessions       = EXCLUDED.sessions,
              input_tokens   = EXCLUDED.input_tokens,
              output_tokens  = EXCLUDED.output_tokens,
              total_cost     = EXCLUDED.total_cost,
              latency_p50_ms = EXCLUDED.latency_p50_ms,
              latency_p90_ms = EXCLUDED.latency_p90_ms,
              rag_hit_rate   = EXCLUDED.rag_hit_rate,
              thumbs_up_rate = EXCLUDED.thumbs_up_rate,
              csat_avg       = EXCLUDED.csat_avg,
              errors         = EXCLUDED.errors;

          -- pure global row per day (no plan/model)
          INSERT INTO chat_agg_day AS d (
            day, user_id, plan, model,
            messages, sessions, input_tokens, output_tokens, total_cost,
            latency_p50_ms, latency_p90_ms, rag_hit_rate, thumbs_up_rate, csat_avg, errors
          )
          SELECT
            (ce.ts AT TIME ZONE 'UTC')::date AS day,
            NULL::uuid                       AS user_id,
            NULL::text                       AS plan,
            NULL::text                       AS model,
            COUNT(*)                         AS messages,
            COUNT(DISTINCT ce.chat_session_id) AS sessions,
            COALESCE(SUM(ce.input_tokens), 0)    AS input_tokens,
            COALESCE(SUM(ce.output_tokens), 0)   AS output_tokens,
            COALESCE(SUM(ce.total_cost), 0)      AS total_cost,
            PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p50_ms,
            PERCENTILE_DISC(0.9) WITHIN GROUP (ORDER BY ce.latency_ms) AS latency_p90_ms,
            CASE WHEN COUNT(*) FILTER (WHERE ce.retrieved) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.retrieved AND ce.rag_hit))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.retrieved), 1)
                 ELSE NULL
            END AS rag_hit_rate,
            CASE WHEN COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0) > 0
                 THEN (COUNT(*) FILTER (WHERE ce.thumb = 1))::float
                      / GREATEST(COUNT(*) FILTER (WHERE ce.thumb IS NOT NULL AND ce.thumb <> 0), 1)
                 ELSE NULL
            END AS thumbs_up_rate,
            AVG(ce.csat)::numeric(5,2) AS csat_avg,
            COUNT(*) FILTER (WHERE ce.error_kind IS NOT NULL OR ce.response_code >= 400) AS errors
          FROM chat_event ce
          WHERE ce.ts >= _start AND ce.ts < _end
          GROUP BY day
          ON CONFLICT ON CONSTRAINT pk_chat_agg_day_composite DO UPDATE
          SET messages       = EXCLUDED.messages,
              sessions       = EXCLUDED.sessions,
              input_tokens   = EXCLUDED.input_tokens,
              output_tokens  = EXCLUDED.output_tokens,
              total_cost     = EXCLUDED.total_cost,
              latency_p50_ms = EXCLUDED.latency_p50_ms,
              latency_p90_ms = EXCLUDED.latency_p90_ms,
              rag_hit_rate   = EXCLUDED.rag_hit_rate,
              thumbs_up_rate = EXCLUDED.thumbs_up_rate,
              csat_avg       = EXCLUDED.csat_avg,
              errors         = EXCLUDED.errors;

        END;
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS fn_update_chat_agg_day(timestamptz, timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS fn_update_chat_session_metrics()")
    op.execute("DROP INDEX IF EXISTS ix_chat_event_user_plan_ts")
    op.execute("DROP INDEX IF EXISTS ix_chat_event_model_ts")
    op.execute("DROP INDEX IF EXISTS ix_chat_event_plan_ts")
