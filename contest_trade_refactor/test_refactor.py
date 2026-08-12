"""
Test script for refactored ContestTrade

Tests:
1. DataAnalysisPipeline (Pipeline pattern)
2. ResearchAgentLoop (Agent Loop pattern)
3. Complete TradeCompany workflow
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_data_pipeline():
    """Test DataAnalysisPipeline"""
    print("\n" + "=" * 80)
    print("TEST 1: DataAnalysisPipeline")
    print("=" * 80)

    try:
        from agents.data_analysis_pipeline import DataAnalysisPipeline

        pipeline = DataAnalysisPipeline(
            agent_name="test_pipeline",
            source_list=["data_source.sina_news.SinaNews"],
            final_target_tokens=2000,
            bias_goal="",
        )

        trigger_time = "2024-01-23 09:00:00"
        print(f"\n🚀 Running Pipeline for {trigger_time}...")

        result = await pipeline.run(trigger_time)

        print(f"\n✅ Pipeline Completed:")
        print(f"   Agent: {result['agent_name']}")
        print(f"   Context Length: {len(result['context_string'])} chars")
        print(f"   References: {len(result['references'])}")
        print(f"   Batches: {len(result['batch_summaries'])}")

        if result['context_string']:
            print(f"\n   Preview:")
            print(f"   {result['context_string'][:200]}...")

        return True

    except Exception as e:
        print(f"\n❌ Pipeline Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_research_loop():
    """Test ResearchAgentLoop"""
    print("\n" + "=" * 80)
    print("TEST 2: ResearchAgentLoop")
    print("=" * 80)

    try:
        from agents.research_agent_loop import (
            ResearchAgentLoop,
            ResearchAgentLoopConfig,
            ResearchAgentInput,
        )

        config = ResearchAgentLoopConfig(
            agent_name="test_research",
            belief="Focus on technology stocks with strong fundamentals",
            max_iterations=3,
            verbose=True,
        )

        agent = ResearchAgentLoop(config)

        # Simple background for testing
        background = """
        <market_information>
        <global_summary>
        <source>test_source</source>
        <timestamp>2024-01-23 09:00:00</timestamp>
        <content>Technology sector showing positive momentum with strong earnings reports.</content>
        </global_summary>
        </market_information>

        <target_market>
        CN-Stock
        </target_market>

        <your_belief>
        Focus on technology stocks with strong fundamentals
        </your_belief>
        """

        trigger_time = "2024-01-23 09:00:00"
        print(f"\n🚀 Running Research Agent for {trigger_time}...")

        input_data = ResearchAgentInput(
            trigger_time=trigger_time,
            background_information=background,
        )

        result = await agent.run(input_data)

        print(f"\n✅ Research Agent Completed:")
        print(f"   Task: {result.task[:100]}...")
        print(f"   Belief: {result.belief[:100]}...")
        print(f"   Final Result Length: {len(result.final_result)} chars")
        print(f"   Thinking Length: {len(result.final_result_thinking)} chars")

        if result.final_result:
            print(f"\n   Result Preview:")
            print(f"   {result.final_result[:200]}...")

        return True

    except Exception as e:
        print(f"\n❌ Research Agent Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_trade_company():
    """Test complete TradeCompany workflow"""
    print("\n" + "=" * 80)
    print("TEST 3: SimpleTradeCompany (Full Workflow)")
    print("=" * 80)

    try:
        from main_loop import SimpleTradeCompany

        company = SimpleTradeCompany()

        trigger_time = "2024-01-23 09:00:00"
        print(f"\n🚀 Running Trade Company for {trigger_time}...")

        result = await company.run(trigger_time)

        print(f"\n✅ Trade Company Completed:")
        print(f"   Trigger Time: {result['trigger_time']}")
        print(f"   Data Factors: {len(result['data_factors'])}")
        print(f"   Research Signals: {len(result['research_signals'])}")
        print(f"   Best Signals: {len(result['best_signals'])}")

        if result['best_signals']:
            print(f"\n   Top 3 Signals:")
            for i, signal in enumerate(result['best_signals'][:3], 1):
                symbol = signal.get('symbol_name', 'Unknown')
                action = signal.get('action', 'Unknown')
                print(f"   {i}. {symbol} - {action}")

        return True

    except Exception as e:
        print(f"\n❌ Trade Company Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all tests"""
    print("\n" + "🧪" * 40)
    print("ContestTrade Refactor - Test Suite")
    print("🧪" * 40)

    results = []

    # Test 1: Pipeline
    result1 = await test_data_pipeline()
    results.append(("DataAnalysisPipeline", result1))

    # Test 2: Loop
    result2 = await test_research_loop()
    results.append(("ResearchAgentLoop", result2))

    # Test 3: Full workflow
    result3 = await test_trade_company()
    results.append(("TradeCompany", result3))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {name}")

    all_passed = all(r[1] for r in results)

    if all_passed:
        print("\n" + "✅" * 40)
        print("All Tests PASSED!")
        print("✅" * 40)
    else:
        print("\n" + "❌" * 40)
        print("Some Tests FAILED!")
        print("❌" * 40)

    return all_passed


async def quick_test():
    """Quick smoke test"""
    print("\n🔥 Quick Smoke Test")
    print("=" * 80)

    try:
        # Test imports
        from agents.base_agent_loop import BaseAgentLoop, ReactAgentLoop
        from agents.data_analysis_pipeline import DataAnalysisPipeline
        from agents.research_agent_loop import ResearchAgentLoop
        from main_loop import SimpleTradeCompany

        print("✅ All imports successful")

        # Test instantiation
        pipeline = DataAnalysisPipeline(
            agent_name="smoke_test",
            source_list=["data_source.sina_news.SinaNews"],
        )
        print("✅ Pipeline instantiation successful")

        from agents.research_agent_loop import ResearchAgentLoopConfig
        config = ResearchAgentLoopConfig(
            agent_name="smoke_test",
            belief="test",
        )
        agent = ResearchAgentLoop(config)
        print("✅ Research Agent instantiation successful")

        company = SimpleTradeCompany()
        print("✅ Trade Company instantiation successful")

        print("\n✅ Smoke test PASSED - All components loadable")
        return True

    except Exception as e:
        print(f"\n❌ Smoke test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test refactored ContestTrade")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick smoke test only"
    )
    parser.add_argument(
        "--test",
        choices=["pipeline", "loop", "company", "all"],
        default="all",
        help="Which test to run"
    )

    args = parser.parse_args()

    if args.quick:
        asyncio.run(quick_test())
    elif args.test == "pipeline":
        asyncio.run(test_data_pipeline())
    elif args.test == "loop":
        asyncio.run(test_research_loop())
    elif args.test == "company":
        asyncio.run(test_trade_company())
    else:
        asyncio.run(run_all_tests())
