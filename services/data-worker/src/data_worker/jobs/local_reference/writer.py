"""Transactional PostgreSQL writer for the local terminal reference catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import psycopg
from psycopg import Connection, Cursor, sql
from psycopg.types.json import Jsonb

from .catalog import JsonValue, LocalReferencePlan

type Row = tuple[object, ...]
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class LocalReferenceMaterializationError(RuntimeError):
    """The catalog could not be persisted without violating immutability."""


@dataclass(frozen=True, slots=True)
class LocalReferenceMaterializationResult:
    inserted: int
    existing: int


class PostgresLocalReferenceWriter:
    """Append immutable reference revisions in one all-or-nothing transaction."""

    def __init__(self, connection: str | Connection[Row], *, schema: str = "kunlun") -> None:
        if _IDENTIFIER.fullmatch(schema) is None:
            raise ValueError("schema must be a safe PostgreSQL identifier")
        self._owns_connection = isinstance(connection, str)
        self._connection = (
            cast(Connection[Row], psycopg.connect(connection))
            if isinstance(connection, str)
            else connection
        )
        self._schema = schema

    def close(self) -> None:
        if self._owns_connection and not self._connection.closed:
            self._connection.close()

    def write(self, plan: LocalReferencePlan) -> LocalReferenceMaterializationResult:
        inserted = 0
        existing = 0
        with self._connection.transaction(), self._connection.cursor() as cursor:
            # The schema has no partial unique index for one open revision per
            # identity. Serialize this small, one-shot catalog materializer so
            # two concurrent upgrades cannot both publish a new root/head.
            for table in (
                "instrument_master_revisions",
                "sector_master_revisions",
                "sector_membership_revisions",
            ):
                cursor.execute(
                    sql.SQL("LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE").format(
                        table=sql.Identifier(self._schema, table)
                    )
                )
            cursor.execute("SELECT CURRENT_TIMESTAMP")
            time_row = cursor.fetchone()
            if time_row is None or not isinstance(time_row[0], datetime):
                raise LocalReferenceMaterializationError("database clock could not be read")
            processing_time = time_row[0]
            if processing_time < plan.catalog.available_time:
                raise LocalReferenceMaterializationError(
                    "catalog availableTime is later than the database clock"
                )

            for revision in plan.instrument_revisions:
                created = self._write_revision(
                    cursor,
                    table="instrument_master_revisions",
                    identity_columns=("instrument_id",),
                    identity_values=(revision.instrument_id,),
                    revision_id=revision.revision_id,
                    payload=revision.payload,
                    payload_fingerprint=revision.payload_fingerprint,
                    plan=plan,
                    processing_time=processing_time,
                )
                inserted += int(created)
                existing += int(not created)
            for revision in plan.sector_revisions:
                created = self._write_revision(
                    cursor,
                    table="sector_master_revisions",
                    identity_columns=("sector_id",),
                    identity_values=(revision.sector_id,),
                    revision_id=revision.revision_id,
                    payload=revision.payload,
                    payload_fingerprint=revision.payload_fingerprint,
                    plan=plan,
                    processing_time=processing_time,
                )
                inserted += int(created)
                existing += int(not created)
            for revision in plan.membership_revisions:
                created = self._write_revision(
                    cursor,
                    table="sector_membership_revisions",
                    identity_columns=("instrument_id", "sector_id"),
                    identity_values=(revision.instrument_id, revision.sector_id),
                    revision_id=revision.revision_id,
                    payload=revision.payload,
                    payload_fingerprint=revision.payload_fingerprint,
                    plan=plan,
                    processing_time=processing_time,
                )
                inserted += int(created)
                existing += int(not created)
        return LocalReferenceMaterializationResult(inserted=inserted, existing=existing)

    def _write_revision(
        self,
        cursor: Cursor[Row],
        *,
        table: str,
        identity_columns: tuple[str, ...],
        identity_values: tuple[str, ...],
        revision_id: str,
        payload: dict[str, JsonValue],
        payload_fingerprint: str,
        plan: LocalReferencePlan,
        processing_time: datetime,
    ) -> bool:
        table_name = sql.Identifier(self._schema, table)
        identity_names = sql.SQL(", ").join(sql.Identifier(name) for name in identity_columns)
        identity_placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in identity_columns)
        identity_predicate = sql.SQL(" AND ").join(
            sql.SQL("{column} = {placeholder}").format(
                column=sql.Identifier(name),
                placeholder=sql.Placeholder(),
            )
            for name in identity_columns
        )
        cursor.execute(
            sql.SQL(
                "SELECT revision_id, effective_from, available_time "
                "FROM {table} WHERE {identity_predicate} AND effective_to IS NULL "
                "ORDER BY revision_id FOR UPDATE"
            ).format(table=table_name, identity_predicate=identity_predicate),
            identity_values,
        )
        open_revisions = cursor.fetchall()
        if len(open_revisions) > 1:
            raise LocalReferenceMaterializationError(
                f"multiple open revisions for {table}/{':'.join(identity_values)}"
            )

        selected_columns = sql.SQL(", ").join(
            [
                sql.Identifier("previous_revision_id"),
                *(sql.Identifier(name) for name in identity_columns),
                sql.Identifier("effective_from"),
                sql.Identifier("effective_to"),
                sql.Identifier("available_time"),
                sql.Identifier("source"),
                sql.Identifier("source_version"),
                sql.Identifier("evidence_id"),
                sql.Identifier("payload_fingerprint"),
                sql.Identifier("payload"),
            ]
        )
        cursor.execute(
            sql.SQL("SELECT {columns} FROM {table} WHERE revision_id = %s FOR UPDATE").format(
                columns=selected_columns,
                table=table_name,
            ),
            (revision_id,),
        )
        actual = cursor.fetchone()
        if actual is not None:
            expected_tail: Row = (
                *identity_values,
                plan.catalog.effective_from,
                None,
                plan.catalog.available_time,
                plan.catalog.source,
                plan.catalog.source_version,
                plan.catalog.evidence_id,
                payload_fingerprint,
                payload,
            )
            raw_previous_revision_id = actual[0]
            if raw_previous_revision_id is not None and not isinstance(
                raw_previous_revision_id, str
            ):
                raise LocalReferenceMaterializationError(
                    f"invalid predecessor for {table}/{revision_id}"
                )
            previous_revision_id = raw_previous_revision_id
            if actual[1:] != expected_tail or open_revisions != [
                (revision_id, plan.catalog.effective_from, plan.catalog.available_time)
            ]:
                raise LocalReferenceMaterializationError(
                    f"immutable revision conflict for {table}/{revision_id}"
                )
            if previous_revision_id is not None:
                if previous_revision_id == revision_id:
                    raise LocalReferenceMaterializationError(
                        f"invalid predecessor for {table}/{revision_id}"
                    )
                cursor.execute(
                    sql.SQL(
                        "SELECT {identity_columns}, effective_from, effective_to FROM {table} "
                        "WHERE revision_id = %s"
                    ).format(identity_columns=identity_names, table=table_name),
                    (previous_revision_id,),
                )
                predecessor = cursor.fetchone()
                # ``effective_to`` is the transaction time at which the new
                # revision became visible, not its possibly earlier business
                # effective time. The predecessor must be the same identity
                # and have a valid closed interval.
                if (
                    predecessor is None
                    or predecessor[:-2] != identity_values
                    or not isinstance(predecessor[-2], datetime)
                    or not isinstance(predecessor[-1], datetime)
                    or predecessor[-1] <= predecessor[-2]
                ):
                    raise LocalReferenceMaterializationError(
                        f"invalid predecessor chain for {table}/{revision_id}"
                    )
            else:
                cursor.execute(
                    sql.SQL(
                        "SELECT COUNT(*) FROM {table} WHERE {identity_predicate} "
                        "AND revision_id <> %s"
                    ).format(table=table_name, identity_predicate=identity_predicate),
                    (*identity_values, revision_id),
                )
                if cursor.fetchone() != (0,):
                    raise LocalReferenceMaterializationError(
                        f"root revision has unexpected history for {table}/{revision_id}"
                    )
            return False

        previous_revision_id: str | None = None
        if open_revisions:
            current_revision_id, current_effective_from, current_available_time = open_revisions[0]
            if (
                not isinstance(current_revision_id, str)
                or not isinstance(current_effective_from, datetime)
                or not isinstance(current_available_time, datetime)
                or plan.catalog.available_time <= current_available_time
                or processing_time <= current_effective_from
            ):
                raise LocalReferenceMaterializationError(
                    f"catalog revision does not advance {table}/{':'.join(identity_values)}"
                )
            cursor.execute(
                sql.SQL(
                    "UPDATE {table} SET effective_to = %s "
                    "WHERE revision_id = %s AND effective_to IS NULL"
                ).format(table=table_name),
                (processing_time, current_revision_id),
            )
            if cursor.rowcount != 1:
                raise LocalReferenceMaterializationError(
                    f"open revision changed concurrently for {table}/{current_revision_id}"
                )
            previous_revision_id = current_revision_id

        cursor.execute(
            sql.SQL(
                """
                INSERT INTO {table} (
                  revision_id, previous_revision_id, {identity_columns},
                  effective_from, effective_to, available_time, processing_time,
                  source, source_version, evidence_id, payload_fingerprint, payload, created_at
                ) VALUES (
                  %s, %s, {identity_placeholders}, %s, NULL, %s, %s,
                  %s, %s, %s, %s, %s, %s
                )
                RETURNING revision_id
                """
            ).format(
                table=table_name,
                identity_columns=identity_names,
                identity_placeholders=identity_placeholders,
            ),
            (
                revision_id,
                previous_revision_id,
                *identity_values,
                plan.catalog.effective_from,
                plan.catalog.available_time,
                processing_time,
                plan.catalog.source,
                plan.catalog.source_version,
                plan.catalog.evidence_id,
                payload_fingerprint,
                Jsonb(payload),
                processing_time,
            ),
        )
        if cursor.fetchone() != (revision_id,):
            raise LocalReferenceMaterializationError(
                f"revision insert was not acknowledged for {table}/{revision_id}"
            )
        return True
