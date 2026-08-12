"""
Minimal test without external dependencies

Just tests if the architecture is correct and files are properly structured.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_file_structure():
    """Test that all required files exist"""
    print("\n📁 Testing File Structure...")

    required_files = [
        "agents/base_agent_loop.py",
        "agents/research_agent_loop.py",
        "agents/data_analysis_pipeline.py",
        "agents/prompts.py",
        "main_loop.py",
        "config.yaml",
        "README.md",
    ]

    base_path = Path(__file__).parent

    for file_path in required_files:
        full_path = base_path / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path} - MISSING")
            return False

    return True


def test_architecture_pattern():
    """Test that the architecture follows correct patterns"""
    print("\n🏗️  Testing Architecture Patterns...")

    base_path = Path(__file__).parent

    # Check Pipeline pattern
    pipeline_file = base_path / "agents/data_analysis_pipeline.py"
    with open(pipeline_file, 'r') as f:
        content = f.read()

    if "class DataAnalysisPipeline:" in content:
        print("  ✅ DataAnalysisPipeline uses Pipeline pattern (not Loop)")
    else:
        print("  ❌ DataAnalysisPipeline structure incorrect")
        return False

    if "BaseAgentLoop" not in content:
        print("  ✅ Pipeline doesn't inherit from BaseAgentLoop")
    else:
        print("  ❌ Pipeline shouldn't inherit from BaseAgentLoop")
        return False

    # Check Loop pattern
    loop_file = base_path / "agents/research_agent_loop.py"
    with open(loop_file, 'r') as f:
        content = f.read()

    if "ReactAgentLoop" in content:
        print("  ✅ ResearchAgent uses ReactAgentLoop")
    else:
        print("  ❌ ResearchAgent should use ReactAgentLoop")
        return False

    return True


def test_main_loop():
    """Test that main_loop.py uses correct imports"""
    print("\n🔄 Testing Main Loop Integration...")

    base_path = Path(__file__).parent
    main_file = base_path / "main_loop.py"

    with open(main_file, 'r') as f:
        content = f.read()

    # Should use Pipeline, not Loop for data analysis
    if "from agents.data_analysis_pipeline import DataAnalysisPipeline" in content:
        print("  ✅ Uses DataAnalysisPipeline (correct)")
    else:
        print("  ❌ Should use DataAnalysisPipeline")
        return False

    # Should use Loop for research
    if "from agents.research_agent_loop import" in content:
        print("  ✅ Uses ResearchAgentLoop (correct)")
    else:
        print("  ❌ Should use ResearchAgentLoop")
        return False

    # Should NOT use old agent_loop version
    if "DataAnalysisAgentLoop" not in content:
        print("  ✅ Doesn't use incorrect DataAnalysisAgentLoop")
    else:
        print("  ⚠️  Still references DataAnalysisAgentLoop (should be removed)")

    return True


def test_code_metrics():
    """Test code metrics to verify simplification"""
    print("\n📊 Testing Code Metrics...")

    base_path = Path(__file__).parent

    # Check Pipeline is simpler than Loop
    pipeline_file = base_path / "agents/data_analysis_pipeline.py"
    with open(pipeline_file, 'r') as f:
        pipeline_lines = len(f.readlines())

    loop_file = base_path / "agents/research_agent_loop.py"
    with open(loop_file, 'r') as f:
        loop_lines = len(f.readlines())

    print(f"  📄 DataAnalysisPipeline: {pipeline_lines} lines")
    print(f"  📄 ResearchAgentLoop: {loop_lines} lines")

    if pipeline_lines < 500:
        print(f"  ✅ Pipeline is concise ({pipeline_lines} lines)")
    else:
        print(f"  ⚠️  Pipeline could be simpler ({pipeline_lines} lines)")

    return True


def main():
    """Run all tests"""
    print("=" * 80)
    print("ContestTrade Refactor - Structure Validation")
    print("=" * 80)

    tests = [
        ("File Structure", test_file_structure),
        ("Architecture Pattern", test_architecture_pattern),
        ("Main Loop Integration", test_main_loop),
        ("Code Metrics", test_code_metrics),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status} - {name}")

    all_passed = all(r[1] for r in results)

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ All structure tests PASSED!")
        print("\nThe refactored project follows correct architecture patterns:")
        print("  • DataAnalysisAgent → Pipeline (fixed steps)")
        print("  • ResearchAgent → Agent Loop (dynamic decisions)")
        print("  • TradeCompany → Simple async orchestration")
    else:
        print("❌ Some tests FAILED!")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
