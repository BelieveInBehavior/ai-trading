#!/usr/bin/env bash
# Convenience runner for the quant closed-loop backtest + portfolio simulation.
# Optionally runs walk-forward validation too.
#
# Usage:
#   ./scripts/run_quant_backtest.sh
#   ./scripts/run_quant_backtest.sh --glob 'agents_workspace/results/trade_decisions/*.json'
#   ./scripts/run_quant_backtest.sh --walk-forward
set -euo pipefail

cd "$(dirname "$0")/.."

GLOB="agents_workspace/results/trade_decisions/*.json"
WALK="no"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --glob)
      GLOB="$2"
      shift 2
      ;;
    --walk-forward)
      WALK="yes"
      shift
      ;;
    *)
      echo "Unknown arg: $1"
      exit 1
      ;;
  esac
done

echo "== Step 1: signal closed-loop evaluation =="
.venv/bin/python scripts/backtest_signal_closed_loop.py --glob "$GLOB" --parallel 4

echo ""
echo "== Step 2: portfolio simulation (buy_passed only; watch/research off by default) =="
.venv/bin/python scripts/portfolio_simulator.py --input agents_workspace/backtest_results/signal_performance.csv

if [[ "$WALK" == "yes" ]]; then
  echo ""
  echo "== Step 3: walk-forward factor validation =="
  .venv/bin/python scripts/walk_forward_validation.py --input agents_workspace/backtest_results/signal_performance.csv
fi

echo ""
echo "Done. Reports in agents_workspace/backtest_results/"
