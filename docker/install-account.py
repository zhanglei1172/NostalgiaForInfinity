"""Install the NFI API/configuration hooks; fail the build if upstream moved them."""

from pathlib import Path
import freqtrade

path = Path(freqtrade.__file__).parent / "rpc/api_server/webserver.py"
source = path.read_text()
anchor = '        app.include_router(api_v1_public, prefix="/api/v1")'
for module, function in [
  ("nfi_account", "configure_account_api"),
  ("nfi_research", "configure_research_api"),
  ("nfi_live", "configure_live_api"),
]:
  marker = f"from {module} import {function}"
  if marker not in source:
    if source.count(anchor) != 1:
      raise RuntimeError("Unsupported Freqtrade API layout: review NFI integration before upgrading")
    source = source.replace(anchor, f"        {marker}\n        {function}(app, config)\n\n" + anchor)
compile(source, str(path), "exec")
path.write_text(source)

# Apply only explicitly enabled paper recipes before the strategy is constructed.
path = Path(freqtrade.__file__).parent / "configuration/configuration.py"
source = path.read_text()
anchor = "            self.config = self.load_config()"
marker = "from nfi_research.recipe import apply_paper_recipe"
if marker not in source:
  if source.count(anchor) != 1:
    raise RuntimeError("Unsupported Freqtrade configuration layout: review recipe integration")
  source = source.replace(anchor, anchor + f"\n            {marker}\n            apply_paper_recipe(self.config)")
compile(source, str(path), "exec")
path.write_text(source)

# A Web preference overrides the stopped fallback only for a fresh worker, never a config reload.
path = Path(freqtrade.__file__).parent / "worker.py"
source = path.read_text()
anchor = "        self.freqtrade = FreqtradeBot(self._config)"
marker = "from nfi_account.startup import apply_startup_policy"
if marker not in source:
  if source.count(anchor) != 1:
    raise RuntimeError("Unsupported Freqtrade worker layout: review startup preference integration")
  source = source.replace(anchor, f"        {marker}\n        apply_startup_policy(self._config, reconfig)\n" + anchor)
compile(source, str(path), "exec")
path.write_text(source)

# Observe final exchange outcomes after Freqtrade's own retries, before exchange initialization.
marker = "from nfi_account.faults import install_fault_hooks"
if marker not in source:
  if source.count(anchor) != 1:
    raise RuntimeError("Unsupported Freqtrade worker layout: review notification observer integration")
  source = source.replace(anchor, f"        {marker}\n        install_fault_hooks(self._config)\n" + anchor)
compile(source, str(path), "exec")
path.write_text(source)
print("NFI account, research, recipe, startup and notification hooks installed")
