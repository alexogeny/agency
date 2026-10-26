from pathlib import Path
import sys
import unittest

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from Tests.promoted_tool_cases import PromotedToolCases
from Tests.promoted_tool_support import PromotedToolFixture
from Tests.promoted_web_cases import PromotedWebCases


class PromotedToolTests(
    PromotedToolFixture, PromotedToolCases, PromotedWebCases, unittest.TestCase
):
    """Keep the collected test IDs stable while organizing cases by domain."""


if __name__ == "__main__":
    unittest.main()
