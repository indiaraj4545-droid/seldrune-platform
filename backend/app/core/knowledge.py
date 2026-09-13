from enum import StrEnum


class KnowledgeKind(StrEnum):
    DOCUMENT = "document"
    RESEARCH = "research"
    DECISION = "decision"
    PROCEDURE = "procedure"
    RESULT = "result"


class MemoryScope(StrEnum):
    ORGANIZATION = "organization"
    AGENT = "agent"
    TASK = "task"


class MemoryKind(StrEnum):
    FACT = "fact"
    WORKING = "working"
    EPISODIC = "episodic"
    RESULT = "result"
