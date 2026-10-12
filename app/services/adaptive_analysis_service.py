"""V13 public facade for adaptive evidence analysis."""
from app.services.data_analysis_service import comprehensive_analysis, verify_comprehensive_report, compare_numeric_effect
from app.planning.adaptive_portfolio import AlgorithmChoice, context_signature, learned_ucb, select_trend_method
from app.knowledge.statistics.statistics_v13 import autocorrelation, choose_confidence_interval_method, moving_block_bootstrap_ci


def adaptive_analyze(path, memory=None, seed_text=None):
    return comprehensive_analysis(path, seed_text=seed_text, memory=memory)
