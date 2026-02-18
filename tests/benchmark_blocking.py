import asyncio
import os
import sys
import time
import wave

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from matilda_voice.internal.audio_utils import get_audio_duration, get_audio_duration_async


async def ticker():
    """Prints a tick every 0.1s to show loop activity."""
    try:
        while True:
            await asyncio.sleep(0.1)
            print(".", end="", flush=True)
    except asyncio.CancelledError:
        pass


async def run_benchmark():
    test_file = "benchmark_test.wav"

    # Create a VALID wav file of 10 seconds
    with wave.open(test_file, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(b"\x00\x00" * 44100 * 10)  # 10 seconds

    print("\n--- Benchmark Start (WAV Optimization) ---")

    # 1. Test get_audio_duration (now Async) with WAV optimization
    print("\nTesting get_audio_duration (Async) (should be instant and yield 10.0):")
    ticker_task = asyncio.create_task(ticker())

    start_time = time.time()

    # Run loop
    for _ in range(100):
        duration = await get_audio_duration(test_file)
        if duration != 10.0:
            print(f"Error: expected 10.0, got {duration}")
            break

    total_time = time.time() - start_time

    ticker_task.cancel()
    await asyncio.sleep(0.1)
    print(f"\nget_audio_duration calls (100x) took {total_time:.4f}s (Avg: {total_time/100*1000:.4f}ms)")

    # 2. Test get_audio_duration_async (Alias) with WAV optimization
    print("\nTesting get_audio_duration_async (Alias) (should be instant and yield 10.0):")
    ticker_task = asyncio.create_task(ticker())

    start_time = time.time()

    for _ in range(100):
        duration = await get_audio_duration_async(test_file)
        if duration != 10.0:
            print(f"Error: expected 10.0, got {duration}")
            break

    total_time = time.time() - start_time

    ticker_task.cancel()
    await asyncio.sleep(0.1)
    print(f"\nAlias calls (100x) took {total_time:.4f}s (Avg: {total_time/100*1000:.4f}ms)")

    # Clean up
    if os.path.exists(test_file):
        os.remove(test_file)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
