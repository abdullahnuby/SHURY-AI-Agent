
from __future__ import annotations
from typing import Any
import hashlib
import os
import json
import sqlite3
import time
from pathlib import Path

from .models import ExperienceRecord, Lesson, ReplayItem, SkillEvaluation
from .transition_model import action_signature as canonical_action_signature

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "learning.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT UNIQUE NOT NULL,
    goal TEXT NOT NULL,
    task_signature TEXT NOT NULL,
    operation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    reward REAL NOT NULL,
    verified_rate REAL NOT NULL,
    steps TEXT NOT NULL,
    failure_class TEXT,
    lesson_keys TEXT NOT NULL DEFAULT '[]',
    session_id TEXT,
    environment_signature TEXT NOT NULL DEFAULT '',
    transitions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experience_signature ON experiences(task_signature, created_at DESC);
CREATE TABLE IF NOT EXISTS capability_priors (
    key TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    capability TEXT NOT NULL,
    examples INTEGER NOT NULL DEFAULT 0,
    phrases TEXT NOT NULL DEFAULT '[]',
    tokens TEXT NOT NULL DEFAULT '[]',
    required_tools TEXT NOT NULL DEFAULT '[]',
    interaction_shapes TEXT NOT NULL DEFAULT '[]',
    failure_modes TEXT NOT NULL DEFAULT '[]',
    success_invariants TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.40,
    source TEXT NOT NULL,
    origin_class TEXT NOT NULL DEFAULT 'learned_prior',
    data_class TEXT NOT NULL DEFAULT 'learned',
    source_ref TEXT NOT NULL DEFAULT '',
    authoritative INTEGER NOT NULL DEFAULT 0,
    not_user_memory INTEGER NOT NULL DEFAULT 1,
    not_execution_evidence INTEGER NOT NULL DEFAULT 1,
    not_promotion_evidence INTEGER NOT NULL DEFAULT 1,
    not_knowledge INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capability_priors_capability ON capability_priors(capability);
CREATE INDEX IF NOT EXISTS idx_capability_priors_domain ON capability_priors(domain);
CREATE TABLE IF NOT EXISTS beliefs (
    session_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(session_id, subject, predicate)
);
CREATE TABLE IF NOT EXISTS belief_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    revision INTEGER NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cognitive_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_beliefs_session ON beliefs(session_id, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_cognitive_events_session ON cognitive_events(session_id, id);
CREATE TABLE IF NOT EXISTS capability_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experience_status ON experiences(status, created_at DESC);
CREATE TABLE IF NOT EXISTS lessons (
    key TEXT PRIMARY KEY,
    task_signature TEXT NOT NULL,
    kind TEXT NOT NULL,
    lesson TEXT NOT NULL,
    when_to_apply TEXT NOT NULL,
    avoid TEXT NOT NULL,
    evidence_run_ids TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    uses INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_signature ON lessons(task_signature, status, created_at DESC);
CREATE TABLE IF NOT EXISTS procedural_memories (
    key TEXT PRIMARY KEY,
    task_family_signature TEXT NOT NULL,
    operation TEXT NOT NULL,
    capability TEXT NOT NULL DEFAULT '',
    workflow TEXT NOT NULL,
    trigger_conditions TEXT NOT NULL DEFAULT '[]',
    termination_conditions TEXT NOT NULL DEFAULT '[]',
    recovery_strategy TEXT NOT NULL DEFAULT '[]',
    context_boundary TEXT NOT NULL DEFAULT '[]',
    evidence_run_ids TEXT NOT NULL DEFAULT '[]',
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL DEFAULT '',
    invalidated_at TEXT NOT NULL DEFAULT '',
    invalidation_reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_procedural_family ON procedural_memories(task_family_signature, status, successes DESC);
CREATE INDEX IF NOT EXISTS idx_procedural_operation ON procedural_memories(operation, status, successes DESC);
CREATE TABLE IF NOT EXISTS skill_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT NOT NULL,
    goal TEXT NOT NULL,
    baseline_reward REAL NOT NULL,
    candidate_reward REAL NOT NULL,
    delta REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    regression INTEGER NOT NULL DEFAULT 0,
    replay_kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS replay_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transition_id TEXT UNIQUE NOT NULL,
    episode_id TEXT NOT NULL,
    transition_index INTEGER NOT NULL,
    transition TEXT NOT NULL,
    state_signature TEXT NOT NULL DEFAULT '',
    action_signature TEXT NOT NULL DEFAULT '',
    outcome_signature TEXT NOT NULL DEFAULT '',
    priority REAL NOT NULL DEFAULT 0.000001,
    prediction_error REAL NOT NULL DEFAULT 0,
    novelty REAL NOT NULL DEFAULT 0,
    failure_importance REAL NOT NULL DEFAULT 0,
    uncertainty REAL NOT NULL DEFAULT 0,
    learning_value REAL NOT NULL DEFAULT 0,
    boundary REAL NOT NULL DEFAULT 0,
    contradictory REAL NOT NULL DEFAULT 0,
    replay_count INTEGER NOT NULL DEFAULT 0,
    last_replayed_at TEXT,
    created_at TEXT NOT NULL,
    model_version INTEGER NOT NULL DEFAULT 1,
    model_change_recency REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_replay_priority ON replay_items(priority DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_replay_episode ON replay_items(episode_id, transition_index);
CREATE INDEX IF NOT EXISTS idx_replay_state_action ON replay_items(state_signature, action_signature);
CREATE TABLE IF NOT EXISTS replay_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL,
    transition_id TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    sampling_probability REAL NOT NULL DEFAULT 0,
    importance_weight REAL NOT NULL DEFAULT 1,
    learning_rate_scale REAL NOT NULL DEFAULT 0,
    td_signal REAL NOT NULL DEFAULT 0,
    state_value_delta REAL NOT NULL DEFAULT 0,
    action_value_delta REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replay_updates_batch ON replay_updates(batch_id, id);
CREATE INDEX IF NOT EXISTS idx_replay_updates_transition ON replay_updates(transition_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_learning_eval_candidate ON skill_evaluations(candidate_key, id DESC);
CREATE TABLE IF NOT EXISTS learning_metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL DEFAULT '',
    metrics TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_learning_metric_snapshots_created ON learning_metric_snapshots(created_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS meta_strategy_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_type TEXT NOT NULL,
    strategy TEXT NOT NULL,
    reward REAL NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 0,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meta_strategy_state ON meta_strategy_observations(state_type, strategy, id DESC);
CREATE TABLE IF NOT EXISTS failure_diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    failure_class TEXT NOT NULL,
    root_transition_id TEXT NOT NULL,
    root_action_signature TEXT NOT NULL,
    prediction_error REAL NOT NULL DEFAULT 0,
    failure_expected INTEGER NOT NULL DEFAULT 0,
    avoidable INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    diagnosis TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_failure_diagnosis_run_root ON failure_diagnoses(run_id, root_transition_id);
CREATE TABLE IF NOT EXISTS recovery_lessons (
    key TEXT PRIMARY KEY,
    failure_class TEXT NOT NULL,
    root_state_signature TEXT NOT NULL DEFAULT '',
    root_action_signature TEXT NOT NULL,
    selected_action_signature TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    verified_successes INTEGER NOT NULL DEFAULT 0,
    mean_quality REAL NOT NULL DEFAULT 0,
    verified_quality_sum REAL NOT NULL DEFAULT 0,
    verified_quality_count INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'candidate',
    version INTEGER NOT NULL DEFAULT 1,
    diagnosis TEXT NOT NULL DEFAULT '{}',
    candidates TEXT NOT NULL DEFAULT '[]',
    last_run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recovery_lessons_failure ON recovery_lessons(failure_class,status,verified_successes DESC);
CREATE TABLE IF NOT EXISTS company_delegation_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    capability TEXT NOT NULL,
    department TEXT NOT NULL,
    specialist TEXT NOT NULL,
    skill_key TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    verified_successes INTEGER NOT NULL DEFAULT 0,
    verified_failures INTEGER NOT NULL DEFAULT 0,
    total_duration REAL NOT NULL DEFAULT 0,
    last_failure_class TEXT NOT NULL DEFAULT '',
    last_run_id TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(capability, department, specialist, tool)
);
CREATE INDEX IF NOT EXISTS idx_company_delegation_evidence_capability ON company_delegation_evidence(capability, verified_successes DESC, attempts DESC);
CREATE TABLE IF NOT EXISTS company_projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    objective TEXT NOT NULL,
    priority REAL NOT NULL DEFAULT 0.5,
    horizon TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'active',
    criticality REAL NOT NULL DEFAULT 0.5,
    metadata TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_company_projects_status_priority ON company_projects(status, priority DESC, updated_at DESC);
CREATE TABLE IF NOT EXISTS company_project_tasks (
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    specialist TEXT NOT NULL DEFAULT '',
    priority REAL NOT NULL DEFAULT 0.5,
    horizon TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'pending',
    depends_on TEXT NOT NULL DEFAULT '[]',
    estimated_duration REAL NOT NULL DEFAULT 0,
    exclusive_resources TEXT NOT NULL DEFAULT '[]',
    ready INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, task_id),
    FOREIGN KEY(project_id) REFERENCES company_projects(project_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_company_project_tasks_project_status ON company_project_tasks(project_id, status, priority DESC);
CREATE TABLE IF NOT EXISTS transition_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    action TEXT NOT NULL,
    observation_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    verified_count INTEGER NOT NULL DEFAULT 0,
    next_states TEXT NOT NULL DEFAULT '{}',
    outcomes TEXT NOT NULL DEFAULT '{}',
    failures TEXT NOT NULL DEFAULT '{}',
    duration_mean REAL NOT NULL DEFAULT 0,
    duration_m2 REAL NOT NULL DEFAULT 0,
    reward_mean REAL NOT NULL DEFAULT 0,
    reward_m2 REAL NOT NULL DEFAULT 0,
    reward_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    model_version INTEGER NOT NULL DEFAULT 1,
    prediction_count INTEGER NOT NULL DEFAULT 0,
    prediction_error_mean REAL NOT NULL DEFAULT 0,
    prediction_error_m2 REAL NOT NULL DEFAULT 0,
    last_prediction_error REAL NOT NULL DEFAULT 0,
    last_predicted_at TEXT,
    stale INTEGER NOT NULL DEFAULT 0,
    invalidation_count INTEGER NOT NULL DEFAULT 0,
    invalidated_at TEXT,
    invalidation_reason TEXT NOT NULL DEFAULT '',
    invalidation_distribution_shift REAL NOT NULL DEFAULT 0,
    invalidation_error_spike REAL NOT NULL DEFAULT 0,
    invalidation_success_rate_delta REAL NOT NULL DEFAULT 0,
    fresh_observations INTEGER NOT NULL DEFAULT 0,
    UNIQUE(state_signature, action_signature)
);
CREATE INDEX IF NOT EXISTS idx_transition_model_state_action ON transition_models(state_signature, action_signature);
CREATE INDEX IF NOT EXISTS idx_transition_model_last_seen ON transition_models(last_seen_at DESC);
CREATE TABLE IF NOT EXISTS transition_model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    model_version INTEGER NOT NULL,
    snapshot TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(state_signature, action_signature, model_version)
);
CREATE INDEX IF NOT EXISTS idx_transition_model_versions_key ON transition_model_versions(state_signature, action_signature, model_version DESC);
CREATE TABLE IF NOT EXISTS transition_beliefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    hypothesis_key TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    supporting_evidence INTEGER NOT NULL DEFAULT 0,
    contradicting_evidence INTEGER NOT NULL DEFAULT 0,
    probability REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_model_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(state_signature, action_signature, hypothesis_key)
);
CREATE INDEX IF NOT EXISTS idx_transition_beliefs_key ON transition_beliefs(state_signature, action_signature, probability DESC);
CREATE TABLE IF NOT EXISTS transition_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transition_id TEXT UNIQUE,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    next_state TEXT NOT NULL,
    outcome_key TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transition_obs_state_action ON transition_observations(state_signature, action_signature, id DESC);
CREATE TABLE IF NOT EXISTS causal_effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_signature TEXT NOT NULL,
    treatment_action_signature TEXT NOT NULL,
    control_action_signature TEXT NOT NULL,
    treatment_observations INTEGER NOT NULL DEFAULT 0,
    control_observations INTEGER NOT NULL DEFAULT 0,
    association REAL NOT NULL DEFAULT 0,
    controlled_causal_effect REAL NOT NULL DEFAULT 0,
    counterfactual_treatment_success REAL,
    counterfactual_control_success REAL,
    counterfactual_effect REAL,
    evidence_confidence REAL NOT NULL DEFAULT 0,
    confounding_risk REAL NOT NULL DEFAULT 1,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_causal_effect_state ON causal_effects(state_signature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_causal_effect_pair ON causal_effects(treatment_action_signature, control_action_signature, created_at DESC);

CREATE TABLE IF NOT EXISTS prediction_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transition_id TEXT UNIQUE NOT NULL,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    predicted_state TEXT,
    observed_state TEXT NOT NULL,
    top_state_probability REAL NOT NULL DEFAULT 0,
    top_state_hit INTEGER NOT NULL DEFAULT 0,
    state_observed_probability REAL NOT NULL DEFAULT 0,
    state_log_loss REAL NOT NULL DEFAULT 0,
    state_brier REAL NOT NULL DEFAULT 0,
    predicted_success_probability REAL NOT NULL DEFAULT 0,
    observed_success INTEGER NOT NULL DEFAULT 0,
    success_brier REAL NOT NULL DEFAULT 0,
    predicted_verified_probability REAL NOT NULL DEFAULT 0,
    observed_verified INTEGER NOT NULL DEFAULT 0,
    verified_brier REAL NOT NULL DEFAULT 0,
    outcome_log_loss REAL NOT NULL DEFAULT 0,
    duration_error REAL NOT NULL DEFAULT 0,
    reward_error REAL NOT NULL DEFAULT 0,
    value_error REAL,
    total_error REAL NOT NULL DEFAULT 0,
    surprise REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    uncertainty REAL NOT NULL DEFAULT 1,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prediction_errors_state_action ON prediction_errors(state_signature, action_signature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_errors_total ON prediction_errors(total_error DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prediction_errors_created ON prediction_errors(created_at DESC);
CREATE TABLE IF NOT EXISTS state_values (
    state_signature TEXT PRIMARY KEY,
    value REAL NOT NULL DEFAULT 0,
    visits INTEGER NOT NULL DEFAULT 0,
    return_mean REAL NOT NULL DEFAULT 0,
    return_m2 REAL NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    model_version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_state_values_visits ON state_values(visits DESC);
CREATE TABLE IF NOT EXISTS action_values (
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    action TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    visits INTEGER NOT NULL DEFAULT 0,
    return_mean REAL NOT NULL DEFAULT 0,
    return_m2 REAL NOT NULL DEFAULT 0,
    first_seen_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    model_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(state_signature, action_signature)
);
CREATE INDEX IF NOT EXISTS idx_action_values_state ON action_values(state_signature, value DESC);
CREATE TABLE IF NOT EXISTS evolution_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_key TEXT NOT NULL,
    action TEXT NOT NULL,
    reason TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_cycles (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    transitions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    failure TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS learning_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE(run_id, stage)
);
CREATE INDEX IF NOT EXISTS idx_learning_updates_run ON learning_updates(run_id, id);
CREATE INDEX IF NOT EXISTS idx_learning_updates_stage ON learning_updates(stage, started_at)
;
CREATE TABLE IF NOT EXISTS self_model_observations (
    transition_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    tool TEXT NOT NULL,
    context_signature TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    failure INTEGER NOT NULL DEFAULT 0,
    reward REAL NOT NULL DEFAULT 0,
    prediction_error REAL NOT NULL DEFAULT 0,
    confidence_before REAL NOT NULL DEFAULT 0,
    confidence_after REAL NOT NULL DEFAULT 0,
    confidence_available INTEGER NOT NULL DEFAULT 0,
    calibration_error REAL NOT NULL DEFAULT 0,
    brier_error REAL NOT NULL DEFAULT 0,
    observed_cost REAL NOT NULL DEFAULT 0,
    recovered INTEGER NOT NULL DEFAULT 0,
    recovery_success INTEGER NOT NULL DEFAULT 0,
    world_model_version INTEGER NOT NULL DEFAULT 1,
    policy_version INTEGER NOT NULL DEFAULT 1,
    procedure_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_self_model_obs_capability ON self_model_observations(capability, tool, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_self_model_obs_context ON self_model_observations(context_signature, capability, tool, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_self_model_obs_run ON self_model_observations(run_id, created_at);
CREATE TABLE IF NOT EXISTS self_model_metrics (
    capability TEXT NOT NULL,
    tool TEXT NOT NULL,
    context_signature TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    reward_sum REAL NOT NULL DEFAULT 0,
    prediction_error_sum REAL NOT NULL DEFAULT 0,
    confidence_sum REAL NOT NULL DEFAULT 0,
    confidence_count INTEGER NOT NULL DEFAULT 0,
    calibration_error_sum REAL NOT NULL DEFAULT 0,
    calibration_count INTEGER NOT NULL DEFAULT 0,
    brier_error_sum REAL NOT NULL DEFAULT 0,
    brier_count INTEGER NOT NULL DEFAULT 0,
    cost_sum REAL NOT NULL DEFAULT 0,
    recovery_attempts INTEGER NOT NULL DEFAULT 0,
    recovery_successes INTEGER NOT NULL DEFAULT 0,
    last_updated_at TEXT NOT NULL,
    model_version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY(capability, tool, context_signature)
);
CREATE INDEX IF NOT EXISTS idx_self_model_metrics_tool ON self_model_metrics(tool, attempts DESC);
CREATE INDEX IF NOT EXISTS idx_self_model_metrics_context ON self_model_metrics(context_signature, attempts DESC);
CREATE TABLE IF NOT EXISTS language_pattern_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_key TEXT NOT NULL,
    mapping_fingerprint TEXT NOT NULL,
    pattern TEXT NOT NULL,
    operation TEXT NOT NULL,
    capability TEXT NOT NULL DEFAULT '',
    goal_payload TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    verified INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_language_pattern_observation_run ON language_pattern_observations(pattern_key, mapping_fingerprint, run_id);
CREATE INDEX IF NOT EXISTS idx_language_pattern_obs_pattern ON language_pattern_observations(pattern_key, created_at DESC);
CREATE TABLE IF NOT EXISTS language_pattern_mappings (
    pattern_key TEXT NOT NULL,
    mapping_fingerprint TEXT NOT NULL,
    pattern TEXT NOT NULL,
    operation TEXT NOT NULL,
    capability TEXT NOT NULL DEFAULT '',
    goal_payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    successes INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    confidence_sum REAL NOT NULL DEFAULT 0,
    promotion_threshold INTEGER NOT NULL DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'candidate',
    model_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_success_at TEXT,
    last_failure_at TEXT,
    last_updated_at TEXT NOT NULL,
    PRIMARY KEY(pattern_key, mapping_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_language_pattern_mapping_lookup ON language_pattern_mappings(pattern_key, status, successes DESC, attempts DESC);
CREATE INDEX IF NOT EXISTS idx_language_pattern_mapping_operation ON language_pattern_mappings(operation, status, successes DESC);
CREATE TABLE IF NOT EXISTS exploration_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    state_signature TEXT NOT NULL,
    action_signature TEXT NOT NULL,
    tool TEXT NOT NULL,
    action TEXT NOT NULL,
    mode TEXT NOT NULL,
    score REAL NOT NULL DEFAULT 0,
    goal_alignment REAL NOT NULL DEFAULT 0,
    exploitation REAL NOT NULL DEFAULT 0,
    ucb_bonus REAL NOT NULL DEFAULT 0,
    information_gain REAL NOT NULL DEFAULT 0,
    novelty REAL NOT NULL DEFAULT 0,
    relearning_pressure REAL NOT NULL DEFAULT 0,
    risk_penalty REAL NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 0,
    executed INTEGER NOT NULL DEFAULT 0,
    ok INTEGER,
    verified INTEGER,
    reward REAL,
    prediction_error REAL,
    uncertainty_before REAL,
    uncertainty_after REAL,
    realized_information_gain REAL,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exploration_events_state ON exploration_events(state_signature, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exploration_events_tool ON exploration_events(tool, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exploration_events_mode ON exploration_events(mode, created_at DESC);
CREATE TABLE IF NOT EXISTS bandit_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state_signature TEXT NOT NULL,
    arm_signature TEXT NOT NULL,
    reward REAL NOT NULL,
    source_event_id INTEGER,
    observed_at TEXT NOT NULL,
    UNIQUE(source_event_id)
);
CREATE INDEX IF NOT EXISTS idx_bandit_observations_state ON bandit_observations(state_signature, id DESC);
CREATE TABLE IF NOT EXISTS company_change_proposals (
    proposal_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    change_kind TEXT NOT NULL,
    target_key TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    evidence TEXT NOT NULL DEFAULT '[]',
    regression TEXT NOT NULL DEFAULT '{}',
    security_review TEXT NOT NULL DEFAULT '{}',
    executive_approval TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_company_change_status ON company_change_proposals(company_id, status, updated_at DESC);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_fingerprint(value) -> str:
    encoded = _safe_json(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clamp_replay_recency(current_version: int, item_version: int) -> float:
    gap = max(0, int(current_version) - max(1, int(item_version)))
    return 1.0 / (1.0 + gap)


def _connect(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()
    if not journal_mode or str(journal_mode[0]).casefold() != "wal":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(experiences)").fetchall()}
    if "operation" not in columns:
        conn.execute("ALTER TABLE experiences ADD COLUMN operation TEXT NOT NULL DEFAULT ''")
    if "transitions" not in columns:
        conn.execute("ALTER TABLE experiences ADD COLUMN transitions TEXT NOT NULL DEFAULT '[]'")
    exploration_columns = {row[1] for row in conn.execute("PRAGMA table_info(exploration_events)").fetchall()}
    for name, definition in {
        'uncertainty_before': 'REAL',
        'uncertainty_after': 'REAL',
        'realized_information_gain': 'REAL',
    }.items():
        if name not in exploration_columns:
            conn.execute(f"ALTER TABLE exploration_events ADD COLUMN {name} {definition}")
    prior_columns = {row[1] for row in conn.execute("PRAGMA table_info(capability_priors)").fetchall()}
    for name, definition in {
        "origin_class": "TEXT NOT NULL DEFAULT 'learned_prior'",
        "data_class": "TEXT NOT NULL DEFAULT 'learned'",
        "source_ref": "TEXT NOT NULL DEFAULT ''",
        "authoritative": "INTEGER NOT NULL DEFAULT 0",
        "not_user_memory": "INTEGER NOT NULL DEFAULT 1",
        "not_execution_evidence": "INTEGER NOT NULL DEFAULT 1",
        "not_promotion_evidence": "INTEGER NOT NULL DEFAULT 1",
        "not_knowledge": "INTEGER NOT NULL DEFAULT 1",
    }.items():
        if name not in prior_columns:
            conn.execute(f"ALTER TABLE capability_priors ADD COLUMN {name} {definition}")
    conn.execute(
        "UPDATE capability_priors SET origin_class='capability_prior',data_class='benchmark',source_ref='seed://100k-v1',authoritative=0,not_user_memory=1,not_execution_evidence=1,not_promotion_evidence=1,not_knowledge=1 WHERE lower(source) IN ('synthetic_seed','synthetic-seed-filtered') OR lower(source) LIKE 'seed:%'"
    )
    replay_columns = {row[1] for row in conn.execute("PRAGMA table_info(replay_items)").fetchall()}
    for name, definition in {
        "model_version": "INTEGER NOT NULL DEFAULT 1",
        "model_change_recency": "REAL NOT NULL DEFAULT 0",
    }.items():
        if name not in replay_columns:
            conn.execute(f"ALTER TABLE replay_items ADD COLUMN {name} {definition}")

    recovery_columns = {row[1] for row in conn.execute("PRAGMA table_info(recovery_lessons)").fetchall()}
    for name, definition in {
        "root_state_signature": "TEXT NOT NULL DEFAULT ''",
        "verified_quality_sum": "REAL NOT NULL DEFAULT 0",
        "verified_quality_count": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if name not in recovery_columns:
            conn.execute(f"ALTER TABLE recovery_lessons ADD COLUMN {name} {definition}")

    transition_columns = {row[1] for row in conn.execute("PRAGMA table_info(transition_models)").fetchall()}
    for name, definition in {
        "prediction_count": "INTEGER NOT NULL DEFAULT 0",
        "prediction_error_mean": "REAL NOT NULL DEFAULT 0",
        "prediction_error_m2": "REAL NOT NULL DEFAULT 0",
        "last_prediction_error": "REAL NOT NULL DEFAULT 0",
        "last_predicted_at": "TEXT",
        "stale": "INTEGER NOT NULL DEFAULT 0",
        "invalidation_count": "INTEGER NOT NULL DEFAULT 0",
        "invalidated_at": "TEXT",
        "invalidation_reason": "TEXT NOT NULL DEFAULT ''",
        "invalidation_distribution_shift": "REAL NOT NULL DEFAULT 0",
        "invalidation_error_spike": "REAL NOT NULL DEFAULT 0",
        "invalidation_success_rate_delta": "REAL NOT NULL DEFAULT 0",
        "fresh_observations": "INTEGER NOT NULL DEFAULT 0",
        "regime_baseline_observations": "INTEGER NOT NULL DEFAULT 0",
        "regime_baseline_successes": "INTEGER NOT NULL DEFAULT 0",
        "regime_baseline_verified": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if name not in transition_columns:
            conn.execute(f"ALTER TABLE transition_models ADD COLUMN {name} {definition}")

    obs_columns = {row[1] for row in conn.execute("PRAGMA table_info(self_model_observations)").fetchall()}
    for name, definition in {"confidence_available": "INTEGER NOT NULL DEFAULT 0"}.items():
        if name not in obs_columns:
            conn.execute(f"ALTER TABLE self_model_observations ADD COLUMN {name} {definition}")
    metric_columns = {row[1] for row in conn.execute("PRAGMA table_info(self_model_metrics)").fetchall()}
    for name, definition in {
        "confidence_count": "INTEGER NOT NULL DEFAULT 0",
        "calibration_count": "INTEGER NOT NULL DEFAULT 0",
        "brier_count": "INTEGER NOT NULL DEFAULT 0",
    }.items():
        if name not in metric_columns:
            conn.execute(f"ALTER TABLE self_model_metrics ADD COLUMN {name} {definition}")
    # Backfill baseline transition-model snapshots/beliefs only once per database.
    # Older code performed these INSERT-SELECT statements on every connection, which made
    # otherwise cheap planning/retrieval operations repeatedly scan the historical tables.
    migration_key = "learning_backfill_transition_history_v1"
    marker = conn.execute("SELECT value FROM learning_meta WHERE key=?", (migration_key,)).fetchone()
    history_count = int(conn.execute("SELECT COUNT(*) FROM transition_model_versions").fetchone()[0] or 0)
    belief_count = int(conn.execute("SELECT COUNT(*) FROM transition_beliefs").fetchone()[0] or 0)
    transition_model_count = int(conn.execute("SELECT COUNT(*) FROM transition_models").fetchone()[0] or 0)
    # The backfill must be self-healing: a restored/trimmed database can retain the
    # migration marker while losing derived history/belief rows. Re-run only the
    # missing derived projections; INSERT OR IGNORE keeps this idempotent.
    needs_backfill = marker is None or (transition_model_count > 0 and (history_count == 0 or belief_count == 0))
    if needs_backfill:
        conn.execute(
            """INSERT OR IGNORE INTO transition_model_versions(state_signature,action_signature,model_version,snapshot,reason,created_at)
            SELECT state_signature,action_signature,model_version,json_object(
                'state_signature',state_signature,'action_signature',action_signature,'action',json(action),
                'observation_count',observation_count,'success_count',success_count,'verified_count',verified_count,
                'next_states',json(next_states),'outcomes',json(outcomes),'failures',json(failures),
                'duration_mean',duration_mean,'duration_m2',duration_m2,'reward_mean',reward_mean,'reward_m2',reward_m2,
                'reward_count',reward_count,'first_seen_at',first_seen_at,'last_seen_at',last_seen_at,
                'model_version',model_version,'stale',stale,'fresh_observations',fresh_observations),
                'migration:baseline',last_seen_at FROM transition_models"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO transition_beliefs(state_signature,action_signature,hypothesis_key,evidence_count,supporting_evidence,contradicting_evidence,probability,confidence,first_seen_at,last_seen_at,last_model_version)
            SELECT o.state_signature,o.action_signature,o.outcome_key,COUNT(*),COUNT(*),
                (SELECT COUNT(*) FROM transition_observations o2 WHERE o2.state_signature=o.state_signature AND o2.action_signature=o.action_signature AND o2.outcome_key<>o.outcome_key),
                CAST(COUNT(*) AS REAL)/MAX(1,(SELECT COUNT(*) FROM transition_observations o2 WHERE o2.state_signature=o.state_signature AND o2.action_signature=o.action_signature)),
                MIN(1.0,CAST(COUNT(*) AS REAL)/(COUNT(*)+5.0)),MIN(o.observed_at),MAX(o.observed_at),
                COALESCE((SELECT tm.model_version FROM transition_models tm WHERE tm.state_signature=o.state_signature AND tm.action_signature=o.action_signature),1)
            FROM transition_observations o GROUP BY o.state_signature,o.action_signature,o.outcome_key"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO learning_meta(key,value) VALUES(?,?)",
            (migration_key, _now()),
        )
    conn.commit()
    return conn


class LearningStore:
    def __init__(self, path=None):
        configured = path or os.environ.get("AGENT_LEARNING_DB") or DEFAULT_PATH
        self.path = Path(configured)
        conn = _connect(self.path)
        conn.close()

    def upsert_belief(self, *, session_id: str, subject: str, predicate: str, value,
                      confidence: float = 1.0, source: str = 'user', provenance: str = '') -> dict:
        now = _now()
        value_json = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    'SELECT value, revision FROM beliefs WHERE session_id=? AND subject=? AND predicate=? AND status="active"',
                    (str(session_id), str(subject), str(predicate)),
                ).fetchone()
                revision = int(row[1]) + 1 if row else 1
                supersedes = f'{subject}:{predicate}:r{revision - 1}' if row else ''
                if row and row[0] == value_json:
                    revision = int(row[1])
                    supersedes = ''
                else:
                    conn.execute(
                        'INSERT INTO belief_history(session_id,subject,predicate,value,confidence,source,provenance,created_at,revision,status) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        (str(session_id), str(subject), str(predicate), value_json, max(0.0, min(1.0, float(confidence))), str(source),
                         str(provenance), now, revision, 'superseded' if row else 'active'),
                    )
                conf = max(0.0, min(1.0, float(confidence)))
                conn.execute(
                    "INSERT INTO beliefs(session_id,subject,predicate,value,confidence,source,provenance,created_at,updated_at,revision,status,supersedes)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(session_id,subject,predicate) DO UPDATE SET"
                    " value=excluded.value, confidence=excluded.confidence, source=excluded.source,"
                    " provenance=excluded.provenance, updated_at=excluded.updated_at, revision=excluded.revision,"
                    " status='active', supersedes=excluded.supersedes",
                    (str(session_id), str(subject), str(predicate), value_json, conf, str(source), str(provenance),
                     now, now, revision, 'active', supersedes),
                )
                return {
                    'subject': str(subject), 'predicate': str(predicate), 'value': value, 'confidence': conf,
                    'source': str(source), 'provenance': str(provenance), 'revision': revision, 'status': 'active',
                    'supersedes': supersedes, 'updated_at': now,
                }
        finally:
            conn.close()

    def delete_belief(self, *, session_id: str, subject: str, predicate: str) -> int:
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE beliefs SET status='deleted', updated_at=? WHERE session_id=? AND subject=? AND predicate=? AND status='active'",
                    (_now(), str(session_id), str(subject), str(predicate)),
                )
                return int(cur.rowcount or 0)
        finally:
            conn.close()

    def list_beliefs(self, session_id: str, *, limit: int = 100) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT subject,predicate,value,confidence,source,provenance,created_at,updated_at,revision,status,supersedes FROM beliefs WHERE session_id=? AND status='active' ORDER BY updated_at DESC LIMIT ?",
                (str(session_id), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        keys = ('subject','predicate','value','confidence','source','provenance','created_at','updated_at','revision','status','supersedes')
        out = []
        for row in rows:
            item = dict(zip(keys, row))
            try:
                item['value'] = json.loads(item['value'])
            except Exception:
                pass
            out.append(item)
        return out

    def find_beliefs(self, session_id: str, *, subject: str | None = None, predicate: str | None = None,
                     query: str | None = None, limit: int = 12) -> list[dict]:
        rows = self.list_beliefs(session_id, limit=200)
        q = (query or '').casefold().strip()
        tokens = {x for x in q.replace('؟', ' ').replace('?', ' ').split() if x}
        out = []
        for row in rows:
            if subject and row['subject'] != subject:
                continue
            if predicate and row['predicate'] != predicate:
                continue
            hay = f"{row['subject']} {row['predicate']} {row['value']}".casefold()
            if q and q not in hay and tokens and not any(token in hay for token in tokens):
                continue
            out.append(row)
            if len(out) >= max(1, int(limit)):
                break
        return out

    def append_cognitive_event(self, session_id: str, kind: str, payload: dict | None = None) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    'INSERT INTO cognitive_events(session_id,kind,payload,created_at) VALUES(?,?,?,?)',
                    (str(session_id), str(kind), _safe_json(payload or {}), _now()),
                )
        finally:
            conn.close()

    def recent_cognitive_events(self, session_id: str, *, limit: int = 30) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                'SELECT kind,payload,created_at FROM cognitive_events WHERE session_id=? ORDER BY id DESC LIMIT ?',
                (str(session_id), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [
            {'kind': kind, 'payload': json.loads(payload or '{}'), 'created_at': created_at}
            for kind, payload, created_at in rows
        ]

    def begin_learning_cycle(self, run_id: str, *, transitions: int, started_at: str | None = None) -> bool:
        """Create a durable cycle marker; returns False when the run was already completed."""
        timestamp = started_at or _now()
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT status FROM learning_cycles WHERE run_id=?", (str(run_id),)
                ).fetchone()
                if row and row[0] == "completed":
                    return False
                conn.execute(
                    "INSERT INTO learning_cycles(run_id,status,transitions,created_at,failure) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, transitions=excluded.transitions",
                    (str(run_id), "running", max(0, int(transitions)), timestamp, ""),
                )
                return True
        finally:
            conn.close()

    def learning_stage_status(self, run_id: str, stage: str) -> str | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT status FROM learning_updates WHERE run_id=? AND stage=?",
                (str(run_id), str(stage)),
            ).fetchone()
            return str(row[0]) if row else None
        finally:
            conn.close()

    def record_learning_stage(self, run_id: str, stage: str, *, status: str, payload: dict | None = None,
                              error: str = "", started_at: str | None = None, completed_at: str | None = None) -> None:
        start = started_at or _now()
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO learning_updates(run_id,stage,status,payload,error,started_at,completed_at) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(run_id,stage) DO UPDATE SET status=excluded.status,payload=excluded.payload,error=excluded.error,"
                    "started_at=COALESCE(learning_updates.started_at,excluded.started_at),completed_at=excluded.completed_at",
                    (str(run_id), str(stage), str(status), _safe_json(payload or {}), str(error or ""), start, completed_at),
                )
        finally:
            conn.close()

    def complete_learning_cycle(self, run_id: str, *, status: str, failure: str = "", completed_at: str | None = None) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "UPDATE learning_cycles SET status=?,failure=?,completed_at=? WHERE run_id=?",
                    (str(status), str(failure or ""), completed_at or _now(), str(run_id)),
                )
        finally:
            conn.close()

    def learning_cycle(self, run_id: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT run_id,status,transitions,created_at,completed_at,failure FROM learning_cycles WHERE run_id=?",
                (str(run_id),),
            ).fetchone()
            updates = conn.execute(
                "SELECT run_id,stage,status,payload,error,started_at,completed_at FROM learning_updates WHERE run_id=? ORDER BY id",
                (str(run_id),),
            ).fetchall()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "run_id": row[0], "status": row[1], "transitions": int(row[2] or 0),
            "created_at": row[3], "completed_at": row[4], "failure": row[5],
            "stages": [
                {"stage": x[1], "status": x[2], "payload": json.loads(x[3] or "{}"),
                 "error": x[4], "started_at": x[5], "completed_at": x[6]}
                for x in updates
            ],
        }

    def recent_learning_cycles(self, *, limit: int = 50) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT run_id,status,transitions,created_at,completed_at,failure FROM learning_cycles ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"run_id": r[0], "status": r[1], "transitions": int(r[2] or 0), "created_at": r[3],
             "completed_at": r[4], "failure": r[5]} for r in rows
        ]

    def learning_cycle_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            total, completed, failed, running = conn.execute(
                "SELECT COUNT(*),SUM(status='completed'),SUM(status='failed'),SUM(status='running') FROM learning_cycles"
            ).fetchone()
            stages = conn.execute(
                "SELECT stage,COUNT(*) FROM learning_updates WHERE status='completed' GROUP BY stage ORDER BY stage"
            ).fetchall()
        finally:
            conn.close()
        return {
            "cycles": int(total or 0), "completed": int(completed or 0), "failed": int(failed or 0),
            "running": int(running or 0), "completed_stages": {str(k): int(v) for k, v in stages},
        }

    def record_experience(self, record: ExperienceRecord) -> bool:
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO experiences(run_id,goal,task_signature,operation,status,reward,verified_rate,steps,failure_class,lesson_keys,session_id,environment_signature,transitions,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (record.run_id, record.goal, record.task_signature, record.operation, record.status, record.reward,
                     record.verified_rate, _safe_json(record.steps), record.failure_class,
                     _safe_json(record.lesson_keys), record.session_id, record.environment_signature,
                     _safe_json(record.transitions), record.created_at or _now()),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def get_experience(self, run_id: str) -> ExperienceRecord | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT run_id,goal,task_signature,operation,status,reward,verified_rate,steps,failure_class,lesson_keys,session_id,environment_signature,transitions,created_at FROM experiences WHERE run_id=?",
                (run_id,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return ExperienceRecord(
            run_id=row[0], goal=row[1], task_signature=row[2], operation=row[3], status=row[4],
            reward=float(row[5]), verified_rate=float(row[6]), steps=tuple(json.loads(row[7] or "[]")),
            failure_class=row[8], lesson_keys=tuple(json.loads(row[9] or "[]")), session_id=row[10],
            environment_signature=row[11], transitions=tuple(json.loads(row[12] or "[]")), created_at=row[13],
        )

    def upsert_capability_prior(self, *, key: str, domain: str, capability: str, examples: int,
                                phrases: list[str], tokens: list[str], required_tools: list[str],
                                interaction_shapes: list[str], failure_modes: list[str],
                                success_invariants: list[str], confidence: float, source: str,
                                origin_class: str = "learned_prior", data_class: str = "learned",
                                source_ref: str = "", authoritative: bool = False,
                                not_user_memory: bool = True, not_execution_evidence: bool = True,
                                not_promotion_evidence: bool = True, not_knowledge: bool = True) -> None:
        source_norm = str(source or "").casefold().strip()
        if source_norm == "synthetic_seed":
            origin_class = "capability_prior"
            data_class = "benchmark"
            source_ref = source_ref or "seed://100k-v1"
            authoritative = False
            not_user_memory = True
            not_execution_evidence = True
            not_promotion_evidence = True
            not_knowledge = True
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO capability_priors(key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source,origin_class,data_class,source_ref,authoritative,not_user_memory,not_execution_evidence,not_promotion_evidence,not_knowledge,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET domain=excluded.domain,capability=excluded.capability,examples=excluded.examples,phrases=excluded.phrases,tokens=excluded.tokens,required_tools=excluded.required_tools,interaction_shapes=excluded.interaction_shapes,failure_modes=excluded.failure_modes,success_invariants=excluded.success_invariants,confidence=excluded.confidence,source=excluded.source,origin_class=excluded.origin_class,data_class=excluded.data_class,source_ref=excluded.source_ref,authoritative=excluded.authoritative,not_user_memory=excluded.not_user_memory,not_execution_evidence=excluded.not_execution_evidence,not_promotion_evidence=excluded.not_promotion_evidence,not_knowledge=excluded.not_knowledge,updated_at=excluded.updated_at",
                    (str(key),str(domain),str(capability),int(examples),_safe_json(phrases),_safe_json(tokens),_safe_json(required_tools),_safe_json(interaction_shapes),_safe_json(failure_modes),_safe_json(success_invariants),max(0.0,min(1.0,float(confidence))),str(source),str(origin_class),str(data_class),str(source_ref),int(bool(authoritative)),int(bool(not_user_memory)),int(bool(not_execution_evidence)),int(bool(not_promotion_evidence)),int(bool(not_knowledge)),_now()),
                )
        finally:
            conn.close()

    def capability_priors(self, *, limit: int = 500) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT key,domain,capability,examples,phrases,tokens,required_tools,interaction_shapes,failure_modes,success_invariants,confidence,source,origin_class,data_class,source_ref,authoritative,not_user_memory,not_execution_evidence,not_promotion_evidence,not_knowledge,updated_at FROM capability_priors ORDER BY examples DESC,confidence DESC,updated_at DESC LIMIT ?",
                (max(1,int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        def dec(value):
            try: return json.loads(value or '[]')
            except Exception: return []
        return [{
            'key':r[0],'domain':r[1],'capability':r[2],'examples':int(r[3] or 0),'phrases':dec(r[4]),'tokens':dec(r[5]),
            'required_tools':dec(r[6]),'interaction_shapes':dec(r[7]),'failure_modes':dec(r[8]),'success_invariants':dec(r[9]),
            'confidence':float(r[10] or 0.0),'source':r[11], 'origin_class':r[12], 'data_class':r[13],
            'source_ref':r[14], 'authoritative':bool(r[15]), 'not_user_memory':bool(r[16]),
            'not_execution_evidence':bool(r[17]), 'not_promotion_evidence':bool(r[18]),
            'not_knowledge':bool(r[19]), 'updated_at':r[20],
        } for r in rows]

    def record_capability_meta(self, key: str, value: str) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute("INSERT INTO capability_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(key),str(value)))
        finally:
            conn.close()

    def capability_meta(self, key: str) -> str | None:
        conn = _connect(self.path)
        try:
            row = conn.execute("SELECT value FROM capability_meta WHERE key=?", (str(key),)).fetchone()
        finally:
            conn.close()
        return str(row[0]) if row else None

    def similar_experiences(self, task_signature: str, *, limit: int = 20) -> list[ExperienceRecord]:
        """Return exact task-family matches first, then semantically related signatures.

        Layer 5 needs some generalization but must avoid broad fuzzy retrieval. The fallback
        uses token-set Jaccard over the normalized task signatures and only admits >= 0.5.
        """
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT run_id,goal,task_signature,operation,status,reward,verified_rate,steps,failure_class,lesson_keys,session_id,environment_signature,transitions,created_at FROM experiences ORDER BY created_at DESC,id DESC LIMIT ?",
                (max(limit * 5, 50),),
            ).fetchall()
        finally:
            conn.close()
        target=set(str(task_signature).split())
        scored=[]
        for r in rows:
            sig=set(str(r[2]).split())
            if str(r[2]) == str(task_signature):
                score=1.0
            elif target and sig:
                inter=len(target & sig); union=len(target | sig)
                score=inter/max(1,union)
                if score < 0.5:
                    continue
            else:
                continue
            scored.append((score,r))
        scored.sort(key=lambda x:(-x[0], x[1][13], x[1][0]))
        return [ExperienceRecord(run_id=r[0], goal=r[1], task_signature=r[2], operation=r[3], status=r[4],
                                 reward=float(r[5]), verified_rate=float(r[6]), steps=tuple(json.loads(r[7] or "[]")),
                                 failure_class=r[8], lesson_keys=tuple(json.loads(r[9] or "[]")), session_id=r[10],
                                 environment_signature=r[11], transitions=tuple(json.loads(r[12] or "[]")), created_at=r[13])
                for _, r in scored[:limit]]

    def recent_experiences(self, limit: int = 50) -> list[ExperienceRecord]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT run_id,goal,task_signature,operation,status,reward,verified_rate,steps,failure_class,lesson_keys,session_id,environment_signature,transitions,created_at FROM experiences ORDER BY created_at DESC,id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [ExperienceRecord(run_id=r[0], goal=r[1], task_signature=r[2], operation=r[3], status=r[4],
                                 reward=float(r[5]), verified_rate=float(r[6]), steps=tuple(json.loads(r[7] or "[]")),
                                 failure_class=r[8], lesson_keys=tuple(json.loads(r[9] or "[]")), session_id=r[10],
                                 environment_signature=r[11], transitions=tuple(json.loads(r[12] or "[]")), created_at=r[13])
                for r in rows]

    # Compatibility/query surface used by the V23 Brain. These methods intentionally
    # live on the canonical learning store so the brain and Layer-5 runtime share one
    # evidence substrate rather than maintaining a second learning database.
    def record(self, *, session_id: str | None, user_text: str, operation: str = '', capability: str = '',
               tool: str = '', status: str, verified: bool = False, reward: float = 0.0,
               trace: list[dict] | None = None, plan_signature: str = '', lesson: str = '') -> None:
        """Legacy Brain API adapter backed by this same canonical LearningStore."""
        import uuid
        from app.learning.diagnosis import task_signature, sanitize
        try:
            plan = json.loads(plan_signature or '[]')
        except Exception:
            plan = []
        steps = []
        if isinstance(plan, list):
            for index, item in enumerate(plan, 1):
                if not isinstance(item, dict) or not item.get('tool'):
                    continue
                steps.append({
                    'step': str(item.get('step_id') or item.get('id') or f's{index}'),
                    'tool': str(item.get('tool')),
                    'status': 'done' if verified else status,
                    'verified': bool(verified),
                    'error': '' if verified else sanitize(lesson, 320),
                    'attempts': int(item.get('attempts') or 1),
                    'capability': str(item.get('capability') or capability or item.get('tool')),
                    'depends_on': tuple(item.get('depends_on') or ()),
                })
        if not steps and tool:
            steps = [{
                'step': 's1', 'tool': tool, 'status': status, 'verified': bool(verified),
                'error': '' if verified else sanitize(lesson, 320), 'attempts': 1,
                'capability': capability or tool, 'depends_on': (),
            }]
        record = ExperienceRecord(
            run_id=uuid.uuid4().hex, goal=str(user_text or ''), task_signature=task_signature(str(user_text or operation)),
            operation=str(operation or ''), status=str(status), reward=float(reward),
            verified_rate=1.0 if verified and steps else 0.0, steps=tuple(steps), failure_class=None if verified else 'execution',
            lesson_keys=(), session_id=session_id, created_at='', environment_signature='', transitions=(),
        )
        self.record_experience(record)

    def successful_methods(self, operation: str, *, limit: int = 12) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT operation,reward,steps FROM experiences WHERE operation=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (operation, max(int(limit) * 6, 24)),
            ).fetchall()
        finally:
            conn.close()
        grouped: dict[tuple[str, str], dict[str, float]] = {}
        for _operation, episode_reward, steps_json in rows:
            try:
                steps = json.loads(steps_json or '[]')
            except Exception:
                steps = []
            for step in steps if isinstance(steps, list) else []:
                if not isinstance(step, dict):
                    continue
                tool = str(step.get('tool') or '')
                capability = str(step.get('capability') or tool)
                if not tool:
                    continue
                key = (capability, tool)
                bucket = grouped.setdefault(key, {'uses': 0.0, 'reward_sum': 0.0})
                bucket['uses'] += 1.0
                # The episode reward is the only durable reward available at this compatibility
                # surface. Per-transition reward is consumed by the Phase-4 value model.
                bucket['reward_sum'] += float(episode_reward or 0.0)
        items = [
            {'capability': cap, 'tool': tool, 'uses': int(data['uses']),
             'reward': round(data['reward_sum'] / max(1.0, data['uses']), 3)}
            for (cap, tool), data in grouped.items()
        ]
        items.sort(key=lambda item: (-float(item['reward']), -int(item['uses']), item['tool']))
        return items[:max(1, int(limit))]

    def by_tool(self, *, limit: int = 200) -> list[dict]:
        """Return observed step-level tool evidence from canonical episode history."""
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT operation,status,verified_rate,reward,created_at,steps FROM experiences ORDER BY id DESC LIMIT ?",
                (max(1, int(limit) * 2),),
            ).fetchall()
        finally:
            conn.close()
        out: list[dict] = []
        for operation, status, verified_rate, reward, created_at, steps_json in rows:
            try:
                steps = json.loads(steps_json or '[]')
            except Exception:
                steps = []
            if not isinstance(steps, list) or not steps:
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                tool = str(step.get('tool') or '')
                if not tool:
                    continue
                out.append({
                    'operation': str(operation or ''),
                    'capability': str(step.get('capability') or tool),
                    'tool': tool,
                    'status': str(step.get('status') or status or ''),
                    'verified': bool(step.get('verified', str(step.get('status') or '') == 'done' and float(verified_rate or 0.0) >= 0.80)),
                    'reward': float(reward or 0.0),
                    'lesson': str(step.get('error') or ''),
                    'created_at': created_at,
                })
                if len(out) >= int(limit):
                    return out[:max(1, int(limit))]
        return out[:max(1, int(limit))]

    def procedure_candidates(self, operation: str, *, limit: int = 12) -> list[dict]:
        # Procedural candidates are now derived from the canonical episode table. A candidate
        # requires repeated identical tool topology; one observed execution is never enough.
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT run_id,task_signature,status,reward,steps,created_at FROM experiences WHERE operation=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (operation, max(int(limit) * 8, 32)),
            ).fetchall()
        finally:
            conn.close()
        groups: dict[tuple[str, ...], dict[str, Any]] = {}
        for run_id, signature, status, reward, steps_json, created_at in rows:
            try:
                steps = json.loads(steps_json or '[]')
            except Exception:
                steps = []
            workflow = tuple(str(step.get('tool') or '') for step in steps if isinstance(step, dict) and step.get('tool'))
            if len(workflow) < 2:
                continue
            group = groups.setdefault(workflow, {'successes': 0, 'failures': 0, 'rewards': [], 'runs': [], 'task_signature': signature, 'last': created_at})
            if str(status) == 'completed':
                group['successes'] += 1
            else:
                group['failures'] += 1
            group['rewards'].append(float(reward or 0.0))
            group['runs'].append(str(run_id))
        out = []
        for workflow, group in groups.items():
            total = group['successes'] + group['failures']
            if group['successes'] < 1:
                continue
            signature = f"{operation}|{'->'.join(workflow)}"
            out.append({
                'signature': signature,
                'operation': operation,
                'workflow': list(workflow),
                'successes': group['successes'],
                'failures': group['failures'],
                'avg_reward': sum(group['rewards']) / max(1, len(group['rewards'])),
                'lesson': f"derived from repeated verified/complete topology ({min(total, 20)} observed runs)",
            })
        out.sort(key=lambda x: (-x['successes'], -x['avg_reward'], x['failures'], x['signature']))
        return out[:max(1, int(limit))]


    @staticmethod
    def _append_transition_model_version_locked(conn, *, state_signature: str, action_signature: str, created_at: str, reason: str) -> None:
        row = conn.execute(
            "SELECT action,observation_count,success_count,verified_count,next_states,outcomes,failures,duration_mean,duration_m2,reward_mean,reward_m2,reward_count,first_seen_at,last_seen_at,model_version,stale,fresh_observations FROM transition_models WHERE state_signature=? AND action_signature=?",
            (str(state_signature), str(action_signature)),
        ).fetchone()
        if not row:
            return
        snapshot = {
            "state_signature": str(state_signature), "action_signature": str(action_signature),
            "action": json.loads(row[0] or '{}'), "observation_count": int(row[1]),
            "success_count": int(row[2]), "verified_count": int(row[3]),
            "next_states": json.loads(row[4] or '{}'), "outcomes": json.loads(row[5] or '{}'),
            "failures": json.loads(row[6] or '{}'), "duration_mean": float(row[7]),
            "duration_m2": float(row[8]), "reward_mean": float(row[9]), "reward_m2": float(row[10]),
            "reward_count": int(row[11]), "first_seen_at": str(row[12]), "last_seen_at": str(row[13]),
            "model_version": int(row[14]), "stale": bool(row[15]), "fresh_observations": int(row[16]),
        }
        conn.execute(
            "INSERT OR IGNORE INTO transition_model_versions(state_signature,action_signature,model_version,snapshot,reason,created_at) VALUES(?,?,?,?,?,?)",
            (str(state_signature), str(action_signature), int(row[14]), _safe_json(snapshot), str(reason), str(created_at)),
        )

    @staticmethod
    def _upsert_transition_beliefs_locked(conn, *, state_signature: str, action_signature: str, hypothesis_key: str, model_version: int, observed_at: str) -> None:
        total_before = int(conn.execute(
            "SELECT COALESCE(SUM(evidence_count),0) FROM transition_beliefs WHERE state_signature=? AND action_signature=?",
            (str(state_signature), str(action_signature)),
        ).fetchone()[0] or 0)
        existing = conn.execute(
            "SELECT evidence_count,supporting_evidence,contradicting_evidence,first_seen_at FROM transition_beliefs WHERE state_signature=? AND action_signature=? AND hypothesis_key=?",
            (str(state_signature), str(action_signature), str(hypothesis_key)),
        ).fetchone()
        if existing is None:
            evidence, support, contradiction, first_seen = 1, 1, total_before, str(observed_at)
        else:
            evidence = int(existing[0]) + 1
            support = int(existing[1]) + 1
            contradiction = int(existing[2]) + total_before - int(existing[0])
            first_seen = str(existing[3])
        total_after = total_before + 1
        probability = support / max(1, total_after)
        confidence = min(1.0, evidence / (evidence + 5.0))
        conn.execute(
            "INSERT INTO transition_beliefs(state_signature,action_signature,hypothesis_key,evidence_count,supporting_evidence,contradicting_evidence,probability,confidence,first_seen_at,last_seen_at,last_model_version) VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(state_signature,action_signature,hypothesis_key) DO UPDATE SET evidence_count=excluded.evidence_count,supporting_evidence=excluded.supporting_evidence,contradicting_evidence=excluded.contradicting_evidence,probability=excluded.probability,confidence=excluded.confidence,last_seen_at=excluded.last_seen_at,last_model_version=excluded.last_model_version",
            (str(state_signature), str(action_signature), str(hypothesis_key), evidence, support, contradiction, probability, confidence, first_seen, str(observed_at), int(model_version)),
        )
        conn.execute(
            "UPDATE transition_beliefs SET contradicting_evidence=contradicting_evidence+1,last_model_version=? WHERE state_signature=? AND action_signature=? AND hypothesis_key<>?",
            (int(model_version), str(state_signature), str(action_signature), str(hypothesis_key)),
        )

    def upsert_transition_observation(self, *, state_signature: str, action_signature: str, action: dict,
                                      next_state: str, outcome_key: str, failure_key: str | None,
                                      ok: bool, verified: bool, duration_seconds: float,
                                      reward: float | None, observed_at: str | None = None,
                                      transition_id: str | None = None) -> None:
        now = observed_at or _now()
        conn = _connect(self.path)
        try:
            with conn:
                tid = str(transition_id or '') or None
                if tid:
                    seen = conn.execute("SELECT 1 FROM transition_observations WHERE transition_id=?", (tid,)).fetchone()
                    if seen:
                        return
                row = conn.execute(
                    "SELECT observation_count,success_count,verified_count,next_states,outcomes,failures,duration_mean,duration_m2,reward_mean,reward_m2,reward_count,first_seen_at,stale,fresh_observations,regime_baseline_observations,regime_baseline_successes,regime_baseline_verified FROM transition_models WHERE state_signature=? AND action_signature=?",
                    (state_signature, action_signature),
                ).fetchone()
                if row is None:
                    count = 0; success = 0; verified_count = 0
                    next_states = {}; outcomes = {}; failures = {}
                    duration_mean = 0.0; duration_m2 = 0.0
                    reward_mean = 0.0; reward_m2 = 0.0; reward_count = 0
                    first_seen = now; was_stale = 0; fresh = 0
                    baseline_obs = 0; baseline_success = 0; baseline_verified = 0
                else:
                    count, success, verified_count = map(int, row[:3])
                    next_states = json.loads(row[3] or '{}'); outcomes = json.loads(row[4] or '{}'); failures = json.loads(row[5] or '{}')
                    duration_mean = float(row[6]); duration_m2 = float(row[7])
                    reward_mean = float(row[8]); reward_m2 = float(row[9]); reward_count = int(row[10]); first_seen = row[11]
                    was_stale = int(row[12] or 0); fresh = int(row[13] or 0)
                    baseline_obs = int(row[14] or 0); baseline_success = int(row[15] or 0); baseline_verified = int(row[16] or 0)
                count += 1
                success += int(bool(ok))
                verified_count += int(bool(verified))
                next_states[str(next_state)] = int(next_states.get(str(next_state), 0)) + 1
                outcomes[str(outcome_key)] = int(outcomes.get(str(outcome_key), 0)) + 1
                if failure_key:
                    failures[str(failure_key)] = int(failures.get(str(failure_key), 0)) + 1
                delta = float(duration_seconds) - duration_mean
                duration_mean += delta / count
                duration_m2 += delta * (float(duration_seconds) - duration_mean)
                if reward is not None:
                    reward_count += 1
                    rdelta = float(reward) - reward_mean
                    reward_mean += rdelta / reward_count
                    reward_m2 += rdelta * (float(reward) - reward_mean)
                if was_stale:
                    fresh = fresh + 1
                fresh_success = max(0, success - baseline_success) if was_stale else 0
                # A new regime is only trusted after fresh evidence shows recovery. Three fresh
                # failures must not clear stale status.
                if was_stale and fresh >= 3 and fresh_success >= 2:
                    stale_after = 0
                    fresh_after = fresh
                else:
                    stale_after = was_stale
                    fresh_after = fresh
                conn.execute(
                    "INSERT INTO transition_models(state_signature,action_signature,action,observation_count,success_count,verified_count,next_states,outcomes,failures,duration_mean,duration_m2,reward_mean,reward_m2,reward_count,first_seen_at,last_seen_at,model_version,stale,fresh_observations,regime_baseline_observations,regime_baseline_successes,regime_baseline_verified) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?) "
                    "ON CONFLICT(state_signature,action_signature) DO UPDATE SET action=excluded.action,observation_count=excluded.observation_count,success_count=excluded.success_count,verified_count=excluded.verified_count,next_states=excluded.next_states,outcomes=excluded.outcomes,failures=excluded.failures,duration_mean=excluded.duration_mean,duration_m2=excluded.duration_m2,reward_mean=excluded.reward_mean,reward_m2=excluded.reward_m2,reward_count=excluded.reward_count,first_seen_at=excluded.first_seen_at,last_seen_at=excluded.last_seen_at,model_version=transition_models.model_version+1,stale=excluded.stale,fresh_observations=excluded.fresh_observations,regime_baseline_observations=excluded.regime_baseline_observations,regime_baseline_successes=excluded.regime_baseline_successes,regime_baseline_verified=excluded.regime_baseline_verified",
                    (state_signature, action_signature, _safe_json(action), count, success, verified_count, _safe_json(next_states), _safe_json(outcomes), _safe_json(failures), duration_mean, duration_m2, reward_mean, reward_m2, reward_count, first_seen, now, int(stale_after), int(fresh_after), baseline_obs, baseline_success, baseline_verified),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO transition_observations(transition_id,state_signature,action_signature,next_state,outcome_key,ok,verified,observed_at) VALUES(?,?,?,?,?,?,?,?)",
                    (tid, state_signature, action_signature, str(next_state), str(outcome_key), int(bool(ok)), int(bool(verified)), now),
                )
                current = conn.execute(
                    "SELECT model_version FROM transition_models WHERE state_signature=? AND action_signature=?",
                    (state_signature, action_signature),
                ).fetchone()
                version = int(current[0] or 1) if current else 1
                self._append_transition_model_version_locked(
                    conn, state_signature=state_signature, action_signature=action_signature,
                    created_at=now, reason="observation",
                )
                self._upsert_transition_beliefs_locked(
                    conn, state_signature=state_signature, action_signature=action_signature,
                    hypothesis_key=str(outcome_key), model_version=version, observed_at=now,
                )
        finally:
            conn.close()

    def transition_model_history(self, state_signature: str, action_signature: str, *, limit: int = 100) -> list[dict]:
        conn=_connect(self.path)
        try:
            rows=conn.execute("SELECT state_signature,action_signature,model_version,snapshot,reason,created_at FROM transition_model_versions WHERE state_signature=? AND action_signature=? ORDER BY model_version DESC LIMIT ?",(str(state_signature),str(action_signature),max(1,int(limit)))).fetchall()
        finally:
            conn.close()
        return [{"state_signature":r[0],"action_signature":r[1],"model_version":int(r[2]),"snapshot":json.loads(r[3] or '{}'),"reason":r[4],"created_at":r[5]} for r in rows]

    def transition_beliefs(self, state_signature: str, action_signature: str, *, limit: int = 100) -> list[dict]:
        conn=_connect(self.path)
        try:
            rows=conn.execute("SELECT state_signature,action_signature,hypothesis_key,evidence_count,supporting_evidence,contradicting_evidence,probability,confidence,first_seen_at,last_seen_at,last_model_version FROM transition_beliefs WHERE state_signature=? AND action_signature=? ORDER BY probability DESC,evidence_count DESC,hypothesis_key ASC LIMIT ?",(str(state_signature),str(action_signature),max(1,int(limit)))).fetchall()
        finally:
            conn.close()
        return [{"state_signature":r[0],"action_signature":r[1],"hypothesis_key":r[2],"evidence_count":int(r[3]),"supporting_evidence":int(r[4]),"contradicting_evidence":int(r[5]),"probability":float(r[6]),"confidence":float(r[7]),"first_seen_at":r[8],"last_seen_at":r[9],"last_model_version":int(r[10])} for r in rows]

    def transition_observations_for_action(self, action_signature: str, *, limit: int = 1000) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT transition_id,state_signature,action_signature,next_state,outcome_key,ok,verified,observed_at FROM transition_observations WHERE action_signature=? ORDER BY id DESC LIMIT ?",
                (str(action_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [{
            "transition_id": r[0], "state_signature": r[1], "action_signature": r[2],
            "next_state": r[3], "outcome_key": r[4], "ok": bool(r[5]), "verified": bool(r[6]), "observed_at": r[7],
        } for r in rows]

    def transition_observations(self, state_signature: str, action_signature: str, *, limit: int = 500) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT transition_id,state_signature,action_signature,next_state,outcome_key,ok,verified,observed_at FROM transition_observations WHERE state_signature=? AND action_signature=? ORDER BY id DESC LIMIT ?",
                (str(state_signature), str(action_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [{
            "transition_id": r[0], "state_signature": r[1], "action_signature": r[2],
            "next_state": r[3], "outcome_key": r[4], "ok": bool(r[5]), "verified": bool(r[6]), "observed_at": r[7],
        } for r in rows]

    def record_causal_effect(self, estimate: dict) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO causal_effects(state_signature,treatment_action_signature,control_action_signature,treatment_observations,control_observations,association,controlled_causal_effect,counterfactual_treatment_success,counterfactual_control_success,counterfactual_effect,evidence_confidence,confounding_risk,method,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(estimate.get("state_signature") or ""), str(estimate.get("treatment_action_signature") or ""),
                     str(estimate.get("control_action_signature") or ""), int(estimate.get("treatment_observations", 0) or 0),
                     int(estimate.get("control_observations", 0) or 0), float(estimate.get("association", 0) or 0),
                     float(estimate.get("controlled_causal_effect", 0) or 0), estimate.get("counterfactual_treatment_success"),
                     estimate.get("counterfactual_control_success"), estimate.get("counterfactual_effect"),
                     float(estimate.get("evidence_confidence", 0) or 0), float(estimate.get("confounding_risk", 1) or 0),
                     str(estimate.get("method") or ""), str(estimate.get("created_at") or _now())),
                )
        finally:
            conn.close()

    def causal_effects(self, state_signature: str | None = None, *, limit: int = 50) -> list[dict]:
        conn = _connect(self.path)
        try:
            if state_signature:
                rows = conn.execute("SELECT state_signature,treatment_action_signature,control_action_signature,treatment_observations,control_observations,association,controlled_causal_effect,counterfactual_treatment_success,counterfactual_control_success,counterfactual_effect,evidence_confidence,confounding_risk,method,created_at FROM causal_effects WHERE state_signature=? ORDER BY id DESC LIMIT ?", (str(state_signature), max(1, int(limit)))).fetchall()
            else:
                rows = conn.execute("SELECT state_signature,treatment_action_signature,control_action_signature,treatment_observations,control_observations,association,controlled_causal_effect,counterfactual_treatment_success,counterfactual_control_success,counterfactual_effect,evidence_confidence,confounding_risk,method,created_at FROM causal_effects ORDER BY id DESC LIMIT ?", (max(1, int(limit)),)).fetchall()
        finally:
            conn.close()
        return [{
            "state_signature": r[0], "treatment_action_signature": r[1], "control_action_signature": r[2],
            "treatment_observations": int(r[3]), "control_observations": int(r[4]), "association": float(r[5]),
            "controlled_causal_effect": float(r[6]), "counterfactual_treatment_success": r[7],
            "counterfactual_control_success": r[8], "counterfactual_effect": r[9],
            "evidence_confidence": float(r[10]), "confounding_risk": float(r[11]), "method": r[12], "created_at": r[13],
        } for r in rows]

    def transition_prediction_error_series(self, state_signature: str, action_signature: str, *, limit: int = 24) -> list[float]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT total_error FROM prediction_errors WHERE state_signature=? AND action_signature=? ORDER BY id DESC LIMIT ?",
                (str(state_signature), str(action_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [float(r[0] or 0.0) for r in rows]

    def transition_outcome_series(self, state_signature: str, action_signature: str, *, limit: int = 24) -> list[float]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT ok FROM transition_observations WHERE state_signature=? AND action_signature=? ORDER BY id DESC LIMIT ?",
                (str(state_signature), str(action_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [float(r[0] or 0.0) for r in rows]

    def transition_outcome_signatures(self, state_signature: str, action_signature: str, *, limit: int = 24) -> list[str]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT outcome_key FROM transition_observations WHERE state_signature=? AND action_signature=? ORDER BY id DESC LIMIT ?",
                (str(state_signature), str(action_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [str(r[0] or '') for r in rows]

    def invalidate_transition_model(self, state_signature: str, action_signature: str, *, reason: str,
                                    distribution_shift: float = 0.0, error_spike: float = 0.0,
                                    success_rate_delta: float = 0.0,
                                    regime_baseline_observations: int | None = None,
                                    regime_baseline_successes: int | None = None,
                                    regime_baseline_verified: int | None = None,
                                    initial_fresh_observations: int = 0) -> dict:
        now = _now()
        conn = _connect(self.path)
        try:
            with conn:
                current = conn.execute(
                    "SELECT observation_count,success_count,verified_count FROM transition_models WHERE state_signature=? AND action_signature=? AND stale=0",
                    (str(state_signature), str(action_signature)),
                ).fetchone()
                if current:
                    baseline_obs = int(current[0]) if regime_baseline_observations is None else max(0, min(int(current[0]), int(regime_baseline_observations)))
                    baseline_success = int(current[1]) if regime_baseline_successes is None else max(0, min(int(current[1]), int(regime_baseline_successes)))
                    baseline_verified = int(current[2]) if regime_baseline_verified is None else max(0, min(int(current[2]), int(regime_baseline_verified)))
                else:
                    baseline_obs = baseline_success = baseline_verified = 0
                conn.execute(
                    "UPDATE transition_models SET stale=1,invalidation_count=invalidation_count+1,invalidated_at=?,invalidation_reason=?,invalidation_distribution_shift=?,invalidation_error_spike=?,invalidation_success_rate_delta=?,fresh_observations=?,regime_baseline_observations=?,regime_baseline_successes=?,regime_baseline_verified=?,model_version=model_version+1 WHERE state_signature=? AND action_signature=? AND stale=0",
                    (now, str(reason)[:500], float(distribution_shift), float(error_spike), float(success_rate_delta),
                     max(0, int(initial_fresh_observations)), baseline_obs, baseline_success, baseline_verified,
                     str(state_signature), str(action_signature)),
                )
                self._append_transition_model_version_locked(
                    conn, state_signature=state_signature, action_signature=action_signature,
                    created_at=now, reason=f"invalidation:{reason}",
                )
        finally:
            conn.close()
        return self.get_transition_model(state_signature, action_signature) or {}

    def model_invalidation_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT COUNT(*),SUM(stale),SUM(invalidation_count),COALESCE(AVG(invalidation_error_spike),0),COALESCE(AVG(invalidation_distribution_shift),0) FROM transition_models"
            ).fetchone()
        finally:
            conn.close()
        return {
            "models": int(row[0] or 0),
            "stale_models": int(row[1] or 0),
            "invalidation_events": int(row[2] or 0),
            "mean_error_spike": round(float(row[3] or 0.0), 6),
            "mean_distribution_shift": round(float(row[4] or 0.0), 6),
            "version": 1,
        }

    def actions_for_state(self, state_signature: str, *, limit: int = 20) -> list[dict]:
        """Return distinct empirically observed actions available from a learned state.

        This is a read-only query used by Phase 7 search control. It never creates or
        updates learning records and therefore cannot turn an imagined action into evidence.
        """
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT state_signature,action_signature,action,observation_count,success_count,verified_count,model_version,prediction_count,prediction_error_mean,last_prediction_error FROM transition_models WHERE state_signature=? ORDER BY observation_count DESC, success_count DESC, verified_count DESC, last_seen_at DESC, id DESC LIMIT ?",
                (str(state_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [{
            "state_signature": r[0],
            "action_signature": r[1],
            "action": json.loads(r[2] or "{}"),
            "observation_count": int(r[3]),
            "success_count": int(r[4]),
            "verified_count": int(r[5]),
            "model_version": int(r[6]),
            "prediction_count": int(r[7]),
            "prediction_error_mean": float(r[8]),
            "last_prediction_error": float(r[9]),
        } for r in rows]

    def get_transition_model(self, state_signature: str, action_signature: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT state_signature,action_signature,action,observation_count,success_count,verified_count,next_states,outcomes,failures,duration_mean,duration_m2,reward_mean,reward_m2,reward_count,first_seen_at,last_seen_at,model_version,prediction_count,prediction_error_mean,prediction_error_m2,last_prediction_error,last_predicted_at,stale,invalidation_count,invalidated_at,invalidation_reason,invalidation_distribution_shift,invalidation_error_spike,invalidation_success_rate_delta,fresh_observations,regime_baseline_observations,regime_baseline_successes,regime_baseline_verified FROM transition_models WHERE state_signature=? AND action_signature=?",
                (state_signature, action_signature),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "state_signature": row[0], "action_signature": row[1], "action": json.loads(row[2] or '{}'),
            "observation_count": int(row[3]), "success_count": int(row[4]), "verified_count": int(row[5]),
            "next_states": json.loads(row[6] or '{}'), "outcomes": json.loads(row[7] or '{}'), "failures": json.loads(row[8] or '{}'),
            "duration_mean": float(row[9]), "duration_m2": float(row[10]), "reward_mean": float(row[11]), "reward_m2": float(row[12]),
            "reward_count": int(row[13]), "first_seen_at": row[14], "last_seen_at": row[15], "model_version": int(row[16]),
            "prediction_count": int(row[17]), "prediction_error_mean": float(row[18]),
            "prediction_error_m2": float(row[19]), "last_prediction_error": float(row[20]),
            "last_predicted_at": row[21], "stale": bool(row[22]),
            "invalidation_count": int(row[23]), "invalidated_at": row[24],
            "invalidation_reason": row[25], "invalidation_distribution_shift": float(row[26]),
            "invalidation_error_spike": float(row[27]), "invalidation_success_rate_delta": float(row[28]),
            "fresh_observations": int(row[29] or 0),
            "regime_baseline_observations": int(row[30] or 0),
            "regime_baseline_successes": int(row[31] or 0),
            "regime_baseline_verified": int(row[32] or 0),
        }

    def record_prediction_error(self, record: dict) -> bool:
        """Persist one pre-update prediction error and update the model's error statistics."""
        if not isinstance(record, dict) or not str(record.get("transition_id") or ""):
            return False
        transition_id = str(record["transition_id"])
        now = str(record.get("created_at") or _now())
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO prediction_errors(transition_id,state_signature,action_signature,predicted_state,observed_state,top_state_probability,top_state_hit,state_observed_probability,state_log_loss,state_brier,predicted_success_probability,observed_success,success_brier,predicted_verified_probability,observed_verified,verified_brier,outcome_log_loss,duration_error,reward_error,value_error,total_error,surprise,confidence,uncertainty,evidence_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        transition_id, str(record.get("state_signature") or ""), str(record.get("action_signature") or ""),
                        record.get("predicted_state"), str(record.get("observed_state") or ""),
                        float(record.get("top_state_probability", 0.0)), int(bool(record.get("top_state_hit"))),
                        float(record.get("state_observed_probability", 0.0)), float(record.get("state_log_loss", 0.0)),
                        float(record.get("state_brier", 0.0)), float(record.get("predicted_success_probability", 0.0)),
                        int(bool(record.get("observed_success"))), float(record.get("success_brier", 0.0)),
                        float(record.get("predicted_verified_probability", 0.0)), int(bool(record.get("observed_verified"))),
                        float(record.get("verified_brier", 0.0)), float(record.get("outcome_log_loss", 0.0)),
                        float(record.get("duration_error", 0.0)), float(record.get("reward_error", 0.0)),
                        (float(record["value_error"]) if record.get("value_error") is not None else None),
                        float(record.get("total_error", 0.0)), float(record.get("surprise", 0.0)),
                        float(record.get("confidence", 0.0)), float(record.get("uncertainty", 1.0)),
                        int(record.get("evidence_count", 0) or 0), now,
                    ),
                )
                if cur.rowcount != 1:
                    return False
                state_signature = str(record.get("state_signature") or "")
                action_signature = str(record.get("action_signature") or "")
                model = conn.execute(
                    "SELECT prediction_count,prediction_error_mean,prediction_error_m2 FROM transition_models WHERE state_signature=? AND action_signature=?",
                    (state_signature, action_signature),
                ).fetchone()
                if model is not None:
                    count, mean, m2 = int(model[0]), float(model[1]), float(model[2])
                    count += 1
                    error = max(0.0, min(1.0, float(record.get("total_error", 0.0))))
                    delta = error - mean
                    mean += delta / count
                    m2 += delta * (error - mean)
                    conn.execute(
                        "UPDATE transition_models SET prediction_count=?,prediction_error_mean=?,prediction_error_m2=?,last_prediction_error=?,last_predicted_at=? WHERE state_signature=? AND action_signature=?",
                        (count, mean, m2, error, now, state_signature, action_signature),
                    )
                return True
        finally:
            conn.close()

    def recent_prediction_errors(self, *, limit: int = 100) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT transition_id,state_signature,action_signature,predicted_state,observed_state,top_state_probability,top_state_hit,state_observed_probability,state_log_loss,state_brier,predicted_success_probability,observed_success,success_brier,predicted_verified_probability,observed_verified,verified_brier,outcome_log_loss,duration_error,reward_error,value_error,total_error,surprise,confidence,uncertainty,evidence_count,created_at FROM prediction_errors ORDER BY created_at DESC,id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        keys=("transition_id","state_signature","action_signature","predicted_state","observed_state","top_state_probability","top_state_hit","state_observed_probability","state_log_loss","state_brier","predicted_success_probability","observed_success","success_brier","predicted_verified_probability","observed_verified","verified_brier","outcome_log_loss","duration_error","reward_error","value_error","total_error","surprise","confidence","uncertainty","evidence_count","created_at")
        out=[]
        for row in rows:
            item=dict(zip(keys,row))
            for key in ("top_state_probability","state_observed_probability","state_log_loss","state_brier","predicted_success_probability","success_brier","predicted_verified_probability","verified_brier","outcome_log_loss","duration_error","reward_error","total_error","surprise","confidence","uncertainty"):
                item[key]=float(item[key] or 0.0)
            for key in ("top_state_hit","observed_success","observed_verified","evidence_count"):
                item[key]=int(item[key] or 0)
            if item["value_error"] is not None:
                item["value_error"]=float(item["value_error"])
            out.append(item)
        return out

    def prediction_error_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row=conn.execute("SELECT COUNT(*),COALESCE(AVG(total_error),0),COALESCE(AVG(surprise),0),COALESCE(MAX(total_error),0) FROM prediction_errors").fetchone()
            high=conn.execute("SELECT COUNT(*) FROM prediction_errors WHERE total_error>=0.75").fetchone()[0]
            models=conn.execute("SELECT COUNT(*),COALESCE(AVG(prediction_error_mean),0),COALESCE(MAX(prediction_error_mean),0) FROM transition_models WHERE prediction_count>0").fetchone()
        finally:
            conn.close()
        return {
            "predictions": int(row[0] or 0), "mean_error": round(float(row[1] or 0),6),
            "mean_surprise": round(float(row[2] or 0),6), "max_error": round(float(row[3] or 0),6),
            "high_error_events": int(high or 0), "models_with_error_feedback": int(models[0] or 0),
            "mean_model_error": round(float(models[1] or 0),6), "max_model_error": round(float(models[2] or 0),6),
        }

    def prediction_calibration_records(self, *, limit: int = 5000) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows=conn.execute(
                "SELECT top_state_probability,top_state_hit,predicted_success_probability,observed_success,predicted_verified_probability,observed_verified FROM prediction_errors ORDER BY created_at DESC,id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        return [dict(top_state_probability=float(r[0]), top_state_hit=int(r[1]), predicted_success_probability=float(r[2]), observed_success=int(r[3]), predicted_verified_probability=float(r[4]), observed_verified=int(r[5])) for r in rows]

    def record_exploration_event(self, *, run_id: str | None, state_signature: str, action_signature: str,
                                 tool: str, action: dict, mode: str, score: float, goal_alignment: float,
                                 exploitation: float, ucb_bonus: float, information_gain: float, novelty: float,
                                 relearning_pressure: float, risk_penalty: float, evidence_count: int,
                                 uncertainty_before: float | None = None, selected: bool = True, executed: bool = False,
                                 created_at: str | None = None) -> int:
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO exploration_events(run_id,state_signature,action_signature,tool,action,mode,score,goal_alignment,exploitation,ucb_bonus,information_gain,novelty,relearning_pressure,risk_penalty,evidence_count,selected,executed,uncertainty_before,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, str(state_signature), str(action_signature), str(tool), _safe_json(action or {}), str(mode),
                     float(score), float(goal_alignment), float(exploitation), float(ucb_bonus), float(information_gain),
                     float(novelty), float(relearning_pressure), float(risk_penalty), int(evidence_count), int(bool(selected)),
                     int(bool(executed)), None if uncertainty_before is None else float(uncertainty_before), created_at or _now()),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def complete_exploration_event(self, event_id: int, *, executed: bool, ok: bool | None, verified: bool | None,
                                   reward: float | None = None, prediction_error: float | None = None,
                                   uncertainty_after: float | None = None, realized_information_gain: float | None = None,
                                   completed_at: str | None = None) -> bool:
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "UPDATE exploration_events SET executed=?,ok=?,verified=?,reward=?,prediction_error=?,uncertainty_after=?,realized_information_gain=?,completed_at=? WHERE id=?",
                    (int(bool(executed)), (None if ok is None else int(bool(ok))),
                     (None if verified is None else int(bool(verified))),
                     (None if reward is None else float(reward)),
                     (None if prediction_error is None else float(prediction_error)),
                     (None if uncertainty_after is None else float(uncertainty_after)),
                     (None if realized_information_gain is None else float(realized_information_gain)),
                     completed_at or _now(), int(event_id)),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def record_bandit_observation(self, *, state_signature: str, arm_signature: str, reward: float, source_event_id: int | None = None, observed_at: str | None = None) -> bool:
        conn=_connect(self.path)
        try:
            with conn:
                cur=conn.execute(
                    "INSERT OR IGNORE INTO bandit_observations(state_signature,arm_signature,reward,source_event_id,observed_at) VALUES(?,?,?,?,?)",
                    (str(state_signature),str(arm_signature),max(0.0,min(1.0,float(reward))),source_event_id,observed_at or _now()),
                )
                return cur.rowcount == 1
        finally:
            conn.close()

    def bandit_observations(self, state_signature: str, *, limit: int = 2000) -> list[dict]:
        conn=_connect(self.path)
        try:
            rows=conn.execute(
                "SELECT id,state_signature,arm_signature,reward,source_event_id,observed_at FROM bandit_observations WHERE state_signature=? ORDER BY id ASC LIMIT ?",
                (str(state_signature),max(1,int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [{"id":int(r[0]),"state_signature":r[1],"arm_signature":r[2],"reward":float(r[3]),"source_event_id":r[4],"observed_at":r[5]} for r in rows]

    def recent_exploration_events(self, *, limit: int = 100, run_id: str | None = None) -> list[dict]:
        conn = _connect(self.path)
        try:
            if run_id:
                rows = conn.execute(
                    "SELECT id,run_id,state_signature,action_signature,tool,action,mode,score,goal_alignment,exploitation,ucb_bonus,information_gain,novelty,relearning_pressure,risk_penalty,evidence_count,selected,executed,ok,verified,reward,prediction_error,uncertainty_before,uncertainty_after,realized_information_gain,created_at,completed_at FROM exploration_events WHERE run_id=? ORDER BY id DESC LIMIT ?",
                    (str(run_id), max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id,run_id,state_signature,action_signature,tool,action,mode,score,goal_alignment,exploitation,ucb_bonus,information_gain,novelty,relearning_pressure,risk_penalty,evidence_count,selected,executed,ok,verified,reward,prediction_error,uncertainty_before,uncertainty_after,realized_information_gain,created_at,completed_at FROM exploration_events ORDER BY id DESC LIMIT ?",
                    (max(1, int(limit)),),
                ).fetchall()
        finally:
            conn.close()
        keys=("id","run_id","state_signature","action_signature","tool","action","mode","score","goal_alignment","exploitation","ucb_bonus","information_gain","novelty","relearning_pressure","risk_penalty","evidence_count","selected","executed","ok","verified","reward","prediction_error","uncertainty_before","uncertainty_after","realized_information_gain","created_at","completed_at")
        out=[]
        for row in rows:
            item=dict(zip(keys,row))
            try: item["action"]=json.loads(item["action"] or "{}")
            except Exception: item["action"]={}
            for key in ("score","goal_alignment","exploitation","ucb_bonus","information_gain","novelty","relearning_pressure","risk_penalty"):
                item[key]=float(item[key] or 0.0)
            for key in ("evidence_count","selected","executed"):
                item[key]=int(item[key] or 0)
            for key in ("ok","verified"):
                item[key]=None if item[key] is None else bool(item[key])
            for key in ("reward","prediction_error","uncertainty_before","uncertainty_after","realized_information_gain"):
                item[key]=None if item[key] is None else float(item[key])
            out.append(item)
        return out

    def exploration_information_gain(self, tool: str, action_signature: str | None = None, *, limit: int = 64) -> float | None:
        """Return realized information gain learned from prior exploration outcomes."""
        conn = _connect(self.path)
        try:
            if action_signature:
                rows = conn.execute(
                    "SELECT realized_information_gain FROM exploration_events WHERE tool=? AND action_signature=? AND executed=1 AND realized_information_gain IS NOT NULL ORDER BY id DESC LIMIT ?",
                    (str(tool), str(action_signature), max(1, int(limit))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT realized_information_gain FROM exploration_events WHERE tool=? AND executed=1 AND realized_information_gain IS NOT NULL ORDER BY id DESC LIMIT ?",
                    (str(tool), max(1, int(limit))),
                ).fetchall()
        finally:
            conn.close()
        values = [float(row[0]) for row in rows if row and row[0] is not None]
        if not values and action_signature:
            conn = _connect(self.path)
            try:
                fallback = conn.execute(
                    "SELECT realized_information_gain FROM exploration_events WHERE tool=? AND executed=1 AND realized_information_gain IS NOT NULL ORDER BY id DESC LIMIT ?",
                    (str(tool), max(1, int(limit))),
                ).fetchall()
            finally:
                conn.close()
            values = [float(row[0]) for row in fallback if row and row[0] is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 6)

    def exploration_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT COUNT(*),SUM(selected),SUM(executed),SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END),SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END),COALESCE(AVG(information_gain),0),COALESCE(AVG(novelty),0),COALESCE(AVG(relearning_pressure),0),COALESCE(AVG(score),0),COALESCE(AVG(realized_information_gain),0) FROM exploration_events"
            ).fetchone()
            modes = conn.execute("SELECT mode,COUNT(*) FROM exploration_events GROUP BY mode").fetchall()
        finally:
            conn.close()
        return {
            "events": int(row[0] or 0),
            "selected": int(row[1] or 0),
            "executed": int(row[2] or 0),
            "successful": int(row[3] or 0),
            "verified": int(row[4] or 0),
            "mean_information_gain": round(float(row[5] or 0.0), 6),
            "mean_novelty": round(float(row[6] or 0.0), 6),
            "mean_relearning_pressure": round(float(row[7] or 0.0), 6),
            "mean_score": round(float(row[8] or 0.0), 6),
            "mean_realized_information_gain": round(float(row[9] or 0.0), 6),
            "modes": {str(k): int(v) for k,v in modes},
        }

    def transition_model_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute("SELECT COUNT(*),COALESCE(SUM(observation_count),0),COALESCE(SUM(prediction_count),0),COALESCE(AVG(prediction_error_mean),0) FROM transition_models").fetchone()
            return {"state_action_models": int(row[0] or 0), "observations": int(row[1] or 0),
                    "predictions": int(row[2] or 0), "mean_prediction_error": round(float(row[3] or 0.0),6)}
        finally:
            conn.close()

    def _update_return_stats(self, mean: float, m2: float, count: int, samples) -> tuple[float, float, int]:
        for sample in samples:
            count += 1
            value = float(sample)
            delta = value - mean
            mean += delta / count
            m2 += delta * (value - mean)
        return mean, m2, count

    def get_state_value(self, state_signature: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT state_signature,value,visits,return_mean,return_m2,first_seen_at,last_updated_at,model_version FROM state_values WHERE state_signature=?",
                (str(state_signature),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"state_signature": row[0], "value": float(row[1]), "visits": int(row[2]),
                "return_mean": float(row[3]), "return_m2": float(row[4]), "first_seen_at": row[5],
                "last_updated_at": row[6], "model_version": int(row[7])}

    def get_action_value(self, state_signature: str, action_signature: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT state_signature,action_signature,action,value,visits,return_mean,return_m2,first_seen_at,last_updated_at,model_version FROM action_values WHERE state_signature=? AND action_signature=?",
                (str(state_signature), str(action_signature)),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {"state_signature": row[0], "action_signature": row[1], "action": json.loads(row[2] or "{}"),
                "value": float(row[3]), "visits": int(row[4]), "return_mean": float(row[5]),
                "return_m2": float(row[6]), "first_seen_at": row[7], "last_updated_at": row[8],
                "model_version": int(row[9])}

    def list_action_values(self, state_signature: str, *, limit: int = 20) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT state_signature,action_signature,action,value,visits,return_mean,return_m2,first_seen_at,last_updated_at,model_version FROM action_values WHERE state_signature=? ORDER BY value DESC, visits DESC LIMIT ?",
                (str(state_signature), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [{"state_signature": r[0], "action_signature": r[1], "action": json.loads(r[2] or "{}"),
                 "value": float(r[3]), "visits": int(r[4]), "return_mean": float(r[5]),
                 "return_m2": float(r[6]), "first_seen_at": r[7], "last_updated_at": r[8],
                 "model_version": int(r[9])} for r in rows]

    def upsert_state_value(self, *, state_signature: str, value: float, visits_increment: int = 0,
                           return_samples=(), last_updated_at: str | None = None) -> None:
        if not state_signature:
            return
        now = last_updated_at or _now()
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT visits,return_mean,return_m2,first_seen_at FROM state_values WHERE state_signature=?",
                    (state_signature,),
                ).fetchone()
                if row is None:
                    visits, mean, m2, first_seen = 0, 0.0, 0.0, now
                else:
                    visits, mean, m2, first_seen = int(row[0]), float(row[1]), float(row[2]), row[3]
                mean, m2, sampled = self._update_return_stats(mean, m2, visits, return_samples)
                visits = max(sampled, visits + max(0, int(visits_increment)))
                conn.execute(
                    "INSERT INTO state_values(state_signature,value,visits,return_mean,return_m2,first_seen_at,last_updated_at,model_version) VALUES(?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(state_signature) DO UPDATE SET value=excluded.value,visits=excluded.visits,return_mean=excluded.return_mean,return_m2=excluded.return_m2,first_seen_at=excluded.first_seen_at,last_updated_at=excluded.last_updated_at,model_version=state_values.model_version+1",
                    (state_signature, float(value), visits, mean, m2, first_seen, now),
                )
        finally:
            conn.close()

    def upsert_action_value(self, *, state_signature: str, action_signature: str, action: dict, value: float,
                            visits_increment: int = 0, return_samples=(), last_updated_at: str | None = None) -> None:
        if not state_signature or not action_signature:
            return
        now = last_updated_at or _now()
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT visits,return_mean,return_m2,first_seen_at FROM action_values WHERE state_signature=? AND action_signature=?",
                    (state_signature, action_signature),
                ).fetchone()
                if row is None:
                    visits, mean, m2, first_seen = 0, 0.0, 0.0, now
                else:
                    visits, mean, m2, first_seen = int(row[0]), float(row[1]), float(row[2]), row[3]
                mean, m2, sampled = self._update_return_stats(mean, m2, visits, return_samples)
                visits = max(sampled, visits + max(0, int(visits_increment)))
                conn.execute(
                    "INSERT INTO action_values(state_signature,action_signature,action,value,visits,return_mean,return_m2,first_seen_at,last_updated_at,model_version) VALUES(?,?,?,?,?,?,?,?,?,1) "
                    "ON CONFLICT(state_signature,action_signature) DO UPDATE SET action=excluded.action,value=excluded.value,visits=excluded.visits,return_mean=excluded.return_mean,return_m2=excluded.return_m2,first_seen_at=excluded.first_seen_at,last_updated_at=excluded.last_updated_at,model_version=action_values.model_version+1",
                    (state_signature, action_signature, _safe_json(action), float(value), visits, mean, m2, first_seen, now),
                )
        finally:
            conn.close()

    def value_model_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            states, state_visits = conn.execute("SELECT COUNT(*),COALESCE(SUM(visits),0) FROM state_values").fetchone()
            actions, action_visits = conn.execute("SELECT COUNT(*),COALESCE(SUM(visits),0) FROM action_values").fetchone()
        finally:
            conn.close()
        return {"states": int(states or 0), "state_visits": int(state_visits or 0),
                "actions": int(actions or 0), "action_visits": int(action_visits or 0)}

    def index_replay_transitions(self, record: ExperienceRecord, *, now: str | None = None) -> int:
        from .replay import replay_priority_components
        """Index real transitions into the durable, bounded replay substrate.

        This method stores evidence only: no tools are executed and no policy/runtime authority
        changes occur. Priority combines historical replay signals plus model-version recency.
        """
        transitions = tuple(record.transitions or ())
        if not transitions:
            return 0
        timestamp = now or record.created_at or _now()
        conn = _connect(self.path)
        inserted = 0
        touched_contexts: set[tuple[str, str]] = set()
        try:
            with conn:
                for index, transition in enumerate(transitions):
                    if not isinstance(transition, dict):
                        continue
                    action = transition.get("action") or {}
                    state_signature = str(transition.get("state_before") or "")
                    action_signature_value = _json_fingerprint(action)
                    outcome_signature = _json_fingerprint({
                        "state_after": transition.get("state_after"),
                        "outcome": transition.get("outcome"),
                        "verified": transition.get("verified"),
                    })
                    prior_count = int(conn.execute(
                        "SELECT COUNT(*) FROM replay_items WHERE state_signature=? AND action_signature=?",
                        (state_signature, action_signature_value),
                    ).fetchone()[0])
                    existing_context = int(conn.execute(
                        "SELECT COUNT(*) FROM replay_items WHERE state_signature=? AND action_signature=? AND outcome_signature<>?",
                        (state_signature, action_signature_value, outcome_signature),
                    ).fetchone()[0]) > 0
                    metadata = transition.get("metadata") or ()
                    try:
                        metadata_map = dict(metadata) if isinstance(metadata, (list, tuple)) else (metadata if isinstance(metadata, dict) else {})
                    except Exception:
                        metadata_map = {}
                    model_version = max(1, int(transition.get("model_version") or metadata_map.get("world_model_version") or 1))
                    current = conn.execute(
                        "SELECT model_version FROM transition_models WHERE state_signature=? AND action_signature=?",
                        (state_signature, canonical_action_signature(action)),
                    ).fetchone()
                    current_model_version = int(current[0]) if current and current[0] is not None else model_version
                    recency = _clamp_replay_recency(current_model_version, model_version)
                    components = replay_priority_components(
                        transition, occurrence_count=prior_count, contradictory=existing_context,
                        boundary=(index == 0 or index == len(transitions) - 1),
                        model_change_recency=recency,
                    )
                    item_id = str(transition.get("transition_id") or _json_fingerprint({
                        "episode": record.run_id, "index": index, "transition": transition
                    }))
                    touched_contexts.add((state_signature, action_signature_value))
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO replay_items(transition_id,episode_id,transition_index,transition,state_signature,action_signature,outcome_signature,priority,prediction_error,novelty,failure_importance,uncertainty,learning_value,boundary,contradictory,replay_count,created_at,model_version,model_change_recency) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (item_id, record.run_id, index, _safe_json(transition), state_signature, action_signature_value, outcome_signature,
                         components["priority"], components["prediction_error"], components["novelty"],
                         components["failure_importance"], components["uncertainty"], components["learning_value"],
                         components["boundary"], components["contradictory"], 0, timestamp, model_version, recency),
                    )
                    inserted += int(cur.rowcount == 1)

                # Recompute context-wide rarity and contradiction so older observations do not
                # remain falsely marked as novel forever after repeated evidence.
                for state_signature, action_signature_value in touched_contexts:
                    count = int(conn.execute(
                        "SELECT COUNT(*) FROM replay_items WHERE state_signature=? AND action_signature=?",
                        (state_signature, action_signature_value),
                    ).fetchone()[0])
                    outcome_kinds = int(conn.execute(
                        "SELECT COUNT(DISTINCT outcome_signature) FROM replay_items WHERE state_signature=? AND action_signature=?",
                        (state_signature, action_signature_value),
                    ).fetchone()[0])
                    contradictory = outcome_kinds > 1
                    rows = conn.execute(
                        "SELECT transition_id,transition,boundary,model_version FROM replay_items WHERE state_signature=? AND action_signature=?",
                        (state_signature, action_signature_value),
                    ).fetchall()
                    representative = json.loads(rows[0][1] or "{}") if rows else {}
                    current = conn.execute(
                        "SELECT model_version FROM transition_models WHERE state_signature=? AND action_signature=?",
                        (state_signature, canonical_action_signature(representative.get("action") or {})),
                    ).fetchone()
                    current_model_version = int(current[0]) if current and current[0] is not None else 1
                    for transition_id, transition_json, boundary, item_model_version in rows:
                        transition = json.loads(transition_json or "{}")
                        recency = _clamp_replay_recency(current_model_version, int(item_model_version or 1))
                        components = replay_priority_components(
                            transition, occurrence_count=max(0, count - 1), contradictory=contradictory,
                            boundary=bool(boundary), model_change_recency=recency,
                        )
                        conn.execute(
                            "UPDATE replay_items SET priority=?,prediction_error=?,novelty=?,failure_importance=?,uncertainty=?,learning_value=?,contradictory=?,model_change_recency=? WHERE transition_id=?",
                            (components["priority"], components["prediction_error"], components["novelty"],
                             components["failure_importance"], components["uncertainty"], components["learning_value"],
                             components["contradictory"], components["model_change_recency"], transition_id),
                        )
        finally:
            conn.close()
        return inserted

    def replay_items(self, *, limit: int = 100, min_priority: float = 0.0) -> list[ReplayItem]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT transition_id,episode_id,transition_index,transition,priority,prediction_error,novelty,failure_importance,uncertainty,learning_value,boundary,contradictory,replay_count,created_at,model_version,model_change_recency FROM replay_items WHERE priority>=? ORDER BY priority DESC, created_at DESC, id DESC LIMIT ?",
                (float(min_priority), max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [ReplayItem(r[0], r[1], int(r[2]), json.loads(r[3] or "{}"), float(r[4]), float(r[5]),
                           float(r[6]), float(r[7]), float(r[8]), float(r[9]), float(r[10]), float(r[11]),
                           int(r[12]), r[13], int(r[14] or 1), float(r[15] or 0.0)) for r in rows]

    def mark_replayed(self, transition_ids: list[str], *, timestamp: str | None = None) -> None:
        if not transition_ids:
            return
        conn = _connect(self.path)
        try:
            with conn:
                conn.executemany(
                    "UPDATE replay_items SET replay_count=replay_count+1,last_replayed_at=? WHERE transition_id=?",
                    [(timestamp or _now(), item_id) for item_id in transition_ids],
                )
        finally:
            conn.close()

    def update_replay_priorities(self, updates: list[dict]) -> int:
        from .replay import replay_priority_components
        if not updates:
            return 0
        conn = _connect(self.path)
        changed = 0
        try:
            with conn:
                for update in updates:
                    item_id = str(update.get("transition_id") or "")
                    if not item_id:
                        continue
                    row = conn.execute(
                        "SELECT transition,state_signature,action_signature,boundary,model_version FROM replay_items WHERE transition_id=?",
                        (item_id,),
                    ).fetchone()
                    if row is None:
                        continue
                    transition = update.get("transition") if isinstance(update.get("transition"), dict) else json.loads(row[0] or "{}")
                    state_signature = str(row[1] or "")
                    action_signature_value = str(row[2] or "")
                    if "occurrence_count" in update:
                        occurrence_count = max(0, int(update.get("occurrence_count", 0) or 0))
                    else:
                        total = int(conn.execute(
                            "SELECT COUNT(*) FROM replay_items WHERE state_signature=? AND action_signature=?",
                            (state_signature, action_signature_value),
                        ).fetchone()[0])
                        occurrence_count = max(0, total - 1)
                    if "contradictory" in update:
                        contradictory = bool(update.get("contradictory"))
                    else:
                        contradictory = int(conn.execute(
                            "SELECT COUNT(DISTINCT outcome_signature) FROM replay_items WHERE state_signature=? AND action_signature=?",
                            (state_signature, action_signature_value),
                        ).fetchone()[0]) > 1
                    current = conn.execute(
                        "SELECT model_version FROM transition_models WHERE state_signature=? AND action_signature=?",
                        (state_signature, canonical_action_signature(transition.get("action") or {})),
                    ).fetchone()
                    current_model_version = int(current[0]) if current and current[0] is not None else int(row[4] or 1)
                    item_model_version = max(1, int(update.get("model_version") or row[4] or 1))
                    recency = _clamp_replay_recency(current_model_version, item_model_version)
                    components = replay_priority_components(
                        transition, occurrence_count=occurrence_count, contradictory=contradictory,
                        boundary=bool(update.get("boundary", bool(row[3]))), model_change_recency=recency,
                    )
                    conn.execute(
                        "UPDATE replay_items SET priority=?,prediction_error=?,novelty=?,failure_importance=?,uncertainty=?,learning_value=?,boundary=?,contradictory=?,model_change_recency=? WHERE transition_id=?",
                        (components["priority"], components["prediction_error"], components["novelty"],
                         components["failure_importance"], components["uncertainty"], components["learning_value"],
                         components["boundary"], components["contradictory"], components["model_change_recency"], item_id),
                    )
                    changed += 1
        finally:
            conn.close()
        return changed

    def prune_replay(self, capacity: int) -> int:
        capacity = max(1, int(capacity))
        conn = _connect(self.path)
        try:
            with conn:
                count = int(conn.execute("SELECT COUNT(*) FROM replay_items").fetchone()[0])
                excess = count - capacity
                if excess <= 0:
                    return 0
                conn.execute(
                    "DELETE FROM replay_items WHERE id IN (SELECT id FROM replay_items ORDER BY priority ASC, created_at ASC, id ASC LIMIT ?)",
                    (excess,),
                )
                return excess
        finally:
            conn.close()

    def record_replay_update(self, *, batch_id: str, transition_id: str, episode_id: str,
                             sampling_probability: float, importance_weight: float,
                             learning_rate_scale: float, td_signal: float,
                             state_value_delta: float = 0.0, action_value_delta: float = 0.0,
                             status: str = "completed", error: str = "", created_at: str | None = None) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO replay_updates(batch_id,transition_id,episode_id,sampling_probability,importance_weight,learning_rate_scale,td_signal,state_value_delta,action_value_delta,status,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(batch_id), str(transition_id), str(episode_id), float(sampling_probability),
                     float(importance_weight), float(learning_rate_scale), float(td_signal),
                     float(state_value_delta), float(action_value_delta), str(status), str(error or ""), created_at or _now()),
                )
        finally:
            conn.close()

    def replay_update_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            batches, updates, completed, td_mean = conn.execute(
                "SELECT COUNT(DISTINCT batch_id),COUNT(*),SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),COALESCE(AVG(td_signal),0) FROM replay_updates"
            ).fetchone()
        finally:
            conn.close()
        return {
            "batches": int(batches or 0),
            "updates": int(updates or 0),
            "completed": int(completed or 0),
            "mean_td_signal": round(float(td_mean or 0.0), 6),
        }

    def replay_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT COUNT(*),COALESCE(MAX(priority),0),COALESCE(AVG(priority),0),COALESCE(SUM(replay_count),0) FROM replay_items"
            ).fetchone()
            episodes = conn.execute("SELECT COUNT(DISTINCT episode_id) FROM replay_items").fetchone()[0]
        finally:
            conn.close()
        update_stats = self.replay_update_stats()
        return {"transitions": int(row[0] or 0), "episodes": int(episodes or 0),
                "max_priority": round(float(row[1] or 0), 6), "mean_priority": round(float(row[2] or 0), 6),
                "replays": int(row[3] or 0), **update_stats}

    def upsert_lesson(self, lesson: Lesson) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                existing = conn.execute("SELECT evidence_run_ids,confidence,uses FROM lessons WHERE key=?", (lesson.key,)).fetchone()
                evidence = list(lesson.evidence_run_ids)
                confidence = lesson.confidence
                uses = lesson.uses
                if existing:
                    old_evidence = json.loads(existing[0] or "[]")
                    evidence = list(dict.fromkeys(old_evidence + evidence))[-20:]
                    confidence = max(float(existing[1]), confidence)
                    uses = int(existing[2])
                conn.execute(
                    "INSERT OR REPLACE INTO lessons(key,task_signature,kind,lesson,when_to_apply,avoid,evidence_run_ids,confidence,status,uses,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (lesson.key, lesson.task_signature, lesson.kind, lesson.lesson, _safe_json(lesson.when_to_apply),
                     _safe_json(lesson.avoid), _safe_json(evidence), confidence, lesson.status, uses, lesson.created_at or _now()),
                )
        finally:
            conn.close()

    def search_lessons(self, task_signature: str, tokens: set[str], limit: int = 8) -> list[Lesson]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT key,task_signature,kind,lesson,when_to_apply,avoid,evidence_run_ids,confidence,status,uses,created_at FROM lessons WHERE status='active' ORDER BY confidence DESC,uses DESC,created_at DESC LIMIT ?",
                (max(limit * 3, 12),),
            ).fetchall()
        finally:
            conn.close()
        out=[]
        for r in rows:
            l=Lesson(r[0],r[1],r[2],r[3],tuple(json.loads(r[4] or "[]")),tuple(json.loads(r[5] or "[]")),
                     tuple(json.loads(r[6] or "[]")),float(r[7]),r[8],int(r[9]),r[10])
            overlap=len(tokens & set(l.task_signature.split())) if tokens else 0
            if l.task_signature == task_signature or overlap > 0:
                out.append((1 if l.task_signature == task_signature else 0, overlap, l))
        out.sort(key=lambda x:(-x[0],-x[1],-x[2].confidence,-x[2].uses,x[2].key))
        return [x[2] for x in out[:limit]]

    def touch_lessons(self, keys: list[str]) -> None:
        if not keys:
            return
        conn = _connect(self.path)
        try:
            with conn:
                conn.executemany("UPDATE lessons SET uses=uses+1 WHERE key=?", [(k,) for k in keys])
        finally:
            conn.close()

    def active_lessons(self, limit: int = 500) -> list[Lesson]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT key,task_signature,kind,lesson,when_to_apply,avoid,evidence_run_ids,confidence,status,uses,created_at FROM lessons WHERE status='active' ORDER BY created_at DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        finally:
            conn.close()
        return [Lesson(r[0], r[1], r[2], r[3], tuple(json.loads(r[4] or "[]")),
                       tuple(json.loads(r[5] or "[]")), tuple(json.loads(r[6] or "[]")),
                       float(r[7]), r[8], int(r[9]), r[10]) for r in rows]

    def set_lesson_status(self, key: str, status: str) -> None:
        if status not in {"active", "retired"}:
            raise ValueError("invalid lesson status")
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute("UPDATE lessons SET status=? WHERE key=?", (status, key))
        finally:
            conn.close()

    def record_evaluation(self, evaluation: SkillEvaluation) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO skill_evaluations(candidate_key,goal,baseline_reward,candidate_reward,delta,verified,regression,replay_kind,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (evaluation.candidate_key,evaluation.goal,evaluation.baseline_reward,evaluation.candidate_reward,
                     evaluation.delta,int(evaluation.verified),int(evaluation.regression),evaluation.replay_kind,evaluation.created_at or _now()),
                )
        finally:
            conn.close()

    def evaluations(self, candidate_key: str, limit: int = 50) -> list[SkillEvaluation]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT candidate_key,goal,baseline_reward,candidate_reward,delta,verified,regression,replay_kind,created_at FROM skill_evaluations WHERE candidate_key=? ORDER BY id DESC LIMIT ?",
                (candidate_key,limit),
            ).fetchall()
        finally:
            conn.close()
        return [SkillEvaluation(r[0],r[1],float(r[2]),float(r[3]),float(r[4]),bool(r[5]),bool(r[6]),r[7],r[8]) for r in rows]

    def record_learning_metrics(self, metrics: dict, *, run_id: str = '', created_at: str | None = None) -> int:
        """Persist one evaluation snapshot without mixing it into cognitive evidence."""
        if not isinstance(metrics, dict):
            raise ValueError("metrics must be an object")
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO learning_metric_snapshots(run_id,metrics,created_at) VALUES(?,?,?)",
                    (str(run_id or ''), _safe_json(metrics), created_at or _now()),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()

    def latest_learning_metrics(self, *, limit: int = 20) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT id,run_id,metrics,created_at FROM learning_metric_snapshots ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        out = []
        for row in rows:
            try:
                metrics = json.loads(row[2] or '{}')
            except Exception:
                metrics = {}
            out.append({"id": int(row[0]), "run_id": row[1], "metrics": metrics, "created_at": row[3]})
        return out

    def create_company_change_proposal(self, *, proposal_id: str, company_id: str, change_kind: str,
                                       target_key: str = "", payload: dict | None = None,
                                       evidence: list | None = None, regression: dict | None = None) -> dict:
        now = _now()
        row = {
            "proposal_id": str(proposal_id), "company_id": str(company_id), "change_kind": str(change_kind),
            "target_key": str(target_key or ""), "payload": dict(payload or {}),
            "evidence": list(evidence or []), "regression": dict(regression or {}),
            "security_review": {}, "executive_approval": {}, "status": "proposed",
            "created_at": now, "updated_at": now,
        }
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO company_change_proposals(proposal_id,company_id,change_kind,target_key,payload,evidence,regression,security_review,executive_approval,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (row["proposal_id"], row["company_id"], row["change_kind"], row["target_key"],
                     _safe_json(row["payload"]), _safe_json(row["evidence"]), _safe_json(row["regression"]),
                     _safe_json(row["security_review"]), _safe_json(row["executive_approval"]), row["status"], now, now),
                )
        finally:
            conn.close()
        return row

    def get_company_change_proposal(self, proposal_id: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT proposal_id,company_id,change_kind,target_key,payload,evidence,regression,security_review,executive_approval,status,created_at,updated_at FROM company_change_proposals WHERE proposal_id=?",
                (str(proposal_id),),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {
            "proposal_id": row[0], "company_id": row[1], "change_kind": row[2], "target_key": row[3],
            "payload": json.loads(row[4] or "{}"), "evidence": json.loads(row[5] or "[]"),
            "regression": json.loads(row[6] or "{}"), "security_review": json.loads(row[7] or "{}"),
            "executive_approval": json.loads(row[8] or "{}"), "status": row[9],
            "created_at": row[10], "updated_at": row[11],
        }

    def list_company_change_proposals(self, company_id: str, *, limit: int = 100, status: str | None = None) -> list[dict]:
        conn = _connect(self.path)
        try:
            sql = "SELECT proposal_id,company_id,change_kind,target_key,payload,evidence,regression,security_review,executive_approval,status,created_at,updated_at FROM company_change_proposals WHERE company_id=?"
            params: list = [str(company_id)]
            if status:
                sql += " AND status=?"
                params.append(str(status))
            sql += " ORDER BY updated_at DESC, proposal_id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()
        return [
            {
                "proposal_id": r[0], "company_id": r[1], "change_kind": r[2], "target_key": r[3],
                "payload": json.loads(r[4] or "{}"), "evidence": json.loads(r[5] or "[]"),
                "regression": json.loads(r[6] or "{}"), "security_review": json.loads(r[7] or "{}"),
                "executive_approval": json.loads(r[8] or "{}"), "status": r[9],
                "created_at": r[10], "updated_at": r[11],
            } for r in rows
        ]

    def update_company_change_proposal(self, proposal_id: str, *, status: str | None = None,
                                       regression: dict | None = None, security_review: dict | None = None,
                                       executive_approval: dict | None = None) -> dict | None:
        current = self.get_company_change_proposal(proposal_id)
        if current is None:
            return None
        next_status = str(status or current["status"])
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "UPDATE company_change_proposals SET status=?, regression=?, security_review=?, executive_approval=?, updated_at=? WHERE proposal_id=?",
                    (next_status, _safe_json(regression if regression is not None else current["regression"]),
                     _safe_json(security_review if security_review is not None else current["security_review"]),
                     _safe_json(executive_approval if executive_approval is not None else current["executive_approval"]),
                     _now(), str(proposal_id)),
                )
        finally:
            conn.close()
        return self.get_company_change_proposal(proposal_id)

    def recent_evolution_events(self, *, limit: int = 100, candidate_key: str | None = None) -> list[dict]:
        conn = _connect(self.path)
        try:
            sql = "SELECT candidate_key,action,reason,payload,created_at FROM evolution_events"
            params: list = []
            if candidate_key is not None:
                sql += " WHERE candidate_key=?"
                params.append(str(candidate_key))
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(max(1, int(limit)))
            rows = conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()
        out = []
        for row in rows:
            try:
                payload = json.loads(row[3] or '{}')
            except Exception:
                payload = {}
            out.append({"candidate_key": row[0], "action": row[1], "reason": row[2], "payload": payload, "created_at": row[4]})
        return out

    def record_event(self, candidate_key: str, action: str, reason: str, payload: dict | None = None) -> None:
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute("INSERT INTO evolution_events(candidate_key,action,reason,payload,created_at) VALUES(?,?,?,?,?)",
                             (candidate_key, action, reason, _safe_json(payload or {}), _now()))
        finally:
            conn.close()

    @staticmethod
    def _transition_metadata(transition: dict) -> dict[str, object]:
        metadata = transition.get("metadata") or ()
        if isinstance(metadata, dict):
            return dict(metadata)
        try:
            return dict(metadata) if isinstance(metadata, (tuple, list)) else {}
        except Exception:
            return {}

    def upsert_self_model_observations(self, record: ExperienceRecord, *, now: str | None = None) -> dict:
        """Persist immutable execution evidence and update self-model aggregates atomically."""
        transitions = tuple(record.transitions or ())
        if not transitions:
            return {"inserted": 0, "duplicates": 0, "metrics": 0}
        timestamp = now or record.created_at or _now()
        prior_failure = False
        rows: list[dict] = []
        for transition in transitions:
            if not isinstance(transition, dict):
                continue
            outcome = transition.get("outcome") or {}
            if not isinstance(outcome, dict):
                outcome = {}
            action = transition.get("action") or {}
            metadata = self._transition_metadata(transition)
            capability = str(action.get("capability") or "")
            tool = str(action.get("tool") or "")
            if not tool:
                continue
            context = str(metadata.get("context_signature") or record.task_signature or record.operation or "")
            verified = bool(transition.get("verified", outcome.get("verified", False)))
            ok = bool(outcome.get("ok", verified))
            failure = not ok or not verified
            raw_confidence = metadata.get("prediction_confidence_before", metadata.get("confidence_before"))
            confidence_available = raw_confidence is not None
            confidence = max(0.0, min(1.0, float(raw_confidence))) if confidence_available else 0.0
            observed = 1.0 if ok and verified else 0.0
            calibration_error = abs(confidence - observed) if confidence_available else 0.0
            brier_error = (confidence - observed) ** 2 if confidence_available else 0.0
            error = max(0.0, min(1.0, float(transition.get("prediction_error") or metadata.get("prediction_error_total") or 0.0)))
            cost = float(outcome.get("duration_ms") or 0.0) / 1000.0
            if cost <= 0.0:
                cost = max(0.0, float(action.get("cost") or 0.0))
            recovery_attempt = prior_failure
            recovery_success = bool(recovery_attempt and ok and verified)
            rows.append({
                "transition_id": str(transition.get("transition_id") or ""),
                "run_id": str(record.run_id), "capability": capability or tool, "tool": tool,
                "context_signature": context, "success": int(ok), "verified": int(verified),
                "failure": int(failure), "reward": float(transition.get("reward") or 0.0),
                "prediction_error": error, "confidence_before": confidence,
                "confidence_after": max(0.0, min(1.0, float(metadata.get("confidence_after", confidence) or confidence))),
                "confidence_available": int(confidence_available),
                "calibration_error": calibration_error, "brier_error": brier_error,
                "observed_cost": cost, "recovered": int(recovery_attempt),
                "recovery_success": int(recovery_success),
                "world_model_version": max(1, int(metadata.get("world_model_version") or transition.get("model_version") or 1)),
                "policy_version": max(1, int(metadata.get("policy_version") or 1)),
                "procedure_version": max(1, int(metadata.get("procedure_version") or 1)),
                "created_at": str(transition.get("timestamp") or timestamp or _now()),
            })
            if failure:
                prior_failure = True
        if not rows:
            return {"inserted": 0, "duplicates": 0, "metrics": 0}
        conn = _connect(self.path)
        inserted = duplicates = metrics = 0
        try:
            with conn:
                for row in rows:
                    if not row["transition_id"]:
                        continue
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO self_model_observations(transition_id,run_id,capability,tool,context_signature,success,verified,failure,reward,prediction_error,confidence_before,confidence_after,confidence_available,calibration_error,brier_error,observed_cost,recovered,recovery_success,world_model_version,policy_version,procedure_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (row["transition_id"], row["run_id"], row["capability"], row["tool"], row["context_signature"],
                         row["success"], row["verified"], row["failure"], row["reward"], row["prediction_error"],
                         row["confidence_before"], row["confidence_after"], row["confidence_available"], row["calibration_error"], row["brier_error"],
                         row["observed_cost"], row["recovered"], row["recovery_success"], row["world_model_version"],
                         row["policy_version"], row["procedure_version"], row["created_at"]),
                    )
                    if cur.rowcount != 1:
                        duplicates += 1
                        continue
                    inserted += 1
                    conn.execute(
                        "INSERT INTO self_model_metrics(capability,tool,context_signature,attempts,successes,verified,failures,reward_sum,prediction_error_sum,confidence_sum,confidence_count,calibration_error_sum,calibration_count,brier_error_sum,brier_count,cost_sum,recovery_attempts,recovery_successes,last_updated_at,model_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1) "
                        "ON CONFLICT(capability,tool,context_signature) DO UPDATE SET attempts=self_model_metrics.attempts+excluded.attempts,successes=self_model_metrics.successes+excluded.successes,verified=self_model_metrics.verified+excluded.verified,failures=self_model_metrics.failures+excluded.failures,reward_sum=self_model_metrics.reward_sum+excluded.reward_sum,prediction_error_sum=self_model_metrics.prediction_error_sum+excluded.prediction_error_sum,confidence_sum=self_model_metrics.confidence_sum+excluded.confidence_sum,confidence_count=self_model_metrics.confidence_count+excluded.confidence_count,calibration_error_sum=self_model_metrics.calibration_error_sum+excluded.calibration_error_sum,calibration_count=self_model_metrics.calibration_count+excluded.calibration_count,brier_error_sum=self_model_metrics.brier_error_sum+excluded.brier_error_sum,brier_count=self_model_metrics.brier_count+excluded.brier_count,cost_sum=self_model_metrics.cost_sum+excluded.cost_sum,recovery_attempts=self_model_metrics.recovery_attempts+excluded.recovery_attempts,recovery_successes=self_model_metrics.recovery_successes+excluded.recovery_successes,last_updated_at=excluded.last_updated_at,model_version=self_model_metrics.model_version+1",
                        (row["capability"], row["tool"], row["context_signature"], 1, row["success"], row["verified"], row["failure"],
                         row["reward"], row["prediction_error"], row["confidence_before"] if row["confidence_available"] else 0.0,
                         row["confidence_available"], row["calibration_error"] if row["confidence_available"] else 0.0,
                         row["confidence_available"], row["brier_error"] if row["confidence_available"] else 0.0,
                         row["confidence_available"], row["observed_cost"], row["recovered"], row["recovery_success"], row["created_at"]),
                    )
                    metrics += 1
        finally:
            conn.close()
        return {"inserted": inserted, "duplicates": duplicates, "metrics": metrics}

    def self_model_metrics(self, *, capability: str | None = None, tool: str | None = None,
                           context_signature: str | None = None, limit: int = 200) -> list[dict]:
        conn = _connect(self.path)
        try:
            clauses = []
            args: list[object] = []
            if capability:
                clauses.append("capability=?"); args.append(str(capability))
            if tool:
                clauses.append("tool=?"); args.append(str(tool))
            if context_signature is not None:
                clauses.append("context_signature=?"); args.append(str(context_signature))
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                "SELECT capability,tool,context_signature,attempts,successes,verified,failures,reward_sum,prediction_error_sum,confidence_sum,confidence_count,calibration_error_sum,calibration_count,brier_error_sum,brier_count,cost_sum,recovery_attempts,recovery_successes,last_updated_at,model_version FROM self_model_metrics" + where + " ORDER BY attempts DESC,last_updated_at DESC LIMIT ?",
                (*args, max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        result=[]
        for r in rows:
            attempts=max(1,int(r[3] or 0))
            result.append({
                "capability":r[0], "tool":r[1], "context_signature":r[2], "attempts":int(r[3] or 0),
                "successes":int(r[4] or 0), "verified":int(r[5] or 0), "failures":int(r[6] or 0),
                "reward_mean":float(r[7] or 0.0)/attempts, "prediction_error_mean":float(r[8] or 0.0)/attempts,
                "confidence_mean":float(r[9] or 0.0)/max(1,int(r[10] or 0)), "confidence_count":int(r[10] or 0),
                "calibration_error":float(r[11] or 0.0)/max(1,int(r[12] or 0)), "calibration_count":int(r[12] or 0),
                "brier_error":float(r[13] or 0.0)/max(1,int(r[14] or 0)), "brier_count":int(r[14] or 0),
                "average_cost":float(r[15] or 0.0)/attempts,
                "recovery_attempts":int(r[16] or 0), "recovery_successes":int(r[17] or 0),
                "recovery_rate":int(r[17] or 0)/max(1,int(r[16] or 0)),
                "reliability":int(r[5] or 0)/attempts, "last_updated_at":r[18], "model_version":int(r[19] or 1),
            })
        return result

    def self_model_action_assessment(self, *, tool: str, capability: str = '', context_signature: str = '') -> dict:
        """Return a conservative, evidence-weighted self-assessment for action selection."""
        rows=self.self_model_metrics(tool=tool, context_signature=context_signature, limit=1) if context_signature else []
        scope="context"
        if not rows:
            # Broaden to the tool/capability family when the exact task context has no evidence.
            family=self.self_model_metrics(tool=tool, capability=capability, limit=100)
            scope="capability"
            if family:
                total=max(1,sum(int(x.get("attempts") or 0) for x in family))
                def wmean(key: str) -> float:
                    return sum(float(x.get(key,0.0) or 0.0)*int(x.get("attempts") or 0) for x in family)/total
                attempts=sum(int(x.get("attempts") or 0) for x in family)
                successes=sum(int(x.get("successes") or 0) for x in family)
                verified=sum(int(x.get("verified") or 0) for x in family)
                failures=sum(int(x.get("failures") or 0) for x in family)
                recovery_attempts=sum(int(x.get("recovery_attempts") or 0) for x in family)
                recovery_successes=sum(int(x.get("recovery_successes") or 0) for x in family)
                rows=[dict(family[0], attempts=attempts, successes=successes, verified=verified, failures=failures,
                           reward_mean=wmean("reward_mean"), prediction_error_mean=wmean("prediction_error_mean"),
                           confidence_mean=wmean("confidence_mean"), calibration_error=wmean("calibration_error"),
                           brier_error=wmean("brier_error"), average_cost=wmean("average_cost"),
                           recovery_attempts=recovery_attempts, recovery_successes=recovery_successes,
                           recovery_rate=recovery_successes/max(1,recovery_attempts))]
        if not rows:
            return {"tool":str(tool),"capability":str(capability or tool),"scope":"prior","attempts":0,
                    "reliability":0.70,"confidence":0.45,"calibration_quality":0.50,"prediction_error":0.50,
                    "average_cost":0.0,"recovery_rate":0.50,"adjustment":0.0,"uncertain":True}
        item=rows[0]
        attempts=int(item["attempts"] or 0)
        posterior=(float(item["successes"])+2.8)/(attempts+4.0)
        calibration_quality=0.75 if int(item.get("calibration_count", 0) or 0) == 0 else 1.0-max(0.0,min(1.0,float(item["calibration_error"])))
        confidence=max(0.0,min(1.0,0.65*posterior+0.35*calibration_quality))
        evidence_weight=min(1.0,attempts/5.0)
        recovery=float(item["recovery_rate"])
        prediction_penalty=max(0.0,min(1.0,float(item["prediction_error_mean"])))
        adjustment=evidence_weight*(0.85*(confidence-0.65)+0.12*(recovery-0.50)-0.20*prediction_penalty)
        if attempts>=3 and float(item["reliability"])<0.5:
            adjustment-=0.35*evidence_weight
        adjustment=max(-0.80,min(0.40,adjustment))
        return {**item,"scope":scope,"posterior_reliability":posterior,"confidence":confidence,
                "calibration_quality":calibration_quality,"prediction_error":prediction_penalty,
                "adjustment":adjustment,"uncertain":attempts<3 or confidence<0.55}

    def self_model_snapshot(self, *, limit: int = 200) -> dict:
        metrics=self.self_model_metrics(limit=limit)
        reliability=[]
        for item in metrics:
            assessment=self.self_model_action_assessment(tool=item["tool"],capability=item["capability"],context_signature=item["context_signature"])
            reliability.append({
                "capability":item["capability"],"tool":item["tool"],"context_signature":item["context_signature"],
                "attempts":item["attempts"],"successes":item["successes"],"verified":item["verified"],"failures":item["failures"],
                "reliability":round(item["reliability"],6),"posterior_reliability":round(float(assessment.get("posterior_reliability",0.0)),6),
                "confidence":round(float(assessment.get("confidence",0.0)),6),"calibration_error":round(item["calibration_error"],6),
                "prediction_error":round(item["prediction_error_mean"],6),"average_cost":round(item["average_cost"],6),
                "recovery_rate":round(item["recovery_rate"],6),"model_version":item["model_version"],"last_updated_at":item["last_updated_at"],
            })
        limits=[]
        for item in reliability:
            if item["attempts"]>=3 and item["reliability"]<0.5:
                limits.append({"tool":item["tool"],"capability":item["capability"],"reason":"low verified reliability from observed runtime history"})
            elif item["attempts"]>=3 and item["calibration_error"]>0.35:
                limits.append({"tool":item["tool"],"capability":item["capability"],"reason":"poor confidence calibration from observed outcomes"})
        reliability.sort(key=lambda x:(-x["confidence"],-x["attempts"],x["tool"],x["context_signature"]))
        return {"version":2,"metrics_count":len(metrics),"reliability":reliability[:limit],"limits":limits[:limit],
                "observed_tools":sorted({x["tool"] for x in metrics}),"context_metrics":len([x for x in metrics if x["context_signature"]])}

    def record_language_pattern_observation(self, *, pattern_key: str, mapping_fingerprint: str, pattern: str, operation: str,
                                             capability: str = '', goal_payload: dict | None = None,
                                             confidence: float = 0.0, success: bool = False, verified: bool = False,
                                             source: str = '', run_id: str = '', now: str | None = None,
                                             promotion_threshold: int = 3) -> dict:
        """Persist one verified language→GoalSpec evidence point without trusting it automatically."""
        key = str(pattern_key or '').strip()
        fingerprint = str(mapping_fingerprint or '').strip()
        op = str(operation or '').strip()
        if not key or not fingerprint or not op:
            return {"inserted": False, "promoted": False, "status": "rejected", "reason": "missing-pattern-or-operation"}
        timestamp = now or _now()
        conf = max(0.0, min(1.0, float(confidence or 0.0)))
        ok = bool(success and verified)
        threshold = max(2, int(promotion_threshold or 3))
        payload = _safe_json(goal_payload or {})
        conn = _connect(self.path)
        try:
            with conn:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO language_pattern_observations(pattern_key,mapping_fingerprint,pattern,operation,capability,goal_payload,confidence,verified,success,source,run_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (key, fingerprint, str(pattern)[:1000], op[:120], str(capability or '')[:120], payload[:12000], conf, int(verified), int(success), str(source or '')[:80], str(run_id or '')[:120], timestamp),
                )
                if cur.rowcount != 1:
                    row = conn.execute(
                        "SELECT status,attempts,successes,failures FROM language_pattern_mappings WHERE pattern_key=? AND mapping_fingerprint=?",
                        (key, fingerprint),
                    ).fetchone()
                    return {"inserted": False, "promoted": bool(row and row[0] == 'promoted'), "status": row[0] if row else 'candidate',
                            "attempts": int(row[1] or 0) if row else 0, "successes": int(row[2] or 0) if row else 0,
                            "failures": int(row[3] or 0) if row else 0}
                # A single language mapping is allowed to compete with other mappings for the same pattern.
                # The winning mapping is promoted only after repeated verified success and no failures.
                conn.execute(
                    "INSERT INTO language_pattern_mappings(pattern_key,mapping_fingerprint,pattern,operation,capability,goal_payload,attempts,successes,failures,contradiction_count,confidence_sum,promotion_threshold,status,created_at,last_updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(pattern_key,mapping_fingerprint) DO UPDATE SET attempts=language_pattern_mappings.attempts+1,successes=language_pattern_mappings.successes+excluded.successes,failures=language_pattern_mappings.failures+excluded.failures,confidence_sum=language_pattern_mappings.confidence_sum+excluded.confidence_sum,last_success_at=CASE WHEN excluded.successes>0 THEN excluded.last_updated_at ELSE language_pattern_mappings.last_success_at END,last_failure_at=CASE WHEN excluded.failures>0 THEN excluded.last_updated_at ELSE language_pattern_mappings.last_failure_at END,last_updated_at=excluded.last_updated_at,promotion_threshold=MAX(language_pattern_mappings.promotion_threshold,excluded.promotion_threshold),model_version=language_pattern_mappings.model_version+1",
                    (key, fingerprint, str(pattern)[:1000], op[:120], str(capability or '')[:120], payload[:12000],
                     int(ok), int(ok), int(not ok), 0, conf, threshold, 'candidate', timestamp, timestamp),
                )
                # Same pattern with a different mapping is contradictory evidence, but not permission
                # to promote the newer mapping. Existing promoted mappings are revoked on contradiction.
                mappings = conn.execute(
                    "SELECT mapping_fingerprint,status FROM language_pattern_mappings WHERE pattern_key=?",
                    (key,),
                ).fetchall()
                contradiction = len(mappings) > 1
                if contradiction:
                    conn.execute(
                        "UPDATE language_pattern_mappings SET contradiction_count=contradiction_count+1,status=CASE WHEN status='promoted' THEN 'revoked' ELSE status END,last_updated_at=? WHERE pattern_key=?",
                        (timestamp, key),
                    )
        finally:
            conn.close()
        promoted = False
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT attempts,successes,failures,contradiction_count,promotion_threshold,status FROM language_pattern_mappings WHERE pattern_key=? AND mapping_fingerprint=?",
                    (key, fingerprint),
                ).fetchone()
                if not row:
                    return {"inserted": True, "promoted": False, "status": "candidate"}
                attempts, successes, failures, contradictions, threshold, status = row
                confidence_row = conn.execute(
                    "SELECT confidence_sum FROM language_pattern_mappings WHERE pattern_key=? AND mapping_fingerprint=?",
                    (key, fingerprint),
                ).fetchone()
                confidence_mean = float(confidence_row[0] or 0.0) / max(1, int(attempts)) if confidence_row else 0.0
                can_promote = int(successes) >= max(2, int(threshold)) and int(failures) == 0 and int(contradictions) == 0 and confidence_mean >= 0.82
                # Exactly one mapping may be promoted for a pattern; a contradiction revokes existing authority.
                if can_promote:
                    conn.execute("UPDATE language_pattern_mappings SET status='candidate' WHERE pattern_key=?", (key,))
                    conn.execute("UPDATE language_pattern_mappings SET status='promoted' WHERE pattern_key=? AND mapping_fingerprint=?", (key, fingerprint))
                    promoted = True
                status = 'promoted' if can_promote else ('revoked' if int(failures) > 0 or int(contradictions) > 0 else str(status or 'candidate'))
                if not can_promote and status == 'revoked':
                    conn.execute("UPDATE language_pattern_mappings SET status='revoked' WHERE pattern_key=? AND mapping_fingerprint=?", (key, fingerprint))
                conn.commit()
                return {"inserted": True, "promoted": promoted, "status": status,
                        "attempts": int(attempts), "successes": int(successes), "failures": int(failures),
                        "contradictions": int(contradictions), "promotion_threshold": int(threshold), "confidence_mean": round(confidence_mean, 6)}
        finally:
            conn.close()

    def language_pattern_lookup(self, pattern_key: str) -> dict | None:
        key = str(pattern_key or '').strip()
        if not key:
            return None
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT pattern_key,mapping_fingerprint,pattern,operation,capability,goal_payload,attempts,successes,failures,contradiction_count,confidence_sum,promotion_threshold,status,model_version,created_at,last_success_at,last_updated_at FROM language_pattern_mappings WHERE pattern_key=? AND status='promoted' AND successes>=promotion_threshold AND failures=0 AND contradiction_count=0 ORDER BY successes DESC,attempts DESC,last_updated_at DESC LIMIT 1",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            payload=json.loads(row[5] or '{}')
        except Exception:
            payload={}
        return {
            "pattern_key":row[0],"mapping_fingerprint":row[1],"pattern":row[2],"operation":row[3],"capability":row[4],
            "goal_payload":payload,"attempts":int(row[6] or 0),"successes":int(row[7] or 0),"failures":int(row[8] or 0),
            "contradiction_count":int(row[9] or 0),"confidence_mean":float(row[10] or 0.0)/max(1,int(row[6] or 0)),
            "promotion_threshold":int(row[11] or 3),"status":row[12],"model_version":int(row[13] or 1),
            "created_at":row[14],"last_success_at":row[15],"last_updated_at":row[16],
        }

    def language_pattern_mappings(self, *, status: str | None = None, operation: str | None = None, limit: int = 100) -> list[dict]:
        conn=_connect(self.path)
        try:
            clauses=[]; args=[]
            if status:
                clauses.append("status=?"); args.append(str(status))
            if operation:
                clauses.append("operation=?"); args.append(str(operation))
            where=(" WHERE "+" AND ".join(clauses)) if clauses else ""
            rows=conn.execute(
                "SELECT pattern_key,mapping_fingerprint,pattern,operation,capability,attempts,successes,failures,contradiction_count,confidence_sum,promotion_threshold,status,model_version,created_at,last_success_at,last_updated_at FROM language_pattern_mappings"+where+" ORDER BY successes DESC,attempts DESC,last_updated_at DESC LIMIT ?",
                (*args,max(1,int(limit))),
            ).fetchall()
        finally:
            conn.close()
        out=[]
        for r in rows:
            attempts=max(1,int(r[5] or 0))
            out.append({"pattern_key":r[0],"mapping_fingerprint":r[1],"pattern":r[2],"operation":r[3],"capability":r[4],
                        "attempts":int(r[5] or 0),"successes":int(r[6] or 0),"failures":int(r[7] or 0),
                        "contradiction_count":int(r[8] or 0),"confidence_mean":float(r[9] or 0.0)/attempts,
                        "promotion_threshold":int(r[10] or 3),"status":r[11],"model_version":int(r[12] or 1),
                        "created_at":r[13],"last_success_at":r[14],"last_updated_at":r[15]})
        return out

    def language_pattern_stats(self) -> dict:
        conn=_connect(self.path)
        try:
            observations=int(conn.execute("SELECT COUNT(*) FROM language_pattern_observations").fetchone()[0] or 0)
            mappings=int(conn.execute("SELECT COUNT(*) FROM language_pattern_mappings").fetchone()[0] or 0)
            promoted=int(conn.execute("SELECT COUNT(*) FROM language_pattern_mappings WHERE status='promoted'").fetchone()[0] or 0)
            revoked=int(conn.execute("SELECT COUNT(*) FROM language_pattern_mappings WHERE status='revoked'").fetchone()[0] or 0)
            candidate=int(conn.execute("SELECT COUNT(*) FROM language_pattern_mappings WHERE status='candidate'").fetchone()[0] or 0)
            return {"observations":observations,"mappings":mappings,"promoted":promoted,"revoked":revoked,"candidate":candidate,"version":1}
        finally:
            conn.close()

    def upsert_procedural_memory(self, *, task_family_signature: str, operation: str, capability: str,
                                 workflow: list[dict] | tuple[dict, ...], trigger_conditions: list[str] | tuple[str, ...],
                                 termination_conditions: list[str] | tuple[str, ...], recovery_strategy: list[str] | tuple[str, ...],
                                 context_boundary: list[str] | tuple[str, ...], evidence_run_ids: list[str] | tuple[str, ...],
                                 success: bool, confidence: float, key: str | None = None) -> dict:
        import hashlib
        now = _now()
        family = str(task_family_signature or '').strip()
        if not family:
            return {"stored": False, "reason": "missing-family-signature"}
        wf = [dict(x) for x in workflow if isinstance(x, dict)]
        material = _safe_json([family, operation, capability, wf])
        proc_key = str(key or ('proc:' + hashlib.sha256(material.encode()).hexdigest()[:20]))
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT successes,failures,evidence_run_ids,version,created_at,status FROM procedural_memories WHERE key=?",
                    (proc_key,),
                ).fetchone()
                successes = int(row[0] or 0) if row else 0
                failures = int(row[1] or 0) if row else 0
                evidence = json.loads(row[2] or '[]') if row else []
                version = int(row[3] or 1) if row else 1
                created = row[4] if row else now
                status = str(row[5] or 'candidate') if row else 'candidate'
                if success:
                    successes += 1
                else:
                    failures += 1
                evidence = list(dict.fromkeys([str(x) for x in evidence] + [str(x) for x in evidence_run_ids if str(x)]))[-24:]
                mean_conf = max(0.0, min(1.0, float(confidence)))
                # A procedure becomes reusable only after repeated verified evidence.
                promoted = successes >= 2 and failures == 0 and mean_conf >= 0.80
                status = 'promoted' if promoted else ('candidate' if status != 'invalidated' else status)
                conn.execute(
                    "INSERT INTO procedural_memories(key,task_family_signature,operation,capability,workflow,trigger_conditions,termination_conditions,recovery_strategy,context_boundary,evidence_run_ids,successes,failures,confidence,status,version,created_at,last_used_at,invalidated_at,invalidation_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET task_family_signature=excluded.task_family_signature,operation=excluded.operation,capability=excluded.capability,workflow=excluded.workflow,trigger_conditions=excluded.trigger_conditions,termination_conditions=excluded.termination_conditions,recovery_strategy=excluded.recovery_strategy,context_boundary=excluded.context_boundary,evidence_run_ids=excluded.evidence_run_ids,successes=excluded.successes,failures=excluded.failures,confidence=excluded.confidence,status=excluded.status,version=procedural_memories.version+1,last_used_at=excluded.last_used_at,invalidation_reason=excluded.invalidation_reason",
                    (proc_key, family, str(operation), str(capability), _safe_json(wf), _safe_json(list(trigger_conditions)), _safe_json(list(termination_conditions)), _safe_json(list(recovery_strategy)), _safe_json(list(context_boundary)), _safe_json(evidence), successes, failures, mean_conf, status, version, created, now, '', ''),
                )
        finally:
            conn.close()
        return {"stored": True, "key": proc_key, "task_family_signature": family, "successes": successes,
                "failures": failures, "status": status, "version": version, "evidence_run_ids": evidence}

    def procedural_memories(self, *, task_family_signature: str | None = None, operation: str | None = None,
                            capability: str | None = None, include_invalidated: bool = False, limit: int = 12) -> list[dict]:
        clauses=[]; args=[]
        if task_family_signature:
            clauses.append('task_family_signature=?'); args.append(str(task_family_signature))
        if operation:
            clauses.append('operation=?'); args.append(str(operation))
        if capability:
            clauses.append('capability=?'); args.append(str(capability))
        if not include_invalidated:
            clauses.append("status<>'invalidated'")
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        conn=_connect(self.path)
        try:
            rows=conn.execute(
                "SELECT key,task_family_signature,operation,capability,workflow,trigger_conditions,termination_conditions,recovery_strategy,context_boundary,evidence_run_ids,successes,failures,confidence,status,version,created_at,last_used_at,invalidated_at,invalidation_reason FROM procedural_memories"+where+" ORDER BY CASE status WHEN 'promoted' THEN 0 ELSE 1 END,successes DESC,confidence DESC,last_used_at DESC LIMIT ?",
                (*args,max(1,int(limit))),
            ).fetchall()
        finally:
            conn.close()
        def dec(raw):
            try: return json.loads(raw or '[]')
            except Exception: return []
        return [{
            'key':r[0],'task_family_signature':r[1],'operation':r[2],'capability':r[3],
            'workflow':dec(r[4]),'trigger_conditions':dec(r[5]),'termination_conditions':dec(r[6]),
            'recovery_strategy':dec(r[7]),'context_boundary':dec(r[8]),'evidence_run_ids':dec(r[9]),
            'successes':int(r[10] or 0),'failures':int(r[11] or 0),'confidence':float(r[12] or 0),
            'status':r[13],'version':int(r[14] or 1),'created_at':r[15],
            'last_used_at':r[16],'invalidated_at':r[17],'invalidation_reason':r[18],
        } for r in rows]

    def match_procedural_memory(self, task_family_signature: str, *, operation: str = '', capability: str = '',
                                limit: int = 6) -> list[dict]:
        exact=self.procedural_memories(task_family_signature=task_family_signature, operation=operation or None,
                                       capability=capability or None, limit=limit)
        if exact:
            return exact
        # Family-level generalization: exact operation may be unavailable, but the verified task
        # family can still supply a bounded workflow. Never cross a conflicting capability.
        return self.procedural_memories(task_family_signature=task_family_signature, capability=capability or None, limit=limit)

    def invalidate_procedural_memory(self, key: str, *, reason: str) -> bool:
        conn=_connect(self.path)
        try:
            with conn:
                cur=conn.execute("UPDATE procedural_memories SET status='invalidated',invalidated_at=?,invalidation_reason=?,version=version+1 WHERE key=?", (_now(), str(reason)[:500], str(key)))
                return cur.rowcount == 1
        finally:
            conn.close()

    def invalidate_procedural_memories_for_tool(self, tool: str, *, reason: str) -> int:
        """Invalidate promoted/candidate procedures that depend on a drifted runtime tool."""
        tool = str(tool or '').strip()
        if not tool:
            return 0
        conn = _connect(self.path)
        changed = 0
        try:
            with conn:
                rows = conn.execute(
                    "SELECT key,workflow FROM procedural_memories WHERE status<>'invalidated'"
                ).fetchall()
                for key, workflow_json in rows:
                    try:
                        workflow = json.loads(workflow_json or '[]')
                    except Exception:
                        workflow = []
                    depends = any(
                        str(step.get('tool') or '') == tool
                        for step in workflow
                        if isinstance(step, dict)
                    )
                    if not depends:
                        continue
                    cur = conn.execute(
                        "UPDATE procedural_memories SET status='invalidated',invalidated_at=?,invalidation_reason=?,version=version+1 WHERE key=? AND status<>'invalidated'",
                        (_now(), str(reason)[:500], str(key)),
                    )
                    changed += int(cur.rowcount == 1)
        finally:
            conn.close()
        return changed

    def procedural_memory_stats(self) -> dict:
        conn=_connect(self.path)
        try:
            row=conn.execute("SELECT COUNT(*),SUM(status='promoted'),SUM(status='candidate'),SUM(status='invalidated'),COUNT(DISTINCT task_family_signature) FROM procedural_memories").fetchone()
        finally:
            conn.close()
        return {'memories':int(row[0] or 0),'promoted':int(row[1] or 0),'candidate':int(row[2] or 0),'invalidated':int(row[3] or 0),'task_families':int(row[4] or 0),'version':1}

    def upsert_recovery_lesson(self, *, key: str, failure_class: str, root_transition_id: str,
                               root_state_signature: str = '', root_action_signature: str,
                               selected_action_signature: str, quality: float,
                               confidence: float, verified: bool, run_id: str, diagnosis: dict,
                               candidates: list[dict], observed_quality: float | None = None) -> dict:
        now=_now()
        conn=_connect(self.path)
        try:
            with conn:
                existing=conn.execute(
                    "SELECT attempts,verified_successes,mean_quality,verified_quality_sum,verified_quality_count,version,status FROM recovery_lessons WHERE key=?",
                    (key,),
                ).fetchone()
                attempts=int(existing[0] or 0) if existing else 0
                successes=int(existing[1] or 0) if existing else 0
                old_quality=float(existing[2] or 0.0) if existing else 0.0
                verified_quality_sum=float(existing[3] or 0.0) if existing else 0.0
                verified_quality_count=int(existing[4] or 0) if existing else 0
                version=int(existing[5] or 1) if existing else 1
                attempts += 1
                actual_quality = max(0.0, min(1.0, float(observed_quality if observed_quality is not None else (1.0 if verified else 0.0))))
                successes += int(bool(verified))
                mean_quality = old_quality + (float(quality)-old_quality)/max(1,attempts)
                if verified:
                    verified_quality_sum += actual_quality
                    verified_quality_count += 1
                empirical_quality = verified_quality_sum / max(1, verified_quality_count)
                empirical_success_rate = successes / max(1, attempts)
                promoted = successes >= 2 and empirical_success_rate >= 0.75 and empirical_quality >= 0.75
                status='promoted' if promoted else 'candidate'
                conn.execute(
                    "INSERT INTO recovery_lessons(key,failure_class,root_state_signature,root_action_signature,selected_action_signature,attempts,verified_successes,mean_quality,verified_quality_sum,verified_quality_count,confidence,status,version,diagnosis,candidates,last_run_id,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET attempts=excluded.attempts,verified_successes=excluded.verified_successes,mean_quality=excluded.mean_quality,verified_quality_sum=excluded.verified_quality_sum,verified_quality_count=excluded.verified_quality_count,confidence=excluded.confidence,status=excluded.status,version=recovery_lessons.version+1,diagnosis=excluded.diagnosis,candidates=excluded.candidates,last_run_id=excluded.last_run_id,root_state_signature=excluded.root_state_signature,selected_action_signature=excluded.selected_action_signature",
                    (str(key),str(failure_class),str(root_state_signature),str(root_action_signature),str(selected_action_signature),attempts,successes,mean_quality,verified_quality_sum,verified_quality_count,max(0,min(1,float(confidence))),status,version,_safe_json(diagnosis),_safe_json(candidates),str(run_id),now),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO failure_diagnoses(run_id,failure_class,root_transition_id,root_action_signature,prediction_error,failure_expected,avoidable,confidence,diagnosis,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (str(run_id),str(failure_class),str(root_transition_id),str(root_action_signature),float(diagnosis.get('prediction_error',0.0) or 0.0),int(bool(diagnosis.get('failure_expected'))),int(bool(diagnosis.get('avoidable'))),max(0,min(1,float(confidence))),_safe_json(diagnosis),now),
                )
                return {
                    'key':key,'attempts':attempts,'verified_successes':successes,
                    'mean_quality':round(mean_quality,6),'empirical_quality':round(empirical_quality,6),
                    'empirical_success_rate':round(empirical_success_rate,6),
                    'status':status,'promoted':promoted,
                }
        finally:
            conn.close()

    def record_company_delegation_outcome(self, *, capability: str, department: str, specialist: str,
                                          skill_key: str = '', tool: str, verified: bool,
                                          duration: float = 0.0, run_id: str = '',
                                          failure_class: str = '') -> dict:
        """Persist bounded organizational delegation evidence in the existing LearningStore.

        This is optimization/execution evidence, not user memory and not ownership truth.
        Ownership remains declarative in OrganizationCatalog; this table only records outcomes.
        """
        now = _now()
        conn = _connect(self.path)
        try:
            with conn:
                row = conn.execute(
                    "SELECT attempts,verified_successes,verified_failures,total_duration FROM company_delegation_evidence WHERE capability=? AND department=? AND specialist=? AND tool=?",
                    (str(capability), str(department), str(specialist), str(tool)),
                ).fetchone()
                attempts = int(row[0] or 0) if row else 0
                successes = int(row[1] or 0) if row else 0
                failures = int(row[2] or 0) if row else 0
                total_duration = float(row[3] or 0.0) if row else 0.0
                attempts += 1
                if verified:
                    successes += 1
                else:
                    failures += 1
                total_duration += max(0.0, float(duration or 0.0))
                conn.execute(
                    "INSERT INTO company_delegation_evidence(capability,department,specialist,skill_key,tool,attempts,verified_successes,verified_failures,total_duration,last_failure_class,last_run_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(capability,department,specialist,tool) DO UPDATE SET skill_key=excluded.skill_key,attempts=excluded.attempts,verified_successes=excluded.verified_successes,verified_failures=excluded.verified_failures,total_duration=excluded.total_duration,last_failure_class=excluded.last_failure_class,last_run_id=excluded.last_run_id,updated_at=excluded.updated_at",
                    (str(capability), str(department), str(specialist), str(skill_key or ''), str(tool), attempts, successes, failures, total_duration,
                     str(failure_class or ''), str(run_id or ''), now),
                )
                return {
                    'capability': str(capability), 'department': str(department), 'specialist': str(specialist),
                    'skill_key': str(skill_key or ''), 'tool': str(tool), 'attempts': attempts,
                    'verified_successes': successes, 'verified_failures': failures,
                    'verified_success_rate': round(successes / max(1, attempts), 6),
                }
        finally:
            conn.close()

    def company_delegation_evidence(self, *, capability: str | None = None, limit: int = 50) -> list[dict]:
        clauses = []
        args = []
        if capability:
            clauses.append('capability=?')
            args.append(str(capability))
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT capability,department,specialist,skill_key,tool,attempts,verified_successes,verified_failures,total_duration,last_failure_class,last_run_id,updated_at FROM company_delegation_evidence"
                + where + " ORDER BY verified_successes DESC, attempts DESC, specialist, tool LIMIT ?",
                (*args, max(1, int(limit))),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                'capability': r[0], 'department': r[1], 'specialist': r[2], 'skill_key': r[3], 'tool': r[4],
                'attempts': int(r[5]), 'verified_successes': int(r[6]), 'verified_failures': int(r[7]),
                'total_duration': float(r[8]), 'last_failure_class': r[9], 'last_run_id': r[10], 'updated_at': r[11],
                'verified_success_rate': int(r[6]) / max(1, int(r[5])),
            } for r in rows
        ]

    def create_company_project(self, project: dict) -> dict:
        now = str(project.get('created_at') or project.get('updated_at') or _now())
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO company_projects(project_id,name,objective,priority,horizon,status,criticality,metadata,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (str(project['project_id']), str(project.get('name') or project['project_id']), str(project.get('objective') or ''),
                     float(project.get('priority',0.5)), str(project.get('horizon') or 'medium'), str(project.get('status') or 'active'),
                     float(project.get('criticality',0.5)), _safe_json(project.get('metadata') or {}), int(project.get('version',1)), now, now),
                )
            return self.get_company_project(str(project['project_id'])) or dict(project)
        finally:
            conn.close()

    def get_company_project(self, project_id: str) -> dict | None:
        conn = _connect(self.path)
        try:
            row = conn.execute("SELECT project_id,name,objective,priority,horizon,status,criticality,metadata,version,created_at,updated_at FROM company_projects WHERE project_id=?", (str(project_id),)).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return {'project_id':row[0],'name':row[1],'objective':row[2],'priority':float(row[3]),'horizon':row[4],'status':row[5],'criticality':float(row[6]),'metadata':json.loads(row[7] or '{}'),'version':int(row[8]),'created_at':row[9],'updated_at':row[10]}

    def list_company_projects(self, *, active_only: bool = False) -> list[dict]:
        conn = _connect(self.path)
        try:
            where = " WHERE status='active'" if active_only else ''
            rows = conn.execute("SELECT project_id,name,objective,priority,horizon,status,criticality,metadata,version,created_at,updated_at FROM company_projects"+where+" ORDER BY priority DESC, project_id").fetchall()
        finally:
            conn.close()
        return [{'project_id':r[0],'name':r[1],'objective':r[2],'priority':float(r[3]),'horizon':r[4],'status':r[5],'criticality':float(r[6]),'metadata':json.loads(r[7] or '{}'),'version':int(r[8]),'created_at':r[9],'updated_at':r[10]} for r in rows]

    def update_company_project(self, project_id: str, changes: dict) -> None:
        if not changes:
            return
        fields=[];args=[]
        for key in ('name','objective','priority','horizon','status','criticality','metadata'):
            if key in changes:
                fields.append(key+'=?'); args.append(_safe_json(changes[key]) if key=='metadata' else changes[key])
        if not fields:
            return
        fields.extend(['version=version+1','updated_at=?']); args.extend([_now(), str(project_id)])
        conn=_connect(self.path)
        try:
            with conn: conn.execute('UPDATE company_projects SET '+','.join(fields)+' WHERE project_id=?', tuple(args))
        finally: conn.close()

    def upsert_company_project_task(self, task: dict) -> None:
        conn=_connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO company_project_tasks(project_id,task_id,objective,department,specialist,priority,horizon,status,depends_on,estimated_duration,exclusive_resources,ready,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(project_id,task_id) DO UPDATE SET objective=excluded.objective,department=excluded.department,specialist=excluded.specialist,priority=excluded.priority,horizon=excluded.horizon,status=excluded.status,depends_on=excluded.depends_on,estimated_duration=excluded.estimated_duration,exclusive_resources=excluded.exclusive_resources,ready=excluded.ready,updated_at=excluded.updated_at",
                    (str(task['project_id']),str(task['task_id']),str(task.get('objective') or ''),str(task.get('department') or ''),str(task.get('specialist') or ''),float(task.get('priority',0.5)),str(task.get('horizon') or 'medium'),str(task.get('status') or 'pending'),_safe_json(task.get('depends_on') or []),float(task.get('estimated_duration',0.0)),_safe_json(task.get('exclusive_resources') or []),int(bool(task.get('ready',True))),str(task.get('created_at') or _now()),str(task.get('updated_at') or _now())),
                )
        finally: conn.close()

    def list_company_project_tasks(self, project_id: str, *, active_only: bool = False) -> list[dict]:
        conn=_connect(self.path)
        try:
            where=" AND status NOT IN ('completed','verified','cancelled')" if active_only else ''
            rows=conn.execute("SELECT project_id,task_id,objective,department,specialist,priority,horizon,status,depends_on,estimated_duration,exclusive_resources,ready,created_at,updated_at FROM company_project_tasks WHERE project_id=?"+where+" ORDER BY priority DESC, task_id",(str(project_id),)).fetchall()
        finally: conn.close()
        out=[]
        for r in rows:
            out.append({'project_id':r[0],'task_id':r[1],'objective':r[2],'department':r[3],'specialist':r[4],'priority':float(r[5]),'horizon':r[6],'status':r[7],'depends_on':json.loads(r[8] or '[]'),'estimated_duration':float(r[9]),'exclusive_resources':json.loads(r[10] or '[]'),'ready':bool(r[11]),'created_at':r[12],'updated_at':r[13]})
        return out

    def recovery_lessons(self, *, failure_class: str | None = None, status: str | None = None, limit: int = 50) -> list[dict]:
        clauses=[];args=[]
        if failure_class: clauses.append('failure_class=?');args.append(str(failure_class))
        if status: clauses.append('status=?');args.append(str(status))
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        conn=_connect(self.path)
        try:
            rows=conn.execute("SELECT key,failure_class,root_state_signature,root_action_signature,selected_action_signature,attempts,verified_successes,mean_quality,verified_quality_sum,verified_quality_count,confidence,status,version,last_run_id,created_at FROM recovery_lessons"+where+" ORDER BY verified_successes DESC,mean_quality DESC,last_run_id DESC LIMIT ?",(*args,max(1,int(limit)))).fetchall()
        finally: conn.close()
        return [{'key':r[0],'failure_class':r[1],'root_state_signature':r[2],'root_action_signature':r[3],'selected_action_signature':r[4],'attempts':int(r[5]),'verified_successes':int(r[6]),'mean_quality':float(r[7]),'verified_quality_sum':float(r[8]),'verified_quality_count':int(r[9]),'empirical_quality':(float(r[8])/max(1,int(r[9]))),'empirical_success_rate':(int(r[6])/max(1,int(r[5]))),'confidence':float(r[10]),'status':r[11],'version':int(r[12]),'last_run_id':r[13],'created_at':r[14]} for r in rows]

    def record_meta_strategy_observation(self, state_type: str, strategy: str, reward: float, success: bool, metadata: dict | None = None) -> dict:
        now = _now()
        conn = _connect(self.path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO meta_strategy_observations(state_type,strategy,reward,success,metadata,created_at) VALUES(?,?,?,?,?,?)",
                    (str(state_type), str(strategy), max(-1.0, min(1.0, float(reward))), int(bool(success)), _safe_json(metadata or {}), now),
                )
        finally:
            conn.close()
        return {"recorded": True, "state_type": str(state_type), "strategy": str(strategy),
                "reward": float(reward), "success": bool(success), "created_at": now}

    def meta_strategy_observation(self, state_type: str, strategy: str) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute(
                "SELECT COUNT(*),COALESCE(AVG(reward),0),COALESCE(AVG(success),0) FROM meta_strategy_observations WHERE state_type=? AND strategy=?",
                (str(state_type), str(strategy)),
            ).fetchone()
        finally:
            conn.close()
        return {"state_type": str(state_type), "strategy": str(strategy), "attempts": int(row[0] or 0),
                "reward_mean": float(row[1] or 0.0), "success_rate": float(row[2] or 0.0)}

    def meta_strategy_preferences(self, *, limit: int = 200) -> list[dict]:
        conn = _connect(self.path)
        try:
            rows = conn.execute(
                "SELECT state_type,strategy,COUNT(*),COALESCE(AVG(reward),0),COALESCE(AVG(success),0),MAX(created_at) FROM meta_strategy_observations GROUP BY state_type,strategy ORDER BY state_type,AVG(reward) DESC,COUNT(*) DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        finally:
            conn.close()
        return [{"state_type": r[0], "strategy": r[1], "attempts": int(r[2] or 0),
                 "reward_mean": round(float(r[3] or 0.0), 6), "success_rate": round(float(r[4] or 0.0), 6),
                 "last_updated_at": r[5]} for r in rows]

    def meta_strategy_stats(self) -> dict:
        conn = _connect(self.path)
        try:
            row = conn.execute("SELECT COUNT(*),COUNT(DISTINCT state_type),COUNT(DISTINCT strategy) FROM meta_strategy_observations").fetchone()
        finally:
            conn.close()
        return {"observations": int(row[0] or 0), "state_types": int(row[1] or 0),
                "strategies": int(row[2] or 0), "version": 1}

    def self_model_stats(self) -> dict:
        conn=_connect(self.path)
        try:
            observations=int(conn.execute("SELECT COUNT(*) FROM self_model_observations").fetchone()[0] or 0)
            metric_rows=int(conn.execute("SELECT COUNT(*) FROM self_model_metrics").fetchone()[0] or 0)
            tools=int(conn.execute("SELECT COUNT(DISTINCT tool) FROM self_model_observations").fetchone()[0] or 0)
            contexts=int(conn.execute("SELECT COUNT(DISTINCT context_signature) FROM self_model_observations WHERE context_signature<>''").fetchone()[0] or 0)
        finally:
            conn.close()
        return {"observations":observations,"metric_rows":metric_rows,"tools":tools,"contexts":contexts,"version":2}

    def stats(self) -> dict:
        conn = _connect(self.path)
        try:
            ex=conn.execute("SELECT COUNT(*),SUM(status='completed'),SUM(status='failed') FROM experiences").fetchone()
            lessons=conn.execute("SELECT COUNT(*),SUM(status='active') FROM lessons").fetchone()
            evals=conn.execute("SELECT COUNT(*),SUM(regression),AVG(delta) FROM skill_evaluations").fetchone()
            procedure_rows=conn.execute("SELECT operation,steps,status FROM experiences WHERE operation <> '' ORDER BY id DESC LIMIT 2000").fetchall()
        finally:
            conn.close()
        procedure_keys = set()
        for operation, steps_json, status in procedure_rows:
            if str(status) != "completed":
                continue
            try:
                steps = json.loads(steps_json or "[]")
            except Exception:
                steps = []
            workflow = tuple(str(step.get("tool") or "") for step in steps if isinstance(step, dict) and step.get("tool"))
            if len(workflow) >= 2:
                procedure_keys.add((str(operation), workflow))
        return {"experiences": int(ex[0] or 0), "completed": int(ex[1] or 0), "verified": int(ex[1] or 0), "failed": int(ex[2] or 0),
                "lessons": int(lessons[0] or 0), "active_lessons": int(lessons[1] or 0),
                "evaluations": int(evals[0] or 0), "regressions": int(evals[1] or 0),
                "mean_delta": round(float(evals[2] or 0.0), 6), "procedures": len(procedure_keys),
                "exploration": self.exploration_stats()}
