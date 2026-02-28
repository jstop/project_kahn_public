#!/usr/bin/env python3
"""
Osmio Tournament Runner

Runs three parallel tournaments with identical matchups under different
experimental conditions to test whether institutional infrastructure
(the Osmio layer) produces cooperation in AI crisis games.

Tournament Structure:
  1. CONTROL:       Original Project Kahn -- no Osmio layers
  2. IDENTITY_ONLY: Layers 1-2 (persistent identity + signed commitments)
  3. FULL_STACK:    All 5 layers (identity, commitments, monitoring, sanctions, networks)

Cross-game state (persistent identity, reputation, alliance membership) is
maintained within each condition's tournament but NOT shared across conditions.

Usage:
  python osmio_tournament.py \\
      --models claude-sonnet-4-20250514 gpt-5.2 gemini-3-flash-preview \\
      --scenarios v7_alliance v7_power_transition_b_rising \\
      --conditions control identity_only full_stack

  # Minimal test run
  python osmio_tournament.py \\
      --models claude-sonnet-4-20250514 gpt-5.2 \\
      --scenarios v7_alliance \\
      --conditions control full_stack \\
      --turns 10
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from itertools import permutations
from typing import Dict, List, Any, Optional

from osmio import (
    OsmioConfig, OsmioMetrics,
    AgentIdentity, create_agent_identity,
)
from Kahn_game_v13_osmio import run_kahn_game_v13

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def generate_matchups(models: List[str], scenarios: List[str]) -> List[Dict[str, str]]:
    """Generate all matchup combinations.

    For each pair of models (A vs B and B vs A) and each scenario,
    generate a matchup with each side as aggressor.
    """
    matchups = []
    for scenario in scenarios:
        for model_a, model_b in permutations(models, 2):
            for aggressor in ['A', 'B']:
                matchups.append({
                    'model_a': model_a,
                    'model_b': model_b,
                    'scenario': scenario,
                    'aggressor': aggressor,
                })
    return matchups


def run_condition_tournament(
        condition: str,
        matchups: List[Dict[str, str]],
        max_turns: int,
        results_dir: str) -> Dict[str, Any]:
    """Run a complete tournament under one experimental condition.

    Persistent identities carry across games within the tournament.

    Returns metrics summary dict.
    """
    config_map = {
        'control': OsmioConfig.control,
        'identity_only': OsmioConfig.identity_only,
        'full_stack': OsmioConfig.full_stack,
    }
    osmio_config = config_map[condition]()
    metrics = OsmioMetrics(condition=condition)

    # Create persistent identities for each model (keyed by model name)
    # Identities persist across games within this tournament condition
    identities: Dict[str, Dict[str, AgentIdentity]] = {}  # model_name -> {side -> identity}

    def get_identity(model_name: str, side: str) -> AgentIdentity:
        """Get or create a persistent identity for a model."""
        key = f"{model_name}:{side}"
        if key not in identities:
            identities[key] = create_agent_identity(model_name, side)
        return identities[key]

    condition_dir = os.path.join(results_dir, condition)
    os.makedirs(condition_dir, exist_ok=True)

    logger.info(f"\n{'=' * 70}")
    logger.info(f"TOURNAMENT CONDITION: {condition.upper()}")
    logger.info(f"Games to play: {len(matchups)}")
    logger.info(f"{'=' * 70}")

    game_results = []

    for i, matchup in enumerate(matchups, 1):
        model_a = matchup['model_a']
        model_b = matchup['model_b']
        scenario = matchup['scenario']
        aggressor = matchup['aggressor']

        logger.info(f"\n--- Game {i}/{len(matchups)} [{condition}] ---")
        logger.info(f"  {model_a} vs {model_b}")
        logger.info(f"  Scenario: {scenario}, Aggressor: {aggressor}")

        identity_a = get_identity(model_a, 'A') if osmio_config.identity_enabled else None
        identity_b = get_identity(model_b, 'B') if osmio_config.identity_enabled else None

        try:
            result_file = run_kahn_game_v13(
                state_a_model=model_a,
                state_b_model=model_b,
                aggressor_side=aggressor,
                max_turns=max_turns,
                scenario_key=scenario,
                results_dir=condition_dir,
                osmio_config=osmio_config,
                identity_a=identity_a,
                identity_b=identity_b,
            )

            # Read back the CSV to compute metrics
            import pandas as pd
            df = pd.read_csv(result_file)
            history = df.to_dict('records')

            # Extract osmio-specific data for metrics
            osmio_data = []
            for r in history:
                osmio_data.append({
                    'a_commitment_violated': r.get('a_commitment_violated', False),
                    'b_commitment_violated': r.get('b_commitment_violated', False),
                    'a_sanction_applied': r.get('a_sanction_applied', False),
                    'b_sanction_applied': r.get('b_sanction_applied', False),
                })
            metrics.record_game(history, osmio_data)

            game_results.append({
                'game_number': i,
                'model_a': model_a,
                'model_b': model_b,
                'scenario': scenario,
                'aggressor': aggressor,
                'result_file': result_file,
                'turns': len(history),
                'final_territory': history[-1].get('territory_balance', 0.0) if history else 0.0,
                'status': 'completed',
            })
            logger.info(f"  Game completed: {len(history)} turns, "
                        f"territory={history[-1].get('territory_balance', 0.0):.2f}")

        except Exception as e:
            logger.error(f"  Game failed: {e}")
            game_results.append({
                'game_number': i,
                'model_a': model_a,
                'model_b': model_b,
                'scenario': scenario,
                'aggressor': aggressor,
                'status': 'failed',
                'error': str(e),
            })

    # Save game results index
    results_index_path = os.path.join(condition_dir, 'tournament_index.json')
    with open(results_index_path, 'w') as f:
        json.dump(game_results, f, indent=2, default=str)

    # Save metrics
    metrics_path = os.path.join(condition_dir, 'metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(metrics.summary(), f, indent=2)

    logger.info(f"\n{metrics.format_report()}")

    return metrics.summary()


def run_full_tournament(
        models: List[str],
        scenarios: List[str],
        conditions: List[str],
        max_turns: int,
        results_dir: str) -> None:
    """Run the complete three-condition tournament and produce comparison."""

    matchups = generate_matchups(models, scenarios)
    logger.info(f"Tournament: {len(models)} models, {len(scenarios)} scenarios, "
                f"{len(matchups)} matchups per condition, {len(conditions)} conditions")
    logger.info(f"Total games: {len(matchups) * len(conditions)}")

    all_metrics = {}

    for condition in conditions:
        summary = run_condition_tournament(
            condition, matchups, max_turns, results_dir)
        all_metrics[condition] = summary

    # ── Comparison Report ──
    print("\n" + "=" * 70)
    print("OSMIO TOURNAMENT COMPARISON")
    print("=" * 70)

    header = f"{'Metric':<35}"
    for cond in conditions:
        header += f"  {cond:>15}"
    print(header)
    print("-" * (35 + 17 * len(conditions)))

    comparison_keys = [
        ('games_played', 'Games played', '{:>15d}'),
        ('total_turns', 'Total turns', '{:>15d}'),
        ('avg_game_duration', 'Avg game duration', '{:>15.1f}'),
        ('tactical_nuclear_pct', 'Tactical nuclear %', '{:>14.0%} '),
        ('strategic_nuclear_pct', 'Strategic nuclear %', '{:>14.0%} '),
        ('full_nuclear_pct', 'Full nuclear war %', '{:>14.0%} '),
        ('deescalation_rate', 'De-escalation rate', '{:>14.1%} '),
        ('mean_signal_action_gap', 'Mean signal-action gap', '{:>15.1f}'),
        ('deception_rate', 'Deception rate (gap>100)', '{:>14.1%} '),
        ('mutual_destruction_count', 'Mutual destruction', '{:>15d}'),
        ('commitment_violations', 'Commitment violations', '{:>15d}'),
        ('commitment_honors', 'Commitments honored', '{:>15d}'),
        ('sanctions_applied', 'Sanctions applied', '{:>15d}'),
    ]

    for key, label, fmt in comparison_keys:
        row = f"{label:<35}"
        for cond in conditions:
            val = all_metrics.get(cond, {}).get(key, 0)
            row += fmt.format(val)
        print(row)

    print("=" * 70)

    # Save comparison
    comparison_path = os.path.join(results_dir, 'tournament_comparison.json')
    with open(comparison_path, 'w') as f:
        json.dump(all_metrics, f, indent=2)
    print(f"\nFull comparison saved to: {comparison_path}")

    # Save human-readable report
    report_path = os.path.join(results_dir, 'tournament_report.txt')
    with open(report_path, 'w') as f:
        f.write("OSMIO TOURNAMENT REPORT\n")
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Models: {', '.join(models)}\n")
        f.write(f"Scenarios: {', '.join(scenarios)}\n")
        f.write(f"Conditions: {', '.join(conditions)}\n")
        f.write(f"Max turns per game: {max_turns}\n")
        f.write(f"Matchups per condition: {len(matchups)}\n\n")
        for cond in conditions:
            m = all_metrics.get(cond, {})
            f.write(f"\n{'=' * 50}\n")
            f.write(f"CONDITION: {cond.upper()}\n")
            f.write(f"{'=' * 50}\n")
            for key, label, fmt in comparison_keys:
                val = m.get(key, 0)
                f.write(f"  {label}: {val}\n")
    print(f"Report saved to: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Osmio Tournament: Institutional Infrastructure in AI Crisis Games')
    parser.add_argument('--models', nargs='+', required=True,
                        help='Models to include in tournament')
    parser.add_argument('--scenarios', nargs='+', default=['v7_alliance'],
                        help='Scenarios to test')
    parser.add_argument('--conditions', nargs='+',
                        default=['control', 'identity_only', 'full_stack'],
                        choices=['control', 'identity_only', 'full_stack'],
                        help='Experimental conditions to run')
    parser.add_argument('--turns', type=int, default=50,
                        help='Maximum turns per game')
    parser.add_argument('--results_dir', type=str, default=None,
                        help='Output directory for results')

    args = parser.parse_args()

    if args.results_dir is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.results_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            f'osmio_tournament_{timestamp}')

    run_full_tournament(
        models=args.models,
        scenarios=args.scenarios,
        conditions=args.conditions,
        max_turns=args.turns,
        results_dir=args.results_dir,
    )


if __name__ == '__main__':
    main()
