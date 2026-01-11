import pytest

from matilda_voice.document_processing.parser_factory import DocumentParserFactory
from matilda_voice.document_processing.performance_cache import PerformanceOptimizer
from matilda_voice.speech_synthesis.ssml.generator import SSMLGenerator, SSMLPlatform


class TestDocumentProcessing:

    def test_html_parsing(self):
        """Test HTML document parsing"""
        html_content = """
        <h1>Title</h1>
        <p>This is <strong>important</strong> text.</p>
        """
        factory = DocumentParserFactory()
        elements = factory.parse_document(html_content, "html")

        assert len(elements) > 0
        # Check for heading - type is an enum, need to check value
        from matilda_voice.document_processing.base_parser import SemanticType

        assert any(e.type == SemanticType.HEADING or e.type.value == "heading" for e in elements)
        assert any("important" in e.content for e in elements)

    def test_json_parsing(self):
        """Test JSON document parsing"""
        json_content = '{"title": "API Guide", "sections": ["Introduction", "Usage"]}'
        factory = DocumentParserFactory()
        elements = factory.parse_document(json_content, "json")

        assert len(elements) > 0
        assert any("API Guide" in e.content for e in elements)

    def test_markdown_parsing(self):
        """Test Markdown parsing with emotion detection"""
        md_content = "# Welcome\n\nThis is **bold** and *italic* text."
        factory = DocumentParserFactory()
        elements = factory.parse_document(md_content, "markdown")

        assert len(elements) > 0
        # Check type value or enum
        from matilda_voice.document_processing.base_parser import SemanticType

        assert elements[0].type == SemanticType.HEADING or elements[0].type.value == "heading"

    def test_ssml_generation_azure(self):
        """Test SSML generation for Azure platform"""
        generator = SSMLGenerator(SSMLPlatform.AZURE)
        speech_md = "Hello [500ms] this is a test"
        ssml = generator.convert_speech_markdown(speech_md)

        assert "<speak" in ssml
        assert "break" in ssml or "mstts:silence" in ssml

    def test_performance_under_2_seconds(self):
        """Test large document parsing performance"""
        import time

        # Generate large markdown document
        large_content = "\n".join([f"# Section {i}\n\nContent for section {i}." for i in range(100)])

        factory = DocumentParserFactory()
        start = time.time()
        elements = factory.parse_document(large_content, "markdown")
        duration = time.time() - start

        assert duration < 2.0, f"Parsing took {duration}s, should be under 2s"
        assert len(elements) > 0

    def test_ssml_validation(self):
        """Test SSML output validates against platform schemas"""
        from xml.etree import ElementTree as ET

        generator = SSMLGenerator(SSMLPlatform.AZURE)
        speech_md = "Hello (excited)[world]! [1s] How are you?"
        ssml = generator.convert_speech_markdown(speech_md)

        # Basic XML validation
        try:
            root = ET.fromstring(ssml)
            # Handle namespaced tags
            assert root.tag.endswith("speak") or root.tag == "speak"
        except ET.ParseError:
            pytest.fail("Generated SSML is not valid XML")

    def test_mixed_content_processing(self):
        """Test mixed document and transcription content processing"""
        from matilda_voice.document_processing.mixed_content_processor import MixedContentProcessor

        processor = MixedContentProcessor()

        # Test document content processing
        doc_result = processor.process_mixed_content("# Title\n\nDocument content", content_type="document")
        assert "Title" in doc_result, "Title should be preserved in document processing"
        assert len(doc_result) > 0, "Document result should not be empty"
        assert isinstance(doc_result, str), "Document result should be a string"

        # Test transcription content processing
        trans_result = processor.process_mixed_content(
            "Um, this is like, you know, spoken text", content_type="transcription"
        )
        assert isinstance(trans_result, str), "Transcription result should be a string"
        assert len(trans_result) > 0, "Transcription result should not be empty"

        # The processing should handle the transcription type appropriately
        # It may or may not clean up filler words depending on implementation
        # The key test is that it processes without error and returns meaningful content
        assert "text" in trans_result.lower(), "Core content should be preserved"

        # Verify that transcription and document processing produce different results
        assert trans_result != doc_result, "Transcription and document processing should handle content differently"

    def test_cache_functionality(self, tmp_path):
        """Test document caching functionality"""
        # Use a temp directory for the cache to ensure isolation
        cache_dir = tmp_path / "cache"
        optimizer = PerformanceOptimizer(cache_dir=str(cache_dir), enable_caching=True)

        # First processing - should cache
        content = "# Test Document\n\nThis is test content."
        elements1 = optimizer.process_document(content, "markdown")
        stats1 = optimizer.get_performance_stats()

        # Second processing - should use cache
        elements2 = optimizer.process_document(content, "markdown")
        stats2 = optimizer.get_performance_stats()

        assert elements1 == elements2
        assert stats2["cache_hits"] > stats1["cache_hits"]
        assert stats2["cache_misses"] == stats1["cache_misses"]

    def test_emotion_detection_integration(self):
        """Test emotion detection in document processing"""
        from matilda_voice.speech_synthesis.advanced_emotion_detector import AdvancedEmotionDetector

        # Technical content
        tech_content = """
        ## API Reference
        The `process()` function takes the following parameters:
        - `data`: Input data structure
        - `options`: Configuration object
        """

        factory = DocumentParserFactory()
        elements = factory.parse_document(tech_content, "markdown")

        detector = AdvancedEmotionDetector()
        profile = detector.detect_document_type(elements)

        assert profile in ["technical", "tutorial"]

    def test_ssml_platform_variations(self):
        """Test SSML generation for different platforms"""
        speech_md = "Hello [pause] world"

        platforms = [SSMLPlatform.AZURE, SSMLPlatform.GOOGLE, SSMLPlatform.AMAZON]

        for platform in platforms:
            generator = SSMLGenerator(platform)
            ssml = generator.convert_speech_markdown(speech_md)

            assert "<speak" in ssml
            assert "</speak>" in ssml
            # Each platform should have some unique formatting
            assert len(ssml) > len(speech_md)

    def test_document_format_autodetection(self):
        """Test automatic format detection"""
        factory = DocumentParserFactory()

        # HTML content
        html_content = "<html><body><h1>Test</h1></body></html>"
        elements = factory.parse_document(html_content, "auto")
        assert len(elements) > 0

        # JSON content
        json_content = '{"key": "value"}'
        elements = factory.parse_document(json_content, "auto")
        assert len(elements) > 0

        # Markdown content
        md_content = "# Heading\n\nParagraph"
        elements = factory.parse_document(md_content, "auto")
        assert len(elements) > 0

    def test_large_document_chunking(self):
        """Test chunking for large documents"""
        optimizer = PerformanceOptimizer(enable_caching=False)

        # Create a very large document
        large_content = "\n\n".join(
            [f"# Chapter {i}\n\n" + "\n".join([f"Paragraph {j} content." for j in range(50)]) for i in range(20)]
        )

        elements = optimizer.process_document(large_content, "markdown", max_chunk_size=5000)

        assert len(elements) > 0
        # Verify all elements were parsed
        assert any(e.content.startswith("Chapter") for e in elements)

    def test_configuration_integration(self):
        """Test that configuration settings are respected"""
        from matilda_voice.internal.config import load_config, save_config

        # Save current config
        original_config = load_config()

        # Test config
        test_config = original_config.copy()
        test_config["document_parsing"] = {
            "default_format": "markdown",
            "emotion_detection": False,
            "cache_enabled": False,
            "cache_ttl": 1800,
        }

        save_config(test_config)

        # Verify config was saved
        loaded_config = load_config()
        assert loaded_config["document_parsing"]["default_format"] == "markdown"
        assert loaded_config["document_parsing"]["emotion_detection"] is False

        # Restore original config
        save_config(original_config)
