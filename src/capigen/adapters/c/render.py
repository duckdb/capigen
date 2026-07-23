"""C-language render objects for the Jinja2 template layer.

These dataclasses encode C output semantics, not API spec semantics.
The resolver (resolve.py) is the only place that reads spec dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CUnionMember:
    name: str
    fields: list[CField]
    description: str = ""


@dataclass
class CField:
    name: str
    base: str = ""
    pointer: int = 0
    const: bool = False
    array_size: int | None = None
    description: str = ""
    # Aggregate fields: a field is either a leaf (base set) or carries one of
    # these. nested_fields -> anonymous struct; union_members -> anonymous union.
    nested_fields: list[CField] | None = None
    union_members: list[CUnionMember] | None = None


@dataclass
class CTypeDef:
    name: str
    canonical_name: str
    base: str
    is_pointer: bool
    tagged_struct: bool = False  # True -> implies a pointer typedef + is_pointer=True
    is_qualified: bool = False
    description: str = ""
    omitted: bool = False
    guard_directive: str = ""  # "#ifdef X" / "#ifndef X"; empty means no wrap


@dataclass
class CStruct:
    name: str
    template_alias: str
    pointer_alias: bool
    fields: list[CField]
    description: str = ""
    omitted: bool = False
    guard_directive: str = ""  # "#ifdef X" / "#ifndef X"; empty means no wrap


@dataclass
class CFuncPtrParam:
    name: str
    base: str
    pointer: int = 0
    const: bool = False


@dataclass
class CFuncPtr:
    name: str
    template_alias: str
    return_base: str
    return_pointer: int
    return_const: bool
    params: list[CFuncPtrParam]
    description: str = ""
    omitted: bool = False
    guard_directive: str = ""  # "#ifdef X" / "#ifndef X"; empty means no wrap


@dataclass
class CParam:
    name: str
    c_decl: str
    description: str | None = None


@dataclass
class CFunction:
    name: str
    description: str | None
    deprecated: str | None
    return_c: str
    static_inline: bool = False
    omitted: bool = False
    guard_directive: str = ""  # "#ifdef X" / "#ifndef X"; empty means no wrap
    deprecated_gate: bool = False  # legacy `deprecated` field: wrap in #ifndef
    parameters: dict[str, CParam] = field(default_factory=dict)


@dataclass
class CEnumValue:
    value: int | str  # str for expression values, e.g. the 0x7FFFFFFF sentinel
    description: str = ""


@dataclass
class CEnum:
    name: str
    description: str
    values: dict[str, CEnumValue]
    omitted: bool = False
    guard_directive: str = ""  # "#ifdef X" / "#ifndef X"; empty means no wrap


@dataclass
class CConstant:
    name: str
    value: int | str
    description: str = ""


@dataclass
class CModule:
    name: str
    types: list[CTypeDef]
    structs: list[CStruct]
    enums: list[CEnum]
    constants: list[CConstant]
    function_ptrs: list[CFuncPtr]
    functions: dict[str, CFunction]
