
import logging

from teuthology.machines.base import MachinePool
from teuthology.machines.lock_server_pool import LockServerMachinePool


log = logging.getLogger(__name__)


def from_config() -> MachinePool:
    log.info("Using lock server machine pool")
    return LockServerMachinePool()


def auto_pool(ctx=None, pool: MachinePool | None = None) -> MachinePool:
    if pool is not None:
        return pool
    # TODO: cached pool on ctx if ctx is given
    return from_config()
