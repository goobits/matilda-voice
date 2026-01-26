"""Document caching and performance optimization for large documents."""

import atexit
import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from matilda_voice.document_processing.parser_factory import DocumentParserFactory
from matilda_voice.internal.config import get_config_value
from matilda_voice.internal.types import SemanticElement, SemanticType

logger = logging.getLogger(__name__)

# Pre-compile regex patterns for performance
SECTION_HEADER_PATTERN = re.compile(r"\n\s*#{1,6}\s+.+")
HTML_HEADER_PATTERN = re.compile(r"<h[1-6][^>]*>", re.IGNORECASE)
PARAGRAPH_SPLIT_PATTERN = re.compile(r"\n\s*\n")
MAJOR_PARAGRAPH_BREAK_PATTERN = re.compile(r"\n\s*\n\s*\n")
SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")


def _serialize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively serialize metadata, handling nested SemanticElements."""
    result = {}
    for key, value in metadata.items():
        if isinstance(value, SemanticElement):
            result[key] = _serialize_element(value)
        elif isinstance(value, list):
            result[key] = [_serialize_element(item) if isinstance(item, SemanticElement) else item for item in value]
        elif isinstance(value, dict):
            result[key] = _serialize_metadata(value)
        else:
            result[key] = value
    return result


def _serialize_element(element: SemanticElement) -> Dict[str, Any]:
    """Serialize a SemanticElement to a JSON-compatible dict."""
    return {
        "type": element.type.value,
        "content": element.content,
        "level": element.level,
        "metadata": _serialize_metadata(element.metadata),
    }


def _deserialize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively deserialize metadata, reconstructing nested SemanticElements."""
    result = {}
    for key, value in metadata.items():
        if isinstance(value, dict) and "type" in value and "content" in value:
            # This looks like a serialized SemanticElement
            result[key] = _deserialize_element(value)
        elif isinstance(value, list):
            result[key] = [
                _deserialize_element(item) if isinstance(item, dict) and "type" in item and "content" in item else item
                for item in value
            ]
        elif isinstance(value, dict):
            result[key] = _deserialize_metadata(value)
        else:
            result[key] = value
    return result


def _deserialize_element(data: Dict[str, Any]) -> SemanticElement:
    """Deserialize a dict back to a SemanticElement."""
    return SemanticElement(
        type=SemanticType(data["type"]),
        content=data["content"],
        level=data.get("level"),
        metadata=_deserialize_metadata(data.get("metadata", {})),
    )


class DocumentCache:
    """Cache parsed documents for performance."""

    def __init__(self, cache_dir: str = ".artifacts/cache/documents", max_cache_size_mb: int = 100):
        """Initialize document cache.

        Args:
            cache_dir: Directory to store cache files
            max_cache_size_mb: Maximum cache size in megabytes
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_size = max_cache_size_mb * 1024 * 1024  # Convert to bytes

        # Cache metadata file
        self.metadata_file = self.cache_dir / "cache_metadata.json"
        self.metadata = self._load_metadata()

        # Batched metadata writing
        self._dirty = False
        self._save_timer: Optional[threading.Timer] = None
        self._save_lock = threading.Lock()
        atexit.register(self._flush)

    def get_cache_key(self, content: str, format_hint: str = "") -> str:
        """Generate cache key from content hash and format hint."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        if format_hint:
            return f"{format_hint}_{content_hash}.json"
        else:
            return f"auto_{content_hash}.json"

    def get_cached_elements(self, content: str, format_hint: str = "") -> Optional[List[SemanticElement]]:
        """Retrieve cached parsed elements if available and valid."""
        cache_key = self.get_cache_key(content, format_hint)
        cache_file = self.cache_dir / cache_key

        if not cache_file.exists():
            return None

        try:
            # Check cache age (expire after configured TTL)
            file_age = time.time() - cache_file.stat().st_mtime
            cache_ttl = get_config_value("cache_file_ttl_seconds", 86400)
            if file_age > cache_ttl:
                cache_file.unlink()
                self._remove_from_metadata(cache_key)
                return None

            # Load cached elements
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)

            # Update access time in metadata
            self._update_access_time(cache_key)

            # Deserialize elements from JSON
            elements: List[SemanticElement] = [_deserialize_element(elem_data) for elem_data in cached_data["elements"]]
            return elements

        except (json.JSONDecodeError, KeyError, FileNotFoundError, ValueError):
            # Remove corrupted cache file
            if cache_file.exists():
                cache_file.unlink()
            self._remove_from_metadata(cache_key)
            return None

    def cache_elements(
        self, content: str, elements: List[SemanticElement], format_hint: str = "", processing_time: float = 0.0
    ) -> None:
        """Cache parsed elements for future use."""
        cache_key = self.get_cache_key(content, format_hint)
        cache_file = self.cache_dir / cache_key

        try:
            # Prepare cache data with serialized elements
            cache_data = {
                "elements": [_serialize_element(elem) for elem in elements],
                "content_length": len(content),
                "format_hint": format_hint,
                "processing_time": processing_time,
                "cached_at": time.time(),
            }

            # Write to cache file as JSON
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_data, f)

            # Update metadata
            self._add_to_metadata(cache_key, cache_data)

            # Clean up cache if too large
            self._cleanup_cache_if_needed()

        except (OSError, IOError, TypeError, ValueError) as e:
            # If caching fails, continue without caching (cache is non-critical)
            logger.debug("Cache write failed for %s: %s", cache_key, e)
            if cache_file.exists():
                cache_file.unlink()

    def _load_metadata(self) -> Dict:
        """Load cache metadata from file."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    metadata: Dict[str, Any] = json.load(f)
                    return metadata
            except (OSError, IOError, json.JSONDecodeError, KeyError) as e:
                logger.debug("Failed to load cache metadata: %s", e)
        return {"files": {}, "total_size": 0, "last_cleanup": time.time()}

    def _save_metadata(self) -> None:
        """Save cache metadata to file."""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self.metadata, f, indent=2)
        except (OSError, IOError, TypeError, ValueError) as e:
            logger.debug("Failed to save cache metadata: %s", e)

    def _mark_dirty(self) -> None:
        """Mark metadata as needing save, schedule debounced write."""
        with self._save_lock:
            self._dirty = True
            if self._save_timer is None:
                self._save_timer = threading.Timer(5.0, self._flush)
                self._save_timer.daemon = True
                self._save_timer.start()

    def _flush(self) -> None:
        """Flush pending metadata changes to disk."""
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
                self._save_timer = None
            if self._dirty:
                self._save_metadata()
                self._dirty = False

    def _add_to_metadata(self, cache_key: str, cache_data: Dict) -> None:
        """Add file to metadata tracking."""
        cache_file = self.cache_dir / cache_key
        file_size = cache_file.stat().st_size if cache_file.exists() else 0

        self.metadata["files"][cache_key] = {
            "size": file_size,
            "content_length": cache_data["content_length"],
            "format_hint": cache_data["format_hint"],
            "processing_time": cache_data["processing_time"],
            "cached_at": cache_data["cached_at"],
            "last_accessed": time.time(),
        }

        self.metadata["total_size"] = sum(f["size"] for f in self.metadata["files"].values())
        self._mark_dirty()

    def _remove_from_metadata(self, cache_key: str) -> None:
        """Remove file from metadata tracking."""
        if cache_key in self.metadata["files"]:
            del self.metadata["files"][cache_key]
            self.metadata["total_size"] = sum(f["size"] for f in self.metadata["files"].values())
            self._mark_dirty()

    def _update_access_time(self, cache_key: str) -> None:
        """Update last access time for a cache file."""
        if cache_key in self.metadata["files"]:
            self.metadata["files"][cache_key]["last_accessed"] = time.time()
            self._mark_dirty()

    def _cleanup_cache_if_needed(self) -> None:
        """Clean up cache if it exceeds size limit."""
        if self.metadata["total_size"] <= self.max_cache_size:
            return

        # Sort files by last access time (least recently used first)
        files_by_access = sorted(self.metadata["files"].items(), key=lambda x: x[1]["last_accessed"])

        # Remove oldest files until under size limit
        for cache_key, _ in files_by_access:
            cache_file = self.cache_dir / cache_key
            if cache_file.exists():
                cache_file.unlink()

            self._remove_from_metadata(cache_key)

            if self.metadata["total_size"] <= self.max_cache_size * 0.8:  # Leave some buffer
                break

    def get_cache_stats(self) -> Dict:
        """Get cache statistics."""
        # Flush pending writes so stats reflect current state
        self._flush()
        total_files = len(self.metadata["files"])
        total_size_mb = self.metadata["total_size"] / (1024 * 1024)

        if total_files > 0:
            avg_file_size = self.metadata["total_size"] / total_files
            total_time = sum(f["processing_time"] for f in self.metadata["files"].values())
            avg_processing_time = total_time / total_files

            # Calculate hit rate (approximate based on access patterns)
            recent_window = get_config_value("cache_recent_access_window_seconds", 3600)
            recent_accesses = sum(
                1 for f in self.metadata["files"].values() if time.time() - f["last_accessed"] < recent_window
            )
        else:
            avg_file_size = 0
            avg_processing_time = 0
            recent_accesses = 0

        return {
            "total_files": total_files,
            "total_size_mb": round(total_size_mb, 2),
            "max_size_mb": self.max_cache_size / (1024 * 1024),
            "utilization": round(total_size_mb / (self.max_cache_size / (1024 * 1024)) * 100, 1),
            "avg_file_size_bytes": int(avg_file_size),
            "avg_processing_time_seconds": round(avg_processing_time, 3),
            "recent_accesses": recent_accesses,
        }

    def clear_cache(self) -> None:
        """Clear all cached files."""
        # Clear both .json (new format) and .pkl (legacy format) files
        for cache_file in self.cache_dir.glob("*.json"):
            if cache_file.name != "cache_metadata.json":  # Preserve metadata file
                cache_file.unlink()
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()

        self.metadata = {"files": {}, "total_size": 0, "last_cleanup": time.time()}
        # Flush immediately - destructive operations should persist right away
        self._save_metadata()


class PerformanceOptimizer:
    """Optimize document processing performance."""

    def __init__(self, cache_dir: str = ".artifacts/cache/documents", enable_caching: bool = True):
        """Initialize performance optimizer.

        Args:
            cache_dir: Directory for caching
            enable_caching: Whether to enable caching
        """
        self.enable_caching = enable_caching
        self.cache = DocumentCache(cache_dir) if enable_caching else None
        self.parser_factory = DocumentParserFactory()

        # Performance tracking
        self.processing_stats = {
            "total_processed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_processing_time": 0.0,
            "total_content_length": 0,
        }

    def process_document(
        self, content: str, format_hint: str = "auto", max_chunk_size: int = 5000
    ) -> List[SemanticElement]:
        """Process document with caching and chunking optimization.

        Args:
            content: Document content to process
            format_hint: Format hint for parsing
            max_chunk_size: Maximum size for document chunks

        Returns:
            List of semantic elements
        """
        start_time = time.time()

        # Try cache first
        if self.enable_caching and self.cache:
            cached_elements = self.cache.get_cached_elements(content, format_hint)
            if cached_elements is not None:
                self.processing_stats["cache_hits"] += 1
                self.processing_stats["total_processed"] += 1
                return cached_elements

        # Cache miss - process document
        self.processing_stats["cache_misses"] += 1

        # Choose processing strategy based on content size
        if len(content) <= max_chunk_size:
            elements = self._parse_single_document(content, format_hint)
        else:
            elements = self._parse_large_document(content, format_hint, max_chunk_size)

        processing_time = time.time() - start_time

        # Update stats
        self.processing_stats["total_processed"] += 1
        self.processing_stats["total_processing_time"] += processing_time
        self.processing_stats["total_content_length"] += len(content)

        # Cache results
        if self.enable_caching and self.cache:
            self.cache.cache_elements(content, elements, format_hint, processing_time)

        return elements

    def _parse_single_document(self, content: str, format_hint: str) -> List[SemanticElement]:
        """Parse a single document."""
        return self.parser_factory.parse_document(content, format_hint)

    def _parse_large_document(self, content: str, format_hint: str, max_chunk_size: int) -> List[SemanticElement]:
        """Parse large documents in intelligent chunks."""

        # Try to split by logical boundaries first
        chunks = self._split_document_intelligently(content, max_chunk_size)

        all_elements = []
        current_offset = 0

        for chunk in chunks:
            # Process each chunk
            chunk_elements = self._parse_single_document(chunk, format_hint)

            # Elements don't have start/end attributes, just add them directly
            all_elements.extend(chunk_elements)
            current_offset += len(chunk)

        return all_elements

    def _split_document_intelligently(self, content: str, max_chunk_size: int) -> List[str]:
        """Split document into logical chunks preserving structure."""

        if len(content) <= max_chunk_size:
            return [content]

        chunks = []

        # Try splitting by major sections first (headers, etc.)
        section_boundaries = self._find_section_boundaries(content)

        if section_boundaries:
            current_start = 0
            current_chunk = ""

            for boundary in section_boundaries + [len(content)]:
                section = content[current_start:boundary]

                if len(current_chunk) + len(section) <= max_chunk_size:
                    current_chunk += section
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    current_chunk = section

                current_start = boundary

            if current_chunk:
                chunks.append(current_chunk)

        else:
            # Fallback: split by paragraphs, then by sentences
            chunks = self._split_by_paragraphs(content, max_chunk_size)

        return chunks

    def _find_section_boundaries(self, content: str) -> List[int]:
        """Find natural section boundaries in the document."""
        boundaries = []

        # Look for headers
        for match in SECTION_HEADER_PATTERN.finditer(content):
            boundaries.append(match.start())

        # Look for HTML headers
        for match in HTML_HEADER_PATTERN.finditer(content):
            boundaries.append(match.start())

        # Look for major paragraph breaks
        for match in MAJOR_PARAGRAPH_BREAK_PATTERN.finditer(content):
            boundaries.append(match.start())

        return sorted(set(boundaries))

    def _split_by_paragraphs(self, content: str, max_chunk_size: int) -> List[str]:
        """Split content by paragraphs, then sentences if needed."""
        paragraphs = PARAGRAPH_SPLIT_PATTERN.split(content)
        chunks = []
        current_chunk = ""

        for paragraph in paragraphs:
            if len(current_chunk) + len(paragraph) <= max_chunk_size:
                current_chunk += paragraph + "\n\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # If single paragraph is too large, split by sentences
                if len(paragraph) > max_chunk_size:
                    sentence_chunks = self._split_by_sentences(paragraph, max_chunk_size)
                    chunks.extend(sentence_chunks)
                    current_chunk = ""
                else:
                    current_chunk = paragraph + "\n\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def _split_by_sentences(self, text: str, max_chunk_size: int) -> List[str]:
        """Split text by sentences as a last resort."""
        sentences = SENTENCE_SPLIT_PATTERN.split(text)
        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if len(current_chunk) + len(sentence) <= max_chunk_size:
                current_chunk += sentence + ". "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())

                # If single sentence is still too large, just truncate
                if len(sentence) > max_chunk_size:
                    chunks.append(sentence[:max_chunk_size])
                else:
                    current_chunk = sentence + ". "

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get comprehensive performance statistics."""
        stats: Dict[str, Any] = self.processing_stats.copy()

        # Calculate derived metrics
        if stats["total_processed"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["total_processed"]
            stats["avg_processing_time"] = stats["total_processing_time"] / stats["total_processed"]
            stats["avg_content_length"] = stats["total_content_length"] / stats["total_processed"]

            # Estimate time saved by caching
            if stats["cache_hits"] > 0:
                stats["estimated_time_saved"] = stats["cache_hits"] * stats["avg_processing_time"]
        else:
            stats["cache_hit_rate"] = 0.0
            stats["avg_processing_time"] = 0.0
            stats["avg_content_length"] = 0.0
            stats["estimated_time_saved"] = 0.0

        # Add cache stats if available
        if self.cache:
            cache_stats: Dict[str, Any] = self.cache.get_cache_stats()
            stats["cache_stats"] = cache_stats

        return stats

    def clear_performance_stats(self) -> None:
        """Reset performance statistics."""
        self.processing_stats = {
            "total_processed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_processing_time": 0.0,
            "total_content_length": 0,
        }

    def optimize_cache_size(self, target_hit_rate: float = 0.8) -> Dict:
        """Analyze cache usage and recommend optimal cache size."""
        if not self.cache:
            return {"error": "Caching not enabled"}

        stats = self.get_performance_stats()
        current_hit_rate = stats.get("cache_hit_rate", 0.0)

        recommendations = {
            "current_hit_rate": current_hit_rate,
            "target_hit_rate": target_hit_rate,
            "current_cache_size_mb": stats.get("cache_stats", {}).get("total_size_mb", 0),
            "recommendations": [],
        }

        if current_hit_rate < target_hit_rate:
            # Recommend increasing cache size
            suggested_increase = min(50, int((target_hit_rate - current_hit_rate) * 100))
            recommendations["recommendations"].append(
                f"Consider increasing cache size by {suggested_increase}MB to improve hit rate"
            )
        elif current_hit_rate > target_hit_rate + 0.1:
            # Cache might be oversized
            recommendations["recommendations"].append(
                "Cache hit rate is very high - consider reducing cache size to save disk space"
            )
        else:
            recommendations["recommendations"].append("Cache size appears to be well-tuned")

        return recommendations
