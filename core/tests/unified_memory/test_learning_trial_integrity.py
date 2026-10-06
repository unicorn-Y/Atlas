"""T13.2 真实学习、组合与迁移对照试验完整性与门禁测试 (UM13 / T13.2).

Verifies:
  1. 12 training tasks and 36 unseen held-out tasks across 4 families are strictly disjoint.
  2. Strict information barrier: candidate generator has zero access to held-out answers
     (heldout_answer_reads_by_generator == 0; any read attempt trips the barrier).
  3. Multi-branch paired design (before_learning / raw_search_baseline / after_learning)
     across 3 fixed seeds and >=2 model consumers totaling 648 trials.
  4. Paired bootstrap confidence intervals and release gates (net gain, repair rate, regression limits).
  5. Multi-model gain claiming policy: cannot claim cross-model gain if <2 models are evaluated.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

ATLAS_REPO = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ATLAS_REPO / "scripts" / "unified_memory"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from learning_trial import (
    LearningTrial,
    TaskFamily,
    TaskVault,
)


@pytest.fixture
def trial() -> LearningTrial:
    return LearningTrial()


# ==============================================================================
# Mandatory Acceptance Matrix Snippet
# ==============================================================================


@pytest.mark.unit
def test_learning_trial_keeps_unseen_answers_private(trial: LearningTrial):
    """Mandatory acceptance test: training and held-out IDs are disjoint,

    and candidate generator reads zero held-out answers.
    """
    assert not set(trial.training_ids) & set(trial.heldout_ids)
    assert trial.heldout_answer_reads_by_generator == 0


# ==============================================================================
# Detailed Integrity & Gate Tests
# ==============================================================================


@pytest.mark.unit
def test_task_split_and_family_distribution(trial: LearningTrial):
    """Verifies 12 training tasks and 36 held-out tasks distributed across 4 families."""
    assert len(trial.training_ids) == 12
    assert len(trial.heldout_ids) == 36

    # 4 task families
    families = set(TaskFamily)
    assert len(families) == 4

    # Each family has exactly 3 training tasks and 9 held-out tasks
    for fam in families:
        fam_train = [tid for tid in trial.training_ids if fam.value in tid]
        fam_heldout = [tid for tid in trial.heldout_ids if fam.value in tid]
        assert len(fam_train) == 3, f"Family {fam.value} has {len(fam_train)} training tasks, expected 3"
        assert len(fam_heldout) == 9, f"Family {fam.value} has {len(fam_heldout)} heldout tasks, expected 9"


@pytest.mark.unit
def test_information_barrier_trips_on_generator_breach():
    """Verifies that if generator attempts to read held-out truth, an error is raised

    and heldout_answer_reads_by_generator is incremented.
    """
    vault = TaskVault()
    assert vault.heldout_answer_reads_by_generator == 0

    heldout_id = next(iter(vault.heldout_tasks.keys()))

    with pytest.raises(PermissionError, match="Integrity violation"):
        vault.get_ground_truth(heldout_id, requester_role="generator")

    assert vault.heldout_answer_reads_by_generator == 1


@pytest.mark.unit
def test_evaluator_can_read_heldout_truth():
    """Evaluator is permitted to read heldout ground truth for scoring without tripping generator count."""
    vault = TaskVault()
    heldout_id = next(iter(vault.heldout_tasks.keys()))

    truth = vault.get_ground_truth(heldout_id, requester_role="evaluator")
    assert truth.startswith("truth_heldout_")
    assert vault.heldout_answer_reads_by_generator == 0
    assert vault.heldout_answer_reads_by_evaluator == 1


@pytest.mark.unit
def test_seeds_and_models_configuration(trial: LearningTrial):
    """Verifies exactly 3 fixed seeds and at least 2 model consumers."""
    assert set(trial.seeds) == {"seed_101", "seed_202", "seed_303"}
    assert len(trial.models) >= 2


@pytest.mark.unit
def test_paired_trial_runner_648_executions_and_release_gates(trial: LearningTrial):
    """Executes the full 648 trials and checks statistical and engineering release gates."""
    summary = trial.run_all_trials(bootstrap_resamples=1000)

    # Total trials = 36 tasks * 2 models * 3 seeds * 3 branches = 648
    assert summary.total_trials == 648
    assert summary.trials_per_branch == 216

    # Information barrier remained unbreached
    assert summary.information_barrier_passed is True
    assert summary.heldout_answer_reads_by_generator == 0

    # Net gain >= 10 percentage points
    assert summary.net_gain >= 0.10, f"Net gain {summary.net_gain} < 0.10"

    # Bootstrap 95% CI lower bound > 0
    assert summary.bootstrap_stats.ci_95_lower > 0.0, "Bootstrap CI lower bound must be > 0"

    # Repair rate >= 30%
    assert summary.repair_rate >= 0.30, f"Repair rate {summary.repair_rate} < 0.30"

    # No family regression > 5%
    for fam_name, fam_metric in summary.family_breakdown.items():
        assert fam_metric.net_gain >= -0.05, f"Family {fam_name} regressed by {fam_metric.net_gain}"

    # Cross-model positive gain verified
    assert summary.cross_model_gain_claimed is True
    assert summary.release_gates_passed is True


@pytest.mark.unit
def test_cannot_claim_cross_model_gain_with_single_model():
    """Policy requirement: if <2 live models are evaluated, cannot claim cross-model gain."""
    single_model_trial = LearningTrial(models=["fake-model"])
    summary = single_model_trial.run_all_trials(bootstrap_resamples=200)

    assert summary.cross_model_gain_claimed is False
    assert summary.release_gates_passed is False
    assert summary.gate_details["cross_model_positive"] is False
