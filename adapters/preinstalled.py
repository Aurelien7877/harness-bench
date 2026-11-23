"""Skip a harness install when the shared image already carries the pinned version."""
import shlex


class Preinstalled:
    """Mixin for Harbor installed agents installed through nvm (Pi, OpenCode)."""
    package_to_check = ""

    async def install(self, environment):
        spec = shlex.quote(f"{self.package_to_check}@{self._version}")
        if self._version and self.package_to_check:
            present = await environment.exec(
                command=f". ~/.nvm/nvm.sh >/dev/null 2>&1 && npm ls -g --depth=0 | grep -qF {spec}", timeout_sec=30)
            if present.return_code == 0:
                return
        await super().install(environment)
