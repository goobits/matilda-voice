"""Mixed content processor integrating document parsing with text formatting."""

import re
from collections import defaultdict
from typing import Any, Dict, List

from matilda_voice.document_processing.parser_factory import DocumentParserFactory
from matilda_voice.internal.types import SemanticElement

# TextFormatter removed - not needed for document processing

# Compiled regex patterns for performance
RE_SENTENCE_SPLIT = re.compile(r"[.!?]+")
RE_HTML_LINK = re.compile(r"<a\s+href")
RE_ANY_HTML_TAG = re.compile(r"<[^>]+>")
RE_MD_HEADER = re.compile(r"#{1,6}\s+")
RE_SPEECH_ARTIFACTS = re.compile(r"\b(?:um|uh|ah|er)\b", re.IGNORECASE)


class MixedContentProcessor:
    """Process mixed content: documents + transcribed text."""

    def __init__(self, language: str = "en"):
        """Initialize with text formatting and document parsing components."""
        self.language = language

        # Import document parsing
        self.document_factory = DocumentParserFactory()

        # Combined single-pass pattern for document indicators (named groups)
        # Each match increments the corresponding indicator count
        self._doc_pattern = re.compile(
            r"(?P<html_tag><[a-zA-Z][^>]*>)"
            r"|(?P<md_header>^#{1,6}\s)"
            r"|(?P<code_block>```)"
            r"|(?P<md_link>\[[^\]]*\]\([^)]*\))"
            r"|(?P<list_item>^\s*[-*+]\s)"
            r"|(?P<num_list>^\s*\d+\.\s)"
            r"|(?P<json_struct>\"[^\"]*\":\s*[{\[])"
            r"|(?P<json_start>{\s*\"[^\"]*\")",
            re.MULTILINE | re.IGNORECASE,
        )

        # Combined single-pass pattern for transcription indicators
        self._trans_pattern = re.compile(
            r"(?P<filler>\b(?:um|uh|ah|er|mm)\b)"
            r"|(?P<speech_pattern>\b(?:like|you know|I mean)\b)"
            r"|(?P<contraction>\b(?:gonna|wanna|gotta)\b)"
            r"|(?P<pause>\.{2,})"
            r"|(?P<uncertainty>\?\s*\?)",
            re.MULTILINE | re.IGNORECASE,
        )

        # Additional heuristic patterns (single-pass combined)
        self._extra_doc_pattern = re.compile(
            r"(?P<struct_header>(?:^|\n)#{1,6}\s+\w+)"
            r"|(?P<html_struct><(?:html|head|body|div|p|h[1-6]))"
            r"|(?P<code_pre>```[\s\S]*?```|<pre>[\s\S]*?</pre>)",
            re.MULTILINE | re.IGNORECASE,
        )

        self._extra_trans_pattern = re.compile(
            r"(?P<think>\bi\s+(?:think|believe|feel|want|need)\b)"
            r"|(?P<you_know>\byou\s+(?:know|see|think)\b)"
            r"|(?P<lets>\blet's\s+\w+)"
            r"|(?P<what_do>\bwhat\s+do\s+you\b)"
            r"|(?P<spoken_num>\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\b)",
            re.MULTILINE | re.IGNORECASE,
        )

    def process_mixed_content(self, content: str, content_type: str = "auto", format_hint: str = "") -> str:
        """Process content that might be document OR transcribed speech.

        Args:
            content: Text content to process
            content_type: "auto", "transcription", or "document"
            format_hint: Optional format hint (html, markdown, json)

        Returns:
            Processed text ready for speech synthesis
        """
        if not content or not content.strip():
            return ""

        # Auto-detect content type if not specified
        if content_type == "auto":
            content_type = self._detect_content_type(content, format_hint)

        if content_type == "transcription":
            # Use existing text formatting pipeline
            return self._process_transcription(content)

        elif content_type == "document":
            # Use document parsing pipeline
            return self._process_document(content, format_hint)

        else:
            # Fallback: try document first, then transcription
            try:
                elements = self.document_factory.parse_document(content, format_hint)
                if elements and len(elements) > 0:
                    return self._format_for_speech(elements)
            except Exception:
                pass

            # Fallback to transcription processing
            return self._process_transcription(content)

    def _detect_content_type(self, content: str, format_hint: str = "") -> str:
        """Heuristics to distinguish documents from transcriptions.

        Uses single-pass regex scanning for performance.
        """
        # If we have a format hint, prefer document processing
        if format_hint and format_hint in ["html", "markdown", "json"]:
            return "document"

        # Single-pass document indicator scan
        doc_score = 0
        for match in self._doc_pattern.finditer(content):
            # Each named group match counts as 1
            doc_score += 1

        # Single-pass transcription indicator scan
        trans_score = 0
        for match in self._trans_pattern.finditer(content):
            trans_score += 1

        # Single-pass additional heuristics scan
        extra_weights = {"struct_header": 3, "html_struct": 5, "code_pre": 2}
        for match in self._extra_doc_pattern.finditer(content):
            for name, val in match.groupdict().items():
                if val:
                    doc_score += extra_weights.get(name, 1)

        for match in self._extra_trans_pattern.finditer(content):
            trans_score += 1

        # JSON structure bonus (quick check, not regex)
        stripped = content.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            doc_score += 4

        # Incomplete sentences heuristic (common in speech)
        sentences = RE_SENTENCE_SPLIT.split(content)
        short_sentences = sum(1 for s in sentences if len(s.split()) <= 3 and len(s.strip()) > 0)
        if short_sentences >= 2:
            trans_score += short_sentences

        # Decision logic
        if doc_score > trans_score * 1.5:  # Bias slightly toward document detection
            return "document"
        elif trans_score > doc_score:
            return "transcription"
        else:
            # When in doubt, try document parsing first (it's more structured)
            return "document"

    def _process_transcription(self, content: str) -> str:
        """Process content as transcribed speech."""
        # For document-focused TTS, we simply return the content
        # The original TextFormatter was part of STT functionality
        return content.strip()

    def _process_document(self, content: str, format_hint: str = "") -> str:
        """Process content as a document using document parsers."""
        try:
            elements = self.document_factory.parse_document(content, format_hint)
            return self._format_for_speech(elements)
        except Exception:
            # If document parsing fails, fall back to transcription processing
            return self._process_transcription(content)

    def _format_for_speech(self, elements: List[SemanticElement]) -> str:
        """Format semantic elements for natural speech output."""
        if not elements:
            return ""

        # Import speech synthesis components
        from matilda_voice.speech_synthesis.speech_markdown import SpeechMarkdownConverter

        # Convert to speech markdown
        converter = SpeechMarkdownConverter()
        speech_markdown = converter.convert_elements(elements)

        return speech_markdown

    def get_content_analysis(self, content: str, format_hint: str = "") -> Dict:
        """Analyze content and return detailed classification information."""
        content_type = self._detect_content_type(content, format_hint)

        # Count indicators using single-pass patterns
        doc_indicators = len(list(self._doc_pattern.finditer(content)))
        trans_indicators = len(list(self._trans_pattern.finditer(content)))

        # Word and sentence statistics
        words = len(content.split())
        sentences = len(RE_SENTENCE_SPLIT.split(content))
        avg_sentence_length = words / max(sentences, 1)

        # Structure analysis using single-pass scanning
        structure_matches = defaultdict(bool)
        for match in self._extra_doc_pattern.finditer(content):
            for name, val in match.groupdict().items():
                if val:
                    structure_matches[name] = True

        # Check main doc pattern for lists and links
        for match in self._doc_pattern.finditer(content):
            for name, val in match.groupdict().items():
                if val:
                    structure_matches[name] = True

        has_headers = (
            structure_matches.get("struct_header", False)
            or structure_matches.get("html_struct", False)
            or structure_matches.get("md_header", False)
        )
        has_code = structure_matches.get("code_pre", False) or structure_matches.get("code_block", False)
        has_lists = structure_matches.get("list_item", False) or structure_matches.get("num_list", False)
        has_links = structure_matches.get("md_link", False) or bool(RE_HTML_LINK.search(content))

        return {
            "detected_type": content_type,
            "confidence": self._calculate_confidence(doc_indicators, trans_indicators),
            "statistics": {
                "word_count": words,
                "sentence_count": sentences,
                "avg_sentence_length": round(avg_sentence_length, 1),
                "document_indicators": doc_indicators,
                "transcription_indicators": trans_indicators,
            },
            "structure": {
                "has_headers": has_headers,
                "has_lists": has_lists,
                "has_code_blocks": has_code,
                "has_links": has_links,
            },
            "recommended_processing": self._get_processing_recommendation(content_type, content),
        }

    def _calculate_confidence(self, doc_indicators: int, trans_indicators: int) -> float:
        """Calculate confidence score for content type detection."""
        total_indicators = doc_indicators + trans_indicators
        if total_indicators == 0:
            return 0.5  # Neutral confidence

        stronger = max(doc_indicators, trans_indicators)
        confidence = stronger / total_indicators

        # Scale to 0.5-1.0 range (0.5 = low confidence, 1.0 = high confidence)
        return 0.5 + (confidence * 0.5)

    def _get_processing_recommendation(self, content_type: str, content: str) -> Dict[str, Any]:
        """Get processing recommendations based on content analysis."""
        suggestions: List[str] = []
        recommendations: Dict[str, Any] = {
            "primary_processor": content_type,
            "fallback_processor": "transcription" if content_type == "document" else "document",
            "suggested_options": suggestions,
        }

        # Add specific recommendations
        if content_type == "document":
            if RE_ANY_HTML_TAG.search(content):
                suggestions.append("Use HTML parser for best results")
            elif RE_MD_HEADER.search(content):
                suggestions.append("Use Markdown parser for best results")
            elif content.strip().startswith("{"):
                suggestions.append("Use JSON parser for best results")

        elif content_type == "transcription":
            if len(content.split()) > 50:
                suggestions.append("Consider breaking into smaller chunks")
            if RE_SPEECH_ARTIFACTS.search(content):
                suggestions.append("Speech artifacts detected - will be cleaned")

        return recommendations

    def process_batch_content(self, content_items: List[Dict[str, str]], preserve_order: bool = True) -> List[str]:
        """Process multiple content items in batch.

        Args:
            content_items: List of dicts with keys 'content', 'type', 'format_hint'
            preserve_order: Whether to maintain input order in output

        Returns:
            List of processed content strings
        """
        results = []

        for item in content_items:
            content = item.get("content", "")
            content_type = item.get("type", "auto")
            format_hint = item.get("format_hint", "")

            processed = self.process_mixed_content(content, content_type, format_hint)
            results.append(processed)

        return results

    def create_processing_report(self, content: str, format_hint: str = "") -> str:
        """Create a detailed processing report for debugging and analysis."""
        analysis = self.get_content_analysis(content, format_hint)
        processed = self.process_mixed_content(content, "auto", format_hint)

        report_lines = [
            "=== Mixed Content Processing Report ===",
            f"Content Length: {len(content)} characters",
            f"Detected Type: {analysis['detected_type']}",
            f"Confidence: {analysis['confidence']:.2f}",
            "",
            "=== Statistics ===",
            f"Words: {analysis['statistics']['word_count']}",
            f"Sentences: {analysis['statistics']['sentence_count']}",
            f"Avg Sentence Length: {analysis['statistics']['avg_sentence_length']}",
            f"Document Indicators: {analysis['statistics']['document_indicators']}",
            f"Transcription Indicators: {analysis['statistics']['transcription_indicators']}",
            "",
            "=== Structure ===",
            f"Has Headers: {analysis['structure']['has_headers']}",
            f"Has Lists: {analysis['structure']['has_lists']}",
            f"Has Code: {analysis['structure']['has_code_blocks']}",
            f"Has Links: {analysis['structure']['has_links']}",
            "",
            "=== Processing Recommendation ===",
            f"Primary: {analysis['recommended_processing']['primary_processor']}",
            f"Fallback: {analysis['recommended_processing']['fallback_processor']}",
        ]

        if analysis["recommended_processing"]["suggested_options"]:
            report_lines.append("Suggestions:")
            for suggestion in analysis["recommended_processing"]["suggested_options"]:
                report_lines.append(f"  - {suggestion}")

        report_lines.extend(
            [
                "",
                "=== Processed Output ===",
                f"Length: {len(processed)} characters",
                f"Preview: {processed[:100]}{'...' if len(processed) > 100 else ''}",
            ]
        )

        return "\n".join(report_lines)
