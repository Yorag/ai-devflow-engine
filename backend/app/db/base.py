from enum import Enum

from sqlalchemy import MetaData


class DatabaseRole(str, Enum):
    CONTROL = "control"
    RUNTIME = "runtime"
    GRAPH = "graph"
    EVENT = "event"
    LOG = "log"


DATABASE_FILE_NAMES: dict[DatabaseRole, str] = {
    DatabaseRole.CONTROL: "control.db",
    DatabaseRole.RUNTIME: "runtime.db",
    DatabaseRole.GRAPH: "graph.db",
    DatabaseRole.EVENT: "event.db",
    DatabaseRole.LOG: "log.db",
}

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ROLE_METADATA: dict[DatabaseRole, MetaData] = {
    role: MetaData(naming_convention=NAMING_CONVENTION)
    for role in DatabaseRole
}
