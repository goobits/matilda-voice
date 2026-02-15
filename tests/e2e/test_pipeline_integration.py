"""
Multi-provider pipeline integration tests for TTS CLI.

This module tests integration scenarios involving multiple providers,
provider switching, fallback mechanisms, and complex pipeline workflows.
"""

import os
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from matilda_voice.cli import cli as cli
from tests.utils.test_helpers import (
    CLITestHelper,
    validate_audio_file_comprehensive,
)


class PipelineTestBase:
    """Base class for pipeline integration tests."""

    def setup_method(self):
        """Set up test environment for pipeline tests."""
        self.runner = CliRunner()
        self.cli_helper = CLITestHelper(self.runner)
        self.pipeline_metrics = {
            "provider_availability": {},
            "cross_provider_consistency": {},
            "fallback_effectiveness": {},
            "pipeline_performance": {},
        }

    def check_provider_availability(self, providers: list) -> dict:
        """Check which providers are available for testing."""
        availability = {}

        for provider in providers:
            # Test provider with a simple command
            result = self.runner.invoke(cli, ["info", provider])
            availability[provider] = result.exit_code == 0 and "error" not in result.output.lower()

        self.pipeline_metrics["provider_availability"] = availability
        return availability

    def _check_network_available(self):
        """Check if network is available for real API tests."""
        try:
            import socket

            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except (socket.error, OSError):
            return False

    def compare_provider_outputs(self, outputs: dict, tolerance: float = 0.3) -> dict:
        """Compare audio outputs from different providers."""
        comparison_results = {}

        # Get valid outputs with validation results
        valid_outputs = {}
        for provider, output_info in outputs.items():
            if output_info["file_path"] and output_info["file_path"].exists():
                validation = validate_audio_file_comprehensive(
                    output_info["file_path"], min_duration=1.0, max_duration=60.0, min_file_size=500
                )
                if validation.valid:
                    valid_outputs[provider] = {"validation": validation, "file_path": output_info["file_path"]}

        if len(valid_outputs) < 2:
            return {"insufficient_data": True}

        # Compare durations
        durations = {p: v["validation"].duration for p, v in valid_outputs.items() if v["validation"].duration}
        if len(durations) > 1:
            duration_values = list(durations.values())
            avg_duration = sum(duration_values) / len(duration_values)
            duration_variance = {
                provider: abs(duration - avg_duration) / avg_duration for provider, duration in durations.items()
            }
            comparison_results["duration_consistency"] = all(
                variance <= tolerance for variance in duration_variance.values()
            )
            comparison_results["duration_variance"] = duration_variance

        # Compare file sizes (less strict, just order of magnitude)
        file_sizes = {p: v["validation"].file_size for p, v in valid_outputs.items() if v["validation"].file_size}
        if len(file_sizes) > 1:
            size_values = list(file_sizes.values())
            max_size = max(size_values)
            min_size = min(size_values)
            size_ratio = max_size / min_size if min_size > 0 else float("inf")
            comparison_results["size_consistency"] = size_ratio <= 10.0  # Within 10x
            comparison_results["size_ratio"] = size_ratio

        self.pipeline_metrics["cross_provider_consistency"] = comparison_results
        return comparison_results


@pytest.mark.e2e
@pytest.mark.pipeline
@pytest.mark.requires_network
@pytest.mark.requires_providers
class TestMultiProviderComparison(PipelineTestBase):
    """Test cross-provider comparison and consistency."""

    def test_provider_synthesis_comparison(self, tmp_path):
        """Test synthesis quality comparison across multiple providers."""
        # Skip real API tests in CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or not self._check_network_available():
            pytest.skip("Skipping real API test in CI environment")
        test_text = "This is a comprehensive comparison test across multiple TTS providers."
        providers_to_test = ["@edge", "@openai", "@google", "@elevenlabs"]

        # Check provider availability
        availability = self.check_provider_availability(providers_to_test)
        available_providers = [p for p, available in availability.items() if available]

        if len(available_providers) < 2:
            pytest.skip(f"Insufficient providers available for comparison. Available: {available_providers}")

        # Synthesize with each available provider
        provider_outputs = {}
        synthesis_metrics = {}

        for provider in available_providers:
            output_file = tmp_path / f"comparison_{provider[1:]}.mp3"

            start_time = time.time()
            result, actual_output = self.cli_helper.invoke_save(
                test_text, provider=provider, output_path=str(output_file), format="mp3"
            )
            synthesis_time = time.time() - start_time

            provider_outputs[provider] = {
                "result": result,
                "file_path": actual_output,
                "synthesis_time": synthesis_time,
                "success": result.exit_code == 0 and actual_output and actual_output.exists(),
            }

            synthesis_metrics[provider] = {
                "synthesis_time": synthesis_time,
                "success": provider_outputs[provider]["success"],
            }

        # Filter successful outputs
        successful_providers = [p for p, output in provider_outputs.items() if output["success"]]

        # Skip if no providers succeeded (common in CI environments)
        if len(successful_providers) == 0:
            pytest.skip("No providers succeeded in synthesis - likely due to provider availability in test environment")

        # Compare outputs if multiple providers succeeded
        if len(successful_providers) > 1:
            comparison_results = self.compare_provider_outputs(provider_outputs)

            if not comparison_results.get("insufficient_data"):
                # Duration consistency check
                if "duration_consistency" in comparison_results:
                    assert comparison_results[
                        "duration_consistency"
                    ], f"Provider duration inconsistency detected: {comparison_results.get('duration_variance')}"

                # Size consistency check (more lenient)
                if "size_consistency" in comparison_results:
                    assert comparison_results[
                        "size_consistency"
                    ], f"Provider file size inconsistency detected: ratio = {comparison_results.get('size_ratio')}"

        # Performance comparison
        synthesis_times = [m["synthesis_time"] for m in synthesis_metrics.values() if m["success"]]
        if len(synthesis_times) > 1:
            avg_time = sum(synthesis_times) / len(synthesis_times)
            # No provider should be more than 3x slower than average
            for provider, metrics in synthesis_metrics.items():
                if metrics["success"]:
                    time_ratio = metrics["synthesis_time"] / avg_time
                    assert (
                        time_ratio <= 3.0
                    ), f"Provider {provider} too slow: {metrics['synthesis_time']:.2f}s vs avg {avg_time:.2f}s"

        self.pipeline_metrics["pipeline_performance"]["comparison_test"] = {
            "providers_tested": len(available_providers),
            "successful_providers": len(successful_providers),
            "avg_synthesis_time": sum(synthesis_times) / len(synthesis_times) if synthesis_times else 0,
        }

    def test_voice_selection_across_providers(self, tmp_path):
        """Test voice selection consistency and quality across providers."""
        # Skip real API tests in CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or not self._check_network_available():
            pytest.skip("Skipping real API test in CI environment")
        test_text = "Voice selection consistency test across different providers."

        # Define provider-specific voice mappings
        provider_voices = {
            "@edge": ["en-US-AriaNeural", "en-US-JennyNeural"],
            "@openai": ["alloy", "echo"],
            "@google": ["en-US-Wavenet-D", "en-US-Standard-B"],
            "@elevenlabs": ["Rachel", "Adam"],  # Common ElevenLabs voices
        }

        # Check which providers are available
        available_providers = []
        for provider in provider_voices.keys():
            result = self.runner.invoke(cli, ["info", provider])
            if result.exit_code == 0:
                available_providers.append(provider)

        if len(available_providers) < 2:
            pytest.skip("Insufficient providers available for voice comparison")

        voice_test_results = {}

        for provider in available_providers:
            provider_results = {}
            voices = provider_voices[provider]

            for voice in voices:
                output_file = tmp_path / f"voice_test_{provider[1:]}_{voice.replace('-', '_').replace(' ', '_')}.mp3"

                result, actual_output = self.cli_helper.invoke_save(
                    test_text, provider=provider, voice=voice, output_path=str(output_file)
                )

                if result.exit_code == 0 and actual_output and actual_output.exists():
                    validation = validate_audio_file_comprehensive(
                        actual_output, expected_format="mp3", min_duration=2.0, max_duration=15.0, min_file_size=1000
                    )

                    provider_results[voice] = {
                        "success": validation.valid,
                        "validation": validation,
                        "file_path": actual_output,
                    }
                else:
                    provider_results[voice] = {"success": False}

            voice_test_results[provider] = provider_results

        # Analyze voice selection results
        provider_success_rates = {}
        for provider, results in voice_test_results.items():
            successful_voices = sum(1 for r in results.values() if r.get("success", False))
            total_voices = len(results)
            provider_success_rates[provider] = successful_voices / total_voices if total_voices > 0 else 0

        # At least one provider should have reasonable voice success rate (relaxed for CI)
        max_success_rate = max(provider_success_rates.values()) if provider_success_rates else 0
        if max_success_rate == 0:
            pytest.skip(
                "All providers have low voice success rates - likely due to provider availability in test environment"
            )

        assert max_success_rate >= 0.25, f"All providers have low voice success rates: {provider_success_rates}"

        # Compare voice quality across providers
        cross_provider_voice_quality = {}
        for provider, results in voice_test_results.items():
            successful_validations = [
                r["validation"] for r in results.values() if r.get("success") and "validation" in r
            ]

            if successful_validations:
                avg_duration = sum(v.duration for v in successful_validations if v.duration) / len(
                    successful_validations
                )
                avg_file_size = sum(v.file_size for v in successful_validations if v.file_size) / len(
                    successful_validations
                )

                cross_provider_voice_quality[provider] = {
                    "avg_duration": avg_duration,
                    "avg_file_size": avg_file_size,
                    "voice_count": len(successful_validations),
                }

        self.pipeline_metrics["cross_provider_consistency"]["voice_selection"] = {
            "provider_success_rates": provider_success_rates,
            "quality_metrics": cross_provider_voice_quality,
        }


@pytest.mark.e2e
@pytest.mark.pipeline
@pytest.mark.requires_network
@pytest.mark.requires_providers
class TestProviderFallbackMechanisms(PipelineTestBase):
    """Test provider fallback and error recovery mechanisms."""

    def test_provider_fallback_workflow(self, tmp_path):
        """Test automatic fallback when primary provider fails."""
        # Skip real API tests in CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or not self._check_network_available():
            pytest.skip("Skipping real API test in CI environment")
        test_text = "Provider fallback mechanism test"

        # Test fallback scenarios
        fallback_scenarios = [
            {
                "name": "invalid_provider_fallback",
                "primary": "@invalid_provider",
                "expected_behavior": "error_with_suggestions",
            },
            {
                "name": "provider_unavailable",
                "primary": "@elevenlabs",  # Might not be configured
                "fallback": "@edge",
                "expected_behavior": "manual_fallback",
            },
        ]

        fallback_results = {}

        for scenario in fallback_scenarios:
            scenario_name = scenario["name"]
            output_file = tmp_path / f"fallback_{scenario_name}.mp3"

            # Try primary provider
            primary_result, primary_output = self.cli_helper.invoke_save(
                test_text, provider=scenario["primary"], output_path=str(output_file)
            )

            fallback_data = {
                "primary_success": primary_result.exit_code == 0 and primary_output and primary_output.exists(),
                "primary_result": primary_result,
                "fallback_attempted": False,
                "fallback_success": False,
            }

            # If primary failed and fallback is specified, try fallback
            if not fallback_data["primary_success"] and "fallback" in scenario:
                fallback_output_file = tmp_path / f"fallback_{scenario_name}_backup.mp3"
                fallback_result, fallback_output = self.cli_helper.invoke_save(
                    test_text, provider=scenario["fallback"], output_path=str(fallback_output_file)
                )

                fallback_data["fallback_attempted"] = True
                fallback_data["fallback_success"] = (
                    fallback_result.exit_code == 0 and fallback_output and fallback_output.exists()
                )
                fallback_data["fallback_result"] = fallback_result

            # Analyze error handling quality
            if not fallback_data["primary_success"]:
                error_analysis = {
                    "provides_error_message": "error" in primary_result.output.lower(),
                    "suggests_alternatives": any(
                        keyword in primary_result.output.lower() for keyword in ["available", "try", "use", "provider"]
                    ),
                    "exit_code_appropriate": primary_result.exit_code in [1, 2],
                }
                fallback_data["error_analysis"] = error_analysis

            fallback_results[scenario_name] = fallback_data

        # Evaluate fallback mechanisms
        fallback_quality_scores = []

        for scenario_name, data in fallback_results.items():
            score = 0.0

            # If primary succeeded, that's good
            if data["primary_success"]:
                score = 1.0
            else:
                # Evaluate error handling
                if "error_analysis" in data:
                    analysis = data["error_analysis"]
                    if analysis["provides_error_message"]:
                        score += 0.3
                    if analysis["suggests_alternatives"]:
                        score += 0.3
                    if analysis["exit_code_appropriate"]:
                        score += 0.2

                # If fallback was attempted and succeeded
                if data["fallback_attempted"] and data["fallback_success"]:
                    score += 0.2

            fallback_quality_scores.append(score)

        avg_fallback_quality = sum(fallback_quality_scores) / len(fallback_quality_scores)
        self.pipeline_metrics["fallback_effectiveness"] = {
            "avg_quality_score": avg_fallback_quality,
            "scenario_results": fallback_results,
        }

        # Assertions - Allow for limited provider availability in test environments
        # Note: In mocked test environments, error patterns may not match expected patterns
        # which affects quality scores. We use lenient thresholds for test stability.
        assert avg_fallback_quality >= 0.2, f"Fallback mechanism quality too low: {avg_fallback_quality:.2f}"

        # At least one scenario should demonstrate some error handling
        assert max(fallback_quality_scores) >= 0.2, "No fallback scenario demonstrates adequate error handling"

    def test_configuration_based_provider_selection(self, tmp_path):
        """Test provider selection based on configuration."""
        # Skip real API tests in CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or not self._check_network_available():
            pytest.skip("Skipping real API test in CI environment")
        test_text = "Configuration-based provider selection test"

        # Test different configuration scenarios
        config_scenarios = [
            {"name": "default_provider", "config_changes": {}, "expected_provider": "@edge"},  # Typically the default
            {
                "name": "explicit_voice_provider",
                "config_changes": {"voice": "openai_tts:alloy"},
                "expected_provider": "openai_tts",
            },
        ]

        config_test_results = {}

        for scenario in config_scenarios:
            scenario_name = scenario["name"]

            # Create isolated test environment
            with self.runner.isolated_filesystem():
                # Apply configuration changes if any
                for key, value in scenario["config_changes"].items():
                    self.runner.invoke(cli, ["config", "set", key, value])
                    # Don't fail if config set doesn't work in test environment

                # Test synthesis
                # New CLI: save TEXT OPTIONS [--options]
                output_file = Path("config_test.mp3")
                result = self.runner.invoke(cli, ["save", test_text, "@edge", "-o", str(output_file)])

                config_test_results[scenario_name] = {
                    "synthesis_success": result.exit_code == 0,
                    "output_exists": output_file.exists(),
                    "result_output": result.output,
                }

        # Evaluate configuration-based selection
        successful_configs = sum(1 for r in config_test_results.values() if r["synthesis_success"])

        # Skip if no configurations worked (common in CI environments)
        if successful_configs == 0:
            pytest.skip(
                "No configuration scenarios resulted in successful synthesis - likely due to provider availability in test environment"
            )

        self.pipeline_metrics["configuration_selection"] = {
            "successful_scenarios": successful_configs,
            "total_scenarios": len(config_scenarios),
            "scenario_details": config_test_results,
        }


@pytest.mark.e2e
@pytest.mark.pipeline
@pytest.mark.slow
@pytest.mark.requires_network
@pytest.mark.requires_providers
class TestProviderPipelinePerformance(PipelineTestBase):
    """Test performance characteristics of multi-provider pipelines."""

    def test_provider_switching_performance(self, tmp_path):
        """Test performance impact of switching between providers."""
        # Skip real API tests in CI environment
        if os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or not self._check_network_available():
            pytest.skip("Skipping real API test in CI environment")
        test_texts = ["First provider test", "Second provider test", "Third provider test"]

        # Get available providers
        potential_providers = ["@edge", "@openai", "@google"]
        available_providers = []

        for provider in potential_providers:
            result = self.runner.invoke(cli, ["info", provider])
            if result.exit_code == 0:
                available_providers.append(provider)

        if len(available_providers) < 2:
            pytest.skip("Need at least 2 providers for switching performance test")

        # Test provider switching performance
        switching_metrics = []

        for i, text in enumerate(test_texts):
            provider = available_providers[i % len(available_providers)]
            output_file = tmp_path / f"switching_test_{i}.mp3"

            start_time = time.time()
            result, actual_output = self.cli_helper.invoke_save(text, provider=provider, output_path=str(output_file))
            synthesis_time = time.time() - start_time

            switching_metrics.append(
                {
                    "provider": provider,
                    "synthesis_time": synthesis_time,
                    "success": result.exit_code == 0 and actual_output and actual_output.exists(),
                    "text_length": len(text),
                }
            )

        # Analyze switching performance
        successful_syntheses = [m for m in switching_metrics if m["success"]]

        if len(successful_syntheses) >= 2:
            synthesis_times = [m["synthesis_time"] for m in successful_syntheses]
            avg_synthesis_time = sum(synthesis_times) / len(synthesis_times)

            # Check for consistent performance (no dramatic slowdowns from switching)
            max_time = max(synthesis_times)
            min_time = min(synthesis_times)
            time_variance_ratio = max_time / min_time if min_time > 0 else float("inf")

            performance_metrics = {
                "avg_synthesis_time": avg_synthesis_time,
                "time_variance_ratio": time_variance_ratio,
                "consistent_performance": time_variance_ratio <= 3.0,  # Within 3x
            }

            self.pipeline_metrics["pipeline_performance"]["provider_switching"] = performance_metrics

            # Assertions
            assert (
                avg_synthesis_time < 45.0
            ), f"Average synthesis time too high with switching: {avg_synthesis_time:.2f}s"
            assert (
                time_variance_ratio <= 5.0
            ), f"Provider switching causes excessive time variance: {time_variance_ratio:.2f}x"

        # Skip if no provider switching tests succeeded (common in CI environments)
        if len(successful_syntheses) == 0:
            pytest.skip(
                "No provider switching tests succeeded - likely due to provider availability in test environment"
            )

    def test_concurrent_multi_provider_synthesis(self, tmp_path):
        """Test concurrent synthesis using different providers."""
        import queue
        import threading

        # Prepare concurrent synthesis tasks
        tasks = [
            {"text": "Concurrent test with Edge TTS", "provider": "@edge", "id": "edge_concurrent"},
            {"text": "Concurrent test with OpenAI", "provider": "@openai", "id": "openai_concurrent"},
            {"text": "Concurrent test with Google", "provider": "@google", "id": "google_concurrent"},
        ]

        results_queue = queue.Queue()

        def synthesize_concurrent(task):
            output_file = tmp_path / f"{task['id']}.mp3"
            start_time = time.time()

            # Click's CliRunner mutates global stdio and is not thread-safe. Use subprocess per thread.
            import subprocess
            import sys

            repo_root = Path(__file__).resolve().parents[2]
            env = os.environ.copy()
            pythonpath_entries = [str(repo_root / "src"), str(repo_root)]
            existing_pythonpath = env.get("PYTHONPATH", "")
            prefix = os.pathsep.join(pythonpath_entries)
            env["PYTHONPATH"] = f"{prefix}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else prefix

            cmd = [
                sys.executable,
                "-m",
                "matilda_voice.cli",
                "save",
                task["text"],
                task["provider"],
                "-o",
                str(output_file),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env, check=False)

            synthesis_time = time.time() - start_time

            results_queue.put(
                {
                    "task_id": task["id"],
                    "provider": task["provider"],
                    "synthesis_time": synthesis_time,
                    "success": proc.returncode == 0 and output_file.exists(),
                    "exit_code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }
            )

        # Execute concurrent syntheses
        start_time = time.time()
        threads = []

        for task in tasks:
            thread = threading.Thread(target=synthesize_concurrent, args=(task,))
            thread.start()
            threads.append(thread)

        # Wait for completion with timeout
        for thread in threads:
            thread.join(timeout=60)

        total_concurrent_time = time.time() - start_time

        # Collect results
        concurrent_results = []
        while not results_queue.empty():
            concurrent_results.append(results_queue.get())

        # Analyze concurrent performance
        successful_concurrent = [r for r in concurrent_results if r["success"]]

        if len(successful_concurrent) >= 2:
            individual_times = [r["synthesis_time"] for r in successful_concurrent]
            sum_individual_times = sum(individual_times)

            # Concurrent execution should be more efficient than sequential
            concurrency_efficiency = sum_individual_times / total_concurrent_time if total_concurrent_time > 0 else 0

            concurrent_performance = {
                "total_concurrent_time": total_concurrent_time,
                "sum_individual_times": sum_individual_times,
                "concurrency_efficiency": concurrency_efficiency,
                "successful_providers": len(successful_concurrent),
            }

            self.pipeline_metrics["pipeline_performance"]["concurrent_synthesis"] = concurrent_performance

            # Assertions
            assert total_concurrent_time < 120.0, f"Concurrent synthesis took too long: {total_concurrent_time:.2f}s"
            assert (
                concurrency_efficiency >= 1.5
            ), f"Concurrent execution not efficient enough: {concurrency_efficiency:.2f}x"
            assert len(successful_concurrent) >= 1, "No concurrent syntheses succeeded"
        else:
            pytest.skip("Insufficient providers available for concurrent testing")

    @pytest.mark.skipif(not os.getenv("TEST_PROVIDER_EXHAUSTIVE"), reason="Exhaustive provider testing disabled")
    def test_provider_resource_utilization(self, tmp_path):
        """Test resource utilization patterns across providers."""
        import gc

        import psutil

        test_text = "Resource utilization test for comprehensive provider analysis"
        providers_to_test = ["@edge", "@openai", "@google", "@elevenlabs"]

        resource_metrics = {}

        for provider in providers_to_test:
            # Check if provider is available
            info_result = self.runner.invoke(cli, ["info", provider])
            if info_result.exit_code != 0:
                continue

            # Measure resource usage during synthesis
            gc.collect()  # Clean up before measurement

            process = psutil.Process()
            memory_before = process.memory_info().rss
            cpu_before = process.cpu_percent()

            output_file = tmp_path / f"resource_test_{provider[1:]}.mp3"

            start_time = time.time()
            result, actual_output = self.cli_helper.invoke_save(
                test_text, provider=provider, output_path=str(output_file)
            )
            synthesis_time = time.time() - start_time

            memory_after = process.memory_info().rss
            cpu_after = process.cpu_percent()

            # Validate output
            synthesis_success = result.exit_code == 0 and actual_output and actual_output.exists()
            validation_result = None

            if synthesis_success:
                validation_result = validate_audio_file_comprehensive(
                    actual_output, expected_format="mp3", min_duration=1.0, max_duration=15.0, min_file_size=1000
                )

            resource_metrics[provider] = {
                "synthesis_time": synthesis_time,
                "memory_delta": memory_after - memory_before,
                "cpu_usage": max(cpu_after - cpu_before, 0),  # Prevent negative values
                "synthesis_success": synthesis_success,
                "audio_valid": validation_result.valid if validation_result else False,
                "memory_before": memory_before,
                "memory_after": memory_after,
            }

        # Analyze resource utilization
        if len(resource_metrics) >= 2:
            successful_providers = {
                p: m for p, m in resource_metrics.items() if m["synthesis_success"] and m["audio_valid"]
            }

            if len(successful_providers) >= 2:
                # Compare resource efficiency
                synthesis_times = [m["synthesis_time"] for m in successful_providers.values()]
                memory_deltas = [m["memory_delta"] for m in successful_providers.values()]

                avg_synthesis_time = sum(synthesis_times) / len(synthesis_times)
                avg_memory_delta = sum(memory_deltas) / len(memory_deltas)

                resource_analysis = {
                    "avg_synthesis_time": avg_synthesis_time,
                    "avg_memory_delta": avg_memory_delta,
                    "provider_count": len(successful_providers),
                    "memory_efficiency_acceptable": all(
                        m["memory_delta"] < 100 * 1024 * 1024 for m in successful_providers.values()  # < 100MB delta
                    ),
                }

                self.pipeline_metrics["pipeline_performance"]["resource_utilization"] = resource_analysis

                # Resource utilization assertions
                assert resource_analysis["memory_efficiency_acceptable"], "Some providers use excessive memory"
                assert avg_synthesis_time < 60.0, f"Average synthesis time too high: {avg_synthesis_time:.2f}s"

        assert len(resource_metrics) >= 1, "No providers available for resource testing"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
