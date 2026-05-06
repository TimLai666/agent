import logging
import os
import sys

logger: logging.Logger = logging.getLogger(__name__)

# Honour an explicit env override; otherwise default to INFO so we don't spam
# DEBUG by default but still surface tool/permission/audit events.
_level_name = os.environ.get("TIM_AGENT_LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, _level_name, logging.INFO))

# Attach a stderr handler exactly once so logger.info/.warning/.error are
# actually visible. Without this, propagation to root logger would normally
# drop everything below WARNING via the default lastResort handler.
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_handler)
    logger.propagate = False
