"""OpenCode's upstream adapter that reuses the CLI baked into the shared image."""
from harbor.agents.installed.opencode import OpenCode

from adapters.preinstalled import Preinstalled


class LocalOpenCode(Preinstalled, OpenCode):
    package_to_check = "opencode-ai"
