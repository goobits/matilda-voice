"""Base parser interface and semantic data structures."""

from abc import ABC, abstractmethod
from typing import List, Optional

# Import shared types from package root for use by this module and re-export
from matilda_voice.internal.types import SemanticElement, SemanticType

__all__ = ["BaseDocumentParser", "SemanticElement", "SemanticType"]


class BaseDocumentParser(ABC):
    """Abstract base class for document parsers."""

    @abstractmethod
    def parse(self, content: str) -> List[SemanticElement]:
        """Parse document content and return semantic elements.

        Args:
            content: Raw document content as string

        Returns:
            List of semantic elements in document order
        """
        pass

    @abstractmethod
    def can_parse(self, content: str, filename: Optional[str] = None) -> bool:
        """Check if this parser can handle the given content.

        Args:
            content: Raw document content
            filename: Optional filename for extension-based detection

        Returns:
            True if this parser can handle the content
        """
        pass
