import time
import pytest
from typing import List
from matilda_voice.document_processing.performance_cache import PerformanceOptimizer

# Define the unoptimized method (simulating the "before" state) for comparison
def _split_by_paragraphs_unoptimized(self, content: str, max_chunk_size: int) -> List[str]:
    """Split content by paragraphs, then sentences if needed."""
    import re
    # Unoptimized: re.split called directly
    paragraphs = re.split(r"\n\s*\n", content)

    chunks = []
    current_chunk_parts: List[str] = []
    current_chunk_len = 0

    for paragraph in paragraphs:
        added_len = len(paragraph) + (2 if current_chunk_parts else 0)

        if current_chunk_len + added_len <= max_chunk_size:
            current_chunk_parts.append(paragraph)
            current_chunk_len += added_len
        else:
            if current_chunk_parts:
                chunks.append("\n\n".join(current_chunk_parts))

            current_chunk_parts = []
            current_chunk_len = 0

            if len(paragraph) > max_chunk_size:
                sentence_chunks = self._split_by_sentences(paragraph, max_chunk_size)
                chunks.extend(sentence_chunks)
            else:
                current_chunk_parts.append(paragraph)
                current_chunk_len = len(paragraph)

    if current_chunk_parts:
        chunks.append("\n\n".join(current_chunk_parts))

    return chunks

class TestPerformance:
    @pytest.mark.benchmark
    def test_paragraph_split_performance(self, tmp_path):
        """Verify that the optimized paragraph splitting is efficient."""
        cache_dir = tmp_path / "cache"
        optimizer = PerformanceOptimizer(cache_dir=str(cache_dir), enable_caching=False)

        # Generate content
        paragraph = "This is a paragraph with some reasonable length to simulate actual content. " * 5
        num_paragraphs = 100
        content = "\n\n".join([paragraph] * num_paragraphs)

        iterations = 100

        # Measure Optimized (Current)
        start_time = time.time()
        for _ in range(iterations):
            optimizer._split_by_paragraphs(content, 5000)
        optimized_time = time.time() - start_time

        # Measure Unoptimized
        original_method = PerformanceOptimizer._split_by_paragraphs
        PerformanceOptimizer._split_by_paragraphs = _split_by_paragraphs_unoptimized

        try:
            start_time = time.time()
            for _ in range(iterations):
                optimizer._split_by_paragraphs(content, 5000)
            unoptimized_time = time.time() - start_time
        finally:
            PerformanceOptimizer._split_by_paragraphs = original_method

        print(f"\nOptimized: {optimized_time:.4f}s, Unoptimized: {unoptimized_time:.4f}s")

        # Ensure optimized version is not significantly slower (allow some variance)
        assert optimized_time <= unoptimized_time * 1.1, "Optimized version significantly slower than unoptimized!"
