import abc


class MachinePool(abc.ABC):
    @abc.abstractmethod
    def description(self) -> str: ...

    @abc.abstractmethod
    def list(
        self,
        machine_type=None,
        up=None,
        locked=None,
        count=None,
        tries=None,
    ): ...

    @abc.abstractmethod
    def reserve(
        self,
        ctx,
        num,
        machine_type,
        user=None,
        description=None,
        os_type=None,
        os_version=None,
        arch=None,
        reimage=True,
    ): ...

    @abc.abstractmethod
    def release(
        self,
        ctx,
        name,
        user=None,
        description=None,
        status_hint=None,
        constraints=None,
    ) -> bool: ...

    @abc.abstractmethod
    def is_vm(self, name: str) -> bool: ...

    @abc.abstractmethod
    def statuses(self, name: 'list[str]') -> 'list[dict]': ...
