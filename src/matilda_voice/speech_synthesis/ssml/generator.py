"""Platform-specific SSML generation from Speech Markdown."""

import re
from enum import Enum
from typing import Dict, List, Match, Tuple


class SSMLPlatform(Enum):
    """Supported SSML platforms."""

    AZURE = "azure"
    GOOGLE = "google"
    AMAZON = "amazon"
    GENERIC = "generic"


class SSMLGenerator:
    """Generate platform-specific SSML from Speech Markdown."""

    def __init__(self, platform: SSMLPlatform = SSMLPlatform.GENERIC):
        self.platform = platform
        self.voice_map = self._get_voice_mapping()
        self.break_map = self._get_break_mapping()
        self.emphasis_map = self._get_emphasis_mapping()

    def convert_speech_markdown(self, speech_markdown: str) -> str:
        """Convert Speech Markdown to platform-specific SSML."""
        ssml_content = self._process_speech_markdown(speech_markdown)
        return self._wrap_with_speak_tag(ssml_content)

    def _process_speech_markdown(self, speech_markdown: str) -> str:
        """Process Speech Markdown syntax and convert to SSML elements."""
        content = speech_markdown

        # Process emotion markers: (excited)[text] → prosody tags
        content = self._convert_emotion_markers(content)

        # Process timing markers: [1s] → break tags
        content = self._convert_timing_markers(content)

        # Process emphasis markers: **text** → emphasis tags
        content = self._convert_emphasis_markers(content)

        return content

    def _convert_emotion_markers(self, content: str) -> str:
        """Convert (emotion)[text] to platform-specific prosody tags."""
        pattern = r"\((\w+)\)\[([^\]]+)\]"

        def replace_emotion(match: Match[str]) -> str:
            emotion = match.group(1)
            text = match.group(2)

            if emotion in self.voice_map:
                settings = self.voice_map[emotion]
                return self._create_prosody_tag(text, settings)
            else:
                return text

        return re.sub(pattern, replace_emotion, content)

    def _convert_timing_markers(self, content: str) -> str:
        """Convert [1s], [500ms] to platform-specific break tags."""
        pattern = r"\[(\d+(?:\.\d+)?)(s|ms)\]"

        def replace_timing(match: Match[str]) -> str:
            value = match.group(1)
            unit = match.group(2)

            # Normalize to seconds for consistent handling
            if unit == "ms":
                seconds = float(value) / 1000
            else:
                seconds = float(value)

            return self._create_break_tag(seconds)

        return re.sub(pattern, replace_timing, content)

    def _convert_emphasis_markers(self, content: str) -> str:
        """Convert **text** to platform-specific emphasis tags."""
        pattern = r"\*\*([^\*]+)\*\*"

        def replace_emphasis(match: Match[str]) -> str:
            text = match.group(1)
            return self._create_emphasis_tag(text, "strong")

        return re.sub(pattern, replace_emphasis, content)

    def _create_prosody_tag(self, text: str, settings: Dict) -> str:
        """Create platform-specific prosody tag."""
        if self.platform == SSMLPlatform.AZURE:
            rate = settings.get("rate", "medium")
            pitch = settings.get("pitch", "0%")
            volume = settings.get("volume", "0%")
            return f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">{text}</prosody>'

        elif self.platform == SSMLPlatform.GOOGLE:
            rate = settings.get("rate", "medium")
            pitch = settings.get("pitch", "0st")
            volume = settings.get("volume", "medium")
            return f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">{text}</prosody>'

        elif self.platform == SSMLPlatform.AMAZON:
            rate = settings.get("rate", "medium")
            pitch = settings.get("pitch", "medium")
            volume = settings.get("volume", "medium")
            return f'<prosody rate="{rate}" pitch="{pitch}" volume="{volume}">{text}</prosody>'

        else:  # GENERIC
            rate = settings.get("rate", "medium")
            pitch = settings.get("pitch", "medium")
            return f'<prosody rate="{rate}" pitch="{pitch}">{text}</prosody>'

    def _create_break_tag(self, seconds: float) -> str:
        """Create platform-specific break tag."""
        if self.platform == SSMLPlatform.AZURE:
            if seconds >= 1.0:
                return f'<break time="{seconds}s"/>'
            else:
                ms = int(seconds * 1000)
                return f'<break time="{ms}ms"/>'

        elif self.platform == SSMLPlatform.GOOGLE:
            return f'<break time="{seconds}s"/>'

        elif self.platform == SSMLPlatform.AMAZON:
            if seconds >= 1.0:
                return f'<break time="{seconds}s"/>'
            else:
                ms = int(seconds * 1000)
                return f'<break time="{ms}ms"/>'

        else:  # GENERIC
            return f'<break time="{seconds}s"/>'

    def _create_emphasis_tag(self, text: str, level: str = "moderate") -> str:
        """Create platform-specific emphasis tag."""
        if self.platform == SSMLPlatform.AZURE:
            return f'<emphasis level="{level}">{text}</emphasis>'

        elif self.platform == SSMLPlatform.GOOGLE:
            return f'<emphasis level="{level}">{text}</emphasis>'

        elif self.platform == SSMLPlatform.AMAZON:
            return f'<emphasis level="{level}">{text}</emphasis>'

        else:  # GENERIC
            return f"<emphasis>{text}</emphasis>"

    def _wrap_with_speak_tag(self, content: str) -> str:
        """Wrap content with platform-specific speak tag."""
        if self.platform == SSMLPlatform.AZURE:
            return f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">\n{content}\n</speak>'

        elif self.platform == SSMLPlatform.GOOGLE:
            return f"<speak>\n{content}\n</speak>"

        elif self.platform == SSMLPlatform.AMAZON:
            return f"<speak>\n{content}\n</speak>"

        else:  # GENERIC
            return f"<speak>\n{content}\n</speak>"

    def _get_voice_mapping(self) -> Dict:
        """Get platform-specific voice and prosody mappings."""
        if self.platform == SSMLPlatform.AZURE:
            return {
                "excited": {"rate": "fast", "pitch": "+15%", "volume": "+20%"},
                "soft": {"rate": "slow", "pitch": "-10%", "volume": "-10%"},
                "monotone": {"rate": "medium", "pitch": "0%", "volume": "0%"},
                "normal": {"rate": "medium", "pitch": "0%", "volume": "0%"},
            }

        elif self.platform == SSMLPlatform.GOOGLE:
            return {
                "excited": {"rate": "fast", "pitch": "+3st", "volume": "loud"},
                "soft": {"rate": "slow", "pitch": "-2st", "volume": "soft"},
                "monotone": {"rate": "medium", "pitch": "0st", "volume": "medium"},
                "normal": {"rate": "medium", "pitch": "0st", "volume": "medium"},
            }

        elif self.platform == SSMLPlatform.AMAZON:
            return {
                "excited": {"rate": "fast", "pitch": "high", "volume": "loud"},
                "soft": {"rate": "slow", "pitch": "low", "volume": "soft"},
                "monotone": {"rate": "medium", "pitch": "medium", "volume": "medium"},
                "normal": {"rate": "medium", "pitch": "medium", "volume": "medium"},
            }

        else:  # GENERIC
            return {
                "excited": {"rate": "fast", "pitch": "high", "volume": "loud"},
                "soft": {"rate": "slow", "pitch": "low", "volume": "soft"},
                "monotone": {"rate": "medium", "pitch": "medium", "volume": "medium"},
                "normal": {"rate": "medium", "pitch": "medium", "volume": "medium"},
            }

    def _get_break_mapping(self) -> Dict:
        """Get platform-specific break time limits."""
        if self.platform == SSMLPlatform.AZURE:
            return {"max_seconds": 10.0, "units": ["s", "ms"]}
        elif self.platform == SSMLPlatform.GOOGLE:
            return {"max_seconds": 10.0, "units": ["s", "ms"]}
        elif self.platform == SSMLPlatform.AMAZON:
            return {"max_seconds": 10.0, "units": ["s", "ms"]}
        else:
            return {"max_seconds": 10.0, "units": ["s", "ms"]}

    def _get_emphasis_mapping(self) -> Dict:
        """Get platform-specific emphasis levels."""
        return {"strong": "strong", "moderate": "moderate", "reduced": "reduced"}

    def validate_ssml(self, ssml: str) -> Tuple[bool, str]:
        """Validate generated SSML for platform compliance."""
        errors = []

        # Check for required speak tag
        if not ssml.strip().startswith("<speak"):
            errors.append("Missing <speak> root tag")

        # Check for balanced tags
        # Updated regex to properly capture self-closing tags
        tags = re.findall(r"<(/?)([^>]+?)(/?)>", ssml)
        open_tags: List[str] = []

        for start_slash, tag_content, end_slash in tags:
            # Extract tag name
            tag_name = tag_content.split()[0] if " " in tag_content else tag_content

            if start_slash:  # Closing tag </tag>
                if open_tags and open_tags[-1] == tag_name:
                    open_tags.pop()
                else:
                    errors.append(f"Unmatched closing tag: {tag_name}")
            elif end_slash:  # Self-closing tag <tag/>
                # Self-closing tags don't need to be tracked
                continue
            else:  # Opening tag <tag>
                open_tags.append(tag_name)

        if open_tags:
            errors.append(f"Unclosed tags: {', '.join(open_tags)}")

        # Platform-specific validation
        if self.platform == SSMLPlatform.AZURE:
            if 'xmlns="http://www.w3.org/2001/10/synthesis"' not in ssml:
                errors.append("Azure SSML missing required namespace")

        return len(errors) == 0, "; ".join(errors) if errors else "Valid SSML"
