"""
Tests for relay.types — constants, enumerations, and value dataclasses.

Covers:
- MAGIC and VERSION constant values
- TypeTag integer values (0x01 - 0x19)
- MessageType integer values
- VectorDtype integer values
- DeltaOpType string values
- RelayField, RelayMessage, RelayRef, DeltaOp dataclass construction
- VectorValue, CodeBlock, MarkdownBlock, EnumValue construction and validation
- RelayMessage.get_field() and to_dict() helpers
"""

from __future__ import annotations

from uuid import UUID

import numpy as np
import pytest

from relay.types import (
    FIELD_HEADER_SIZE,
    FRAME_HEADER_SIZE,
    MAGIC,
    NUMPY_TO_VECTOR_DTYPE,
    VECTOR_DTYPE_ITEMSIZE,
    VECTOR_DTYPE_TO_NUMPY,
    VERSION,
    CodeBlock,
    DeltaOp,
    DeltaOpType,
    EnumValue,
    MarkdownBlock,
    MessageType,
    RelayField,
    RelayMessage,
    RelayRef,
    TypeTag,
    VectorDtype,
    VectorValue,
)

# ---------------------------------------------------------------------------
# Wire-format constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for the module-level wire-format constants."""

    def test_magic_is_0xDE(self):
        """MAGIC must equal 0xDE (222 decimal) per the wire-format spec."""
        assert MAGIC == 0xDE

    def test_magic_decimal_222(self):
        """MAGIC expressed as a decimal integer equals 222."""
        assert MAGIC == 222

    def test_version_is_0x01(self):
        """VERSION must equal 0x01."""
        assert VERSION == 0x01

    def test_frame_header_size_is_12(self):
        """FRAME_HEADER_SIZE must be exactly 12 bytes."""
        assert FRAME_HEADER_SIZE == 12

    def test_field_header_size_is_7(self):
        """FIELD_HEADER_SIZE must be exactly 7 bytes."""
        assert FIELD_HEADER_SIZE == 7


# ---------------------------------------------------------------------------
# TypeTag enum
# ---------------------------------------------------------------------------


class TestTypeTag:
    """Tests for TypeTag integer values (0x01 - 0x19)."""

    def test_null_is_0x01(self):
        """TypeTag.NULL == 0x01."""
        assert TypeTag.NULL == 0x01

    def test_bool_is_0x02(self):
        """TypeTag.BOOL == 0x02."""
        assert TypeTag.BOOL == 0x02

    def test_int8_is_0x03(self):
        """TypeTag.INT8 == 0x03."""
        assert TypeTag.INT8 == 0x03

    def test_int16_is_0x04(self):
        """TypeTag.INT16 == 0x04."""
        assert TypeTag.INT16 == 0x04

    def test_int32_is_0x05(self):
        """TypeTag.INT32 == 0x05."""
        assert TypeTag.INT32 == 0x05

    def test_int64_is_0x06(self):
        """TypeTag.INT64 == 0x06."""
        assert TypeTag.INT64 == 0x06

    def test_uint8_is_0x07(self):
        """TypeTag.UINT8 == 0x07."""
        assert TypeTag.UINT8 == 0x07

    def test_uint16_is_0x08(self):
        """TypeTag.UINT16 == 0x08."""
        assert TypeTag.UINT16 == 0x08

    def test_uint32_is_0x09(self):
        """TypeTag.UINT32 == 0x09."""
        assert TypeTag.UINT32 == 0x09

    def test_uint64_is_0x0A(self):
        """TypeTag.UINT64 == 0x0A."""
        assert TypeTag.UINT64 == 0x0A

    def test_float32_is_0x0B(self):
        """TypeTag.FLOAT32 == 0x0B."""
        assert TypeTag.FLOAT32 == 0x0B

    def test_float64_is_0x0C(self):
        """TypeTag.FLOAT64 == 0x0C."""
        assert TypeTag.FLOAT64 == 0x0C

    def test_string_is_0x0D(self):
        """TypeTag.STRING == 0x0D."""
        assert TypeTag.STRING == 0x0D

    def test_bytes_is_0x0E(self):
        """TypeTag.BYTES == 0x0E."""
        assert TypeTag.BYTES == 0x0E

    def test_array_is_0x0F(self):
        """TypeTag.ARRAY == 0x0F."""
        assert TypeTag.ARRAY == 0x0F

    def test_object_is_0x10(self):
        """TypeTag.OBJECT == 0x10."""
        assert TypeTag.OBJECT == 0x10

    def test_uuid_is_0x11(self):
        """TypeTag.UUID == 0x11."""
        assert TypeTag.UUID == 0x11

    def test_datetime_is_0x12(self):
        """TypeTag.DATETIME == 0x12."""
        assert TypeTag.DATETIME == 0x12

    def test_uri_is_0x13(self):
        """TypeTag.URI == 0x13."""
        assert TypeTag.URI == 0x13

    def test_vector_is_0x14(self):
        """TypeTag.VECTOR == 0x14."""
        assert TypeTag.VECTOR == 0x14

    def test_enum_is_0x15(self):
        """TypeTag.ENUM == 0x15."""
        assert TypeTag.ENUM == 0x15

    def test_code_block_is_0x16(self):
        """TypeTag.CODE_BLOCK == 0x16."""
        assert TypeTag.CODE_BLOCK == 0x16

    def test_markdown_block_is_0x17(self):
        """TypeTag.MARKDOWN_BLOCK == 0x17."""
        assert TypeTag.MARKDOWN_BLOCK == 0x17

    def test_ref_is_0x18(self):
        """TypeTag.REF == 0x18."""
        assert TypeTag.REF == 0x18

    def test_delta_op_is_0x19(self):
        """TypeTag.DELTA_OP == 0x19."""
        assert TypeTag.DELTA_OP == 0x19

    def test_type_tag_count_is_25(self):
        """There are exactly 25 TypeTag members (0x01 through 0x19)."""
        assert len(TypeTag) == 25

    def test_type_tag_members_are_int(self):
        """Every TypeTag member value is an int."""
        for tag in TypeTag:
            assert isinstance(int(tag), int)

    def test_type_tag_from_int(self):
        """TypeTag(0x0D) resolves to TypeTag.STRING."""
        assert TypeTag(0x0D) == TypeTag.STRING


# ---------------------------------------------------------------------------
# MessageType enum
# ---------------------------------------------------------------------------


class TestMessageType:
    """Tests for MessageType integer values."""

    def test_full_is_0x0001(self):
        """MessageType.FULL == 1."""
        assert MessageType.FULL == 0x0001

    def test_delta_is_0x0002(self):
        """MessageType.DELTA == 2."""
        assert MessageType.DELTA == 0x0002

    def test_ref_only_is_0x0003(self):
        """MessageType.REF_ONLY == 3."""
        assert MessageType.REF_ONLY == 0x0003

    def test_schema_def_is_0x0004(self):
        """MessageType.SCHEMA_DEF == 4."""
        assert MessageType.SCHEMA_DEF == 0x0004

    def test_error_is_0x0005(self):
        """MessageType.ERROR == 5."""
        assert MessageType.ERROR == 0x0005

    def test_message_type_from_int(self):
        """MessageType(2) resolves to MessageType.DELTA."""
        assert MessageType(2) == MessageType.DELTA


# ---------------------------------------------------------------------------
# VectorDtype enum
# ---------------------------------------------------------------------------


class TestVectorDtype:
    """Tests for VectorDtype integer values."""

    def test_float16_is_0x01(self):
        """VectorDtype.FLOAT16 == 1."""
        assert VectorDtype.FLOAT16 == 0x01

    def test_float32_is_0x02(self):
        """VectorDtype.FLOAT32 == 2."""
        assert VectorDtype.FLOAT32 == 0x02

    def test_float64_is_0x03(self):
        """VectorDtype.FLOAT64 == 3."""
        assert VectorDtype.FLOAT64 == 0x03

    def test_int8_is_0x04(self):
        """VectorDtype.INT8 == 4."""
        assert VectorDtype.INT8 == 0x04

    def test_dtype_to_numpy_keys(self):
        """VECTOR_DTYPE_TO_NUMPY contains all four VectorDtype members."""
        assert set(VECTOR_DTYPE_TO_NUMPY.keys()) == set(VectorDtype)

    def test_dtype_to_numpy_float32_value(self):
        """VECTOR_DTYPE_TO_NUMPY[VectorDtype.FLOAT32] == 'float32'."""
        assert VECTOR_DTYPE_TO_NUMPY[VectorDtype.FLOAT32] == "float32"

    def test_numpy_to_dtype_round_trip(self):
        """NUMPY_TO_VECTOR_DTYPE is the inverse of VECTOR_DTYPE_TO_NUMPY."""
        for dtype, np_str in VECTOR_DTYPE_TO_NUMPY.items():
            assert NUMPY_TO_VECTOR_DTYPE[np_str] == dtype

    def test_itemsize_float32(self):
        """VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT32] == 4."""
        assert VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT32] == 4

    def test_itemsize_float16(self):
        """VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT16] == 2."""
        assert VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT16] == 2

    def test_itemsize_float64(self):
        """VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT64] == 8."""
        assert VECTOR_DTYPE_ITEMSIZE[VectorDtype.FLOAT64] == 8

    def test_itemsize_int8(self):
        """VECTOR_DTYPE_ITEMSIZE[VectorDtype.INT8] == 1."""
        assert VECTOR_DTYPE_ITEMSIZE[VectorDtype.INT8] == 1


# ---------------------------------------------------------------------------
# DeltaOpType enum
# ---------------------------------------------------------------------------


class TestDeltaOpType:
    """Tests for DeltaOpType string values."""

    def test_set_value(self):
        """DeltaOpType.SET == 'SET'."""
        assert DeltaOpType.SET == "SET"

    def test_del_value(self):
        """DeltaOpType.DEL == 'DEL'."""
        assert DeltaOpType.DEL == "DEL"

    def test_app_value(self):
        """DeltaOpType.APP == 'APP'."""
        assert DeltaOpType.APP == "APP"

    def test_spl_value(self):
        """DeltaOpType.SPL == 'SPL'."""
        assert DeltaOpType.SPL == "SPL"

    def test_from_string(self):
        """DeltaOpType('SET') resolves to DeltaOpType.SET."""
        assert DeltaOpType("SET") == DeltaOpType.SET


# ---------------------------------------------------------------------------
# VectorValue
# ---------------------------------------------------------------------------


class TestVectorValue:
    """Tests for the VectorValue semantic type dataclass."""

    def test_construction_float32(self):
        """VectorValue accepts float32 numpy array with matching dim."""
        data = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        v = VectorValue(dtype=VectorDtype.FLOAT32, dim=3, data=data)
        assert v.dim == 3
        assert v.dtype == VectorDtype.FLOAT32

    def test_data_equality(self):
        """Two VectorValues with identical data compare equal."""
        data = np.array([1.0, 2.0], dtype=np.float32)
        v1 = VectorValue(VectorDtype.FLOAT32, 2, data.copy())
        v2 = VectorValue(VectorDtype.FLOAT32, 2, data.copy())
        assert v1 == v2

    def test_data_inequality(self):
        """VectorValues with different data are not equal."""
        v1 = VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0, 2.0], dtype=np.float32))
        v2 = VectorValue(VectorDtype.FLOAT32, 2, np.array([1.0, 9.0], dtype=np.float32))
        assert v1 != v2

    def test_dim_mismatch_raises_value_error(self):
        """VectorValue raises ValueError when dim != len(data)."""
        data = np.array([1.0, 2.0], dtype=np.float32)
        with pytest.raises(ValueError, match="dim=5"):
            VectorValue(VectorDtype.FLOAT32, 5, data)

    def test_hash_is_stable(self):
        """VectorValue is hashable and hash is stable across calls."""
        data = np.array([1.0, 2.0], dtype=np.float32)
        v = VectorValue(VectorDtype.FLOAT32, 2, data)
        assert hash(v) == hash(v)

    def test_float64_dtype(self):
        """VectorValue accepts float64 arrays."""
        data = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float64)
        v = VectorValue(VectorDtype.FLOAT64, 5, data)
        assert v.dim == 5
        assert v.dtype == VectorDtype.FLOAT64

    def test_int8_dtype(self):
        """VectorValue accepts int8 arrays."""
        data = np.array([1, -1, 0], dtype=np.int8)
        v = VectorValue(VectorDtype.INT8, 3, data)
        assert v.dtype == VectorDtype.INT8


# ---------------------------------------------------------------------------
# CodeBlock
# ---------------------------------------------------------------------------


class TestCodeBlock:
    """Tests for the CodeBlock semantic type dataclass."""

    def test_construction(self):
        """CodeBlock stores lang and code correctly."""
        cb = CodeBlock(lang="python", code="print('hello')")
        assert cb.lang == "python"
        assert cb.code == "print('hello')"

    def test_equality(self):
        """Two CodeBlocks with the same fields are equal."""
        cb1 = CodeBlock(lang="json", code='{"key": "value"}')
        cb2 = CodeBlock(lang="json", code='{"key": "value"}')
        assert cb1 == cb2

    def test_inequality_lang(self):
        """CodeBlocks with different lang are not equal."""
        cb1 = CodeBlock(lang="python", code="x = 1")
        cb2 = CodeBlock(lang="ruby", code="x = 1")
        assert cb1 != cb2

    def test_frozen(self):
        """CodeBlock is frozen — assignment raises AttributeError."""
        cb = CodeBlock(lang="python", code="pass")
        with pytest.raises(AttributeError):
            cb.lang = "ruby"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MarkdownBlock
# ---------------------------------------------------------------------------


class TestMarkdownBlock:
    """Tests for the MarkdownBlock semantic type dataclass."""

    def test_construction(self):
        """MarkdownBlock stores content correctly."""
        mb = MarkdownBlock(content="# Title\nBody text.")
        assert mb.content == "# Title\nBody text."

    def test_equality(self):
        """Two MarkdownBlocks with identical content are equal."""
        mb1 = MarkdownBlock(content="hello")
        mb2 = MarkdownBlock(content="hello")
        assert mb1 == mb2

    def test_frozen(self):
        """MarkdownBlock is frozen — assignment raises AttributeError."""
        mb = MarkdownBlock(content="text")
        with pytest.raises(AttributeError):
            mb.content = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EnumValue
# ---------------------------------------------------------------------------


class TestEnumValue:
    """Tests for the EnumValue semantic type dataclass."""

    def test_construction(self):
        """EnumValue stores name and index correctly."""
        ev = EnumValue(name="assistant", index=2)
        assert ev.name == "assistant"
        assert ev.index == 2

    def test_equality(self):
        """Two EnumValues with the same name and index are equal."""
        ev1 = EnumValue(name="tool", index=3)
        ev2 = EnumValue(name="tool", index=3)
        assert ev1 == ev2

    def test_inequality_index(self):
        """EnumValues with different indexes are not equal."""
        ev1 = EnumValue(name="user", index=1)
        ev2 = EnumValue(name="user", index=0)
        assert ev1 != ev2

    def test_frozen(self):
        """EnumValue is frozen — assignment raises AttributeError."""
        ev = EnumValue(name="system", index=0)
        with pytest.raises(AttributeError):
            ev.index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RelayRef
# ---------------------------------------------------------------------------


class TestRelayRef:
    """Tests for the RelayRef dataclass."""

    def test_construction(self):
        """RelayRef stores all three fields correctly."""
        ref = RelayRef(
            session_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            call_index=2,
            field_path="output.embedding",
        )
        assert ref.session_id == UUID("550e8400-e29b-41d4-a716-446655440000")
        assert ref.call_index == 2
        assert ref.field_path == "output.embedding"

    def test_equality(self):
        """Two RelayRefs with identical fields are equal."""
        sid = UUID("550e8400-e29b-41d4-a716-446655440000")
        ref1 = RelayRef(session_id=sid, call_index=0, field_path="x.y")
        ref2 = RelayRef(session_id=sid, call_index=0, field_path="x.y")
        assert ref1 == ref2

    def test_frozen(self):
        """RelayRef is frozen — assignment raises AttributeError."""
        ref = RelayRef(
            session_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            call_index=0,
            field_path="a",
        )
        with pytest.raises(AttributeError):
            ref.call_index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DeltaOp
# ---------------------------------------------------------------------------


class TestDeltaOp:
    """Tests for the DeltaOp dataclass."""

    def test_set_op_construction(self):
        """DeltaOp SET stores all fields correctly."""
        op = DeltaOp(
            op_type=DeltaOpType.SET,
            field_path="tool_call.arguments.rate",
            type_tag=TypeTag.FLOAT64,
            value=0.10,
        )
        assert op.op_type == DeltaOpType.SET
        assert op.field_path == "tool_call.arguments.rate"
        assert op.type_tag == TypeTag.FLOAT64
        assert op.value == 0.10

    def test_del_op_construction(self):
        """DeltaOp DEL has None type_tag and value."""
        op = DeltaOp(
            op_type=DeltaOpType.DEL,
            field_path="result.error",
        )
        assert op.op_type == DeltaOpType.DEL
        assert op.type_tag is None
        assert op.value is None

    def test_spl_op_construction(self):
        """DeltaOp SPL stores splice_start and splice_end."""
        op = DeltaOp(
            op_type=DeltaOpType.SPL,
            field_path="items",
            type_tag=TypeTag.STRING,
            value="replacement",
            splice_start=1,
            splice_end=3,
        )
        assert op.splice_start == 1
        assert op.splice_end == 3


# ---------------------------------------------------------------------------
# RelayField
# ---------------------------------------------------------------------------


class TestRelayField:
    """Tests for the RelayField dataclass."""

    def test_construction(self):
        """RelayField stores all four fields correctly."""
        ev = EnumValue(name="assistant", index=2)
        f = RelayField(field_id=1, name="role", type_tag=TypeTag.ENUM, value=ev)
        assert f.field_id == 1
        assert f.name == "role"
        assert f.type_tag == TypeTag.ENUM
        assert f.value == ev

    def test_string_field(self):
        """RelayField works with a string value."""
        f = RelayField(field_id=2, name="note", type_tag=TypeTag.STRING, value="hi")
        assert f.value == "hi"


# ---------------------------------------------------------------------------
# RelayMessage
# ---------------------------------------------------------------------------


class TestRelayMessage:
    """Tests for the RelayMessage dataclass and its helper methods."""

    def _make_message(self) -> RelayMessage:
        ev = EnumValue(name="assistant", index=2)
        fields = [
            RelayField(field_id=1, name="role", type_tag=TypeTag.ENUM, value=ev),
            RelayField(field_id=2, name="score", type_tag=TypeTag.FLOAT64, value=3.14),
        ]
        return RelayMessage(
            message_type=MessageType.FULL,
            schema_hash=bytes.fromhex("a3f2bc01"),
            fields=fields,
        )

    def test_construction(self):
        """RelayMessage stores message_type and schema_hash correctly."""
        msg = self._make_message()
        assert msg.message_type == MessageType.FULL
        assert msg.schema_hash == bytes.fromhex("a3f2bc01")

    def test_get_field_found(self):
        """get_field returns the correct RelayField when the name exists."""
        msg = self._make_message()
        f = msg.get_field("role")
        assert f is not None
        assert f.name == "role"
        assert f.type_tag == TypeTag.ENUM

    def test_get_field_not_found(self):
        """get_field returns None when the name does not exist."""
        msg = self._make_message()
        result = msg.get_field("nonexistent")
        assert result is None

    def test_to_dict_message_type_key(self):
        """to_dict returns a dict with 'message_type' key equal to 'FULL'."""
        msg = self._make_message()
        d = msg.to_dict()
        assert d["message_type"] == "FULL"

    def test_to_dict_schema_hash_key(self):
        """to_dict returns a dict with 'schema_hash' key as hex string."""
        msg = self._make_message()
        d = msg.to_dict()
        assert d["schema_hash"] == "a3f2bc01"

    def test_to_dict_fields_is_list(self):
        """to_dict['fields'] is a list with two entries."""
        msg = self._make_message()
        d = msg.to_dict()
        assert isinstance(d["fields"], list)
        assert len(d["fields"]) == 2

    def test_to_dict_field_name(self):
        """to_dict['fields'][0]['name'] equals 'role'."""
        msg = self._make_message()
        d = msg.to_dict()
        assert d["fields"][0]["name"] == "role"

    def test_default_raw_bytes_is_none(self):
        """raw_bytes defaults to None when not provided."""
        msg = RelayMessage(
            message_type=MessageType.FULL,
            schema_hash=b"\x00\x00\x00\x00",
            fields=[],
        )
        assert msg.raw_bytes is None

    def test_default_fields_is_empty_list(self):
        """fields defaults to an empty list when not provided."""
        msg = RelayMessage(
            message_type=MessageType.FULL,
            schema_hash=b"\x00\x00\x00\x00",
        )
        assert msg.fields == []
