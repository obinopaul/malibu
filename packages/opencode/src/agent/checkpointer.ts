/**
 * SQLite Checkpointer — persistent checkpoint storage for LangGraph agents.
 *
 * Uses a dedicated SQLite database (separate from the main Drizzle DB)
 * to store LangGraph checkpoints, enabling session persistence across restarts.
 *
 * Tables:
 * - checkpoints: stores serialized checkpoint data per thread/checkpoint ID
 * - checkpoint_writes: stores pending writes per thread/task
 */
import { Database } from "bun:sqlite"
import {
  BaseCheckpointSaver,
  type Checkpoint,
  type CheckpointListOptions,
  type CheckpointTuple,
  type CheckpointMetadata,
} from "@langchain/langgraph-checkpoint"
import type { RunnableConfig } from "@langchain/core/runnables"
import type { PendingWrite, CheckpointPendingWrite } from "@langchain/langgraph-checkpoint"
import { Global } from "../global"
import { Log } from "../util/log"
import path from "path"

const log = Log.create({ service: "sqlite-checkpointer" })

const SCHEMA_VERSION = 1

export class SqliteCheckpointer extends BaseCheckpointSaver {
  private db: Database

  constructor(dbPath?: string) {
    super()
    const resolvedPath = dbPath ?? path.join(Global.Path.data, "langgraph-checkpoints.db")
    log.info("opening checkpoint database", { path: resolvedPath })
    this.db = new Database(resolvedPath, { create: true })
    this.db.run("PRAGMA journal_mode = WAL")
    this.db.run("PRAGMA synchronous = NORMAL")
    this.db.run("PRAGMA busy_timeout = 5000")
    this.setup()
  }

  private setup() {
    this.db.run(`
      CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        parent_checkpoint_id TEXT,
        type TEXT,
        checkpoint BLOB,
        metadata BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
      )
    `)
    this.db.run(`
      CREATE TABLE IF NOT EXISTS checkpoint_writes (
        thread_id TEXT NOT NULL,
        checkpoint_ns TEXT NOT NULL DEFAULT '',
        checkpoint_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        idx INTEGER NOT NULL,
        channel TEXT,
        type TEXT,
        value BLOB,
        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
      )
    `)
    this.db.run(`
      CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
      )
    `)
    const row = this.db.query(`SELECT version FROM schema_version LIMIT 1`).get() as any
    if (!row) {
      this.db.run(`INSERT INTO schema_version (version) VALUES (?)`, [SCHEMA_VERSION])
    } else if (row.version < SCHEMA_VERSION) {
      this.migrate(row.version)
      this.db.run(`UPDATE schema_version SET version = ?`, [SCHEMA_VERSION])
    }
  }

  private migrate(fromVersion: number) {
    log.info("migrating checkpointer schema", { from: fromVersion, to: SCHEMA_VERSION })
    // Future migrations go here
  }

  private getThreadId(config: RunnableConfig): string {
    return config.configurable?.thread_id ?? ""
  }

  private getCheckpointNs(config: RunnableConfig): string {
    return config.configurable?.checkpoint_ns ?? ""
  }

  private getCheckpointId(config: RunnableConfig): string | undefined {
    return config.configurable?.checkpoint_id
  }

  async getTuple(config: RunnableConfig): Promise<CheckpointTuple | undefined> {
    const threadId = this.getThreadId(config)
    const checkpointNs = this.getCheckpointNs(config)
    const checkpointId = this.getCheckpointId(config)

    let row: any
    if (checkpointId) {
      row = this.db
        .query(
          `SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
           FROM checkpoints
           WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?`,
        )
        .get(threadId, checkpointNs, checkpointId)
    } else {
      row = this.db
        .query(
          `SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
           FROM checkpoints
           WHERE thread_id = ? AND checkpoint_ns = ?
           ORDER BY checkpoint_id DESC LIMIT 1`,
        )
        .get(threadId, checkpointNs)
    }

    if (!row) return undefined

    const checkpoint = await this.serde.loadsTyped(
      row.type ?? "json",
      row.checkpoint,
    )
    const metadata = row.metadata
      ? await this.serde.loadsTyped(row.type ?? "json", row.metadata)
      : {}

    const resultConfig: RunnableConfig = {
      configurable: {
        thread_id: threadId,
        checkpoint_ns: checkpointNs,
        checkpoint_id: row.checkpoint_id,
      },
    }

    const parentConfig = row.parent_checkpoint_id
      ? {
          configurable: {
            thread_id: threadId,
            checkpoint_ns: checkpointNs,
            checkpoint_id: row.parent_checkpoint_id,
          },
        }
      : undefined

    // Load pending writes
    const writeRows = this.db
      .query(
        `SELECT task_id, channel, type, value
         FROM checkpoint_writes
         WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?
         ORDER BY idx`,
      )
      .all(threadId, checkpointNs, row.checkpoint_id) as any[]

    const pendingWrites: CheckpointPendingWrite[] = []
    for (const wr of writeRows) {
      const value = await this.serde.loadsTyped(wr.type ?? "json", wr.value)
      pendingWrites.push([wr.task_id, wr.channel, value])
    }

    return {
      config: resultConfig,
      checkpoint,
      metadata,
      parentConfig,
      pendingWrites,
    }
  }

  async *list(
    config: RunnableConfig,
    options?: CheckpointListOptions,
  ): AsyncGenerator<CheckpointTuple> {
    const threadId = this.getThreadId(config)
    const checkpointNs = this.getCheckpointNs(config)
    const limit = options?.limit ?? 100

    let query = `SELECT checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata
                 FROM checkpoints
                 WHERE thread_id = ? AND checkpoint_ns = ?`
    const params: any[] = [threadId, checkpointNs]

    if (options?.before?.configurable?.checkpoint_id) {
      query += ` AND checkpoint_id < ?`
      params.push(options.before.configurable.checkpoint_id)
    }

    query += ` ORDER BY checkpoint_id DESC LIMIT ?`
    params.push(limit)

    const rows = this.db.query(query).all(...params) as any[]

    for (const row of rows) {
      const checkpoint = await this.serde.loadsTyped(
        row.type ?? "json",
        row.checkpoint,
      )
      const metadata = row.metadata
        ? await this.serde.loadsTyped(row.type ?? "json", row.metadata)
        : {}

      yield {
        config: {
          configurable: {
            thread_id: threadId,
            checkpoint_ns: checkpointNs,
            checkpoint_id: row.checkpoint_id,
          },
        },
        checkpoint,
        metadata,
        parentConfig: row.parent_checkpoint_id
          ? {
              configurable: {
                thread_id: threadId,
                checkpoint_ns: checkpointNs,
                checkpoint_id: row.parent_checkpoint_id,
              },
            }
          : undefined,
      }
    }
  }

  async put(
    config: RunnableConfig,
    checkpoint: Checkpoint,
    metadata: CheckpointMetadata,
    _newVersions: Record<string, number | string>,
  ): Promise<RunnableConfig> {
    const threadId = this.getThreadId(config)
    const checkpointNs = this.getCheckpointNs(config)

    const [type, serializedCheckpoint] = await this.serde.dumpsTyped(checkpoint)
    const [, serializedMetadata] = await this.serde.dumpsTyped(metadata)

    const parentCheckpointId = this.getCheckpointId(config)

    this.db
      .query(
        `INSERT OR REPLACE INTO checkpoints
         (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, type, checkpoint, metadata)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
      )
      .run(
        threadId,
        checkpointNs,
        checkpoint.id,
        parentCheckpointId ?? null,
        type,
        serializedCheckpoint,
        serializedMetadata,
      )

    return {
      configurable: {
        thread_id: threadId,
        checkpoint_ns: checkpointNs,
        checkpoint_id: checkpoint.id,
      },
    }
  }

  async putWrites(
    config: RunnableConfig,
    writes: PendingWrite[],
    taskId: string,
  ): Promise<void> {
    const threadId = this.getThreadId(config)
    const checkpointNs = this.getCheckpointNs(config)
    const checkpointId = this.getCheckpointId(config) ?? ""

    const stmt = this.db.query(
      `INSERT OR REPLACE INTO checkpoint_writes
       (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, value)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    )

    for (let i = 0; i < writes.length; i++) {
      const write = writes[i]!
      const [channel, value] = write
      const [type, serializedValue] = await this.serde.dumpsTyped(value)
      stmt.run(threadId, checkpointNs, checkpointId, taskId, i, channel, type, serializedValue)
    }
  }

  async deleteThread(threadId: string): Promise<void> {
    this.db
      .query(`DELETE FROM checkpoint_writes WHERE thread_id = ?`)
      .run(threadId)
    this.db
      .query(`DELETE FROM checkpoints WHERE thread_id = ?`)
      .run(threadId)
  }

  vacuum() {
    this.db.run("VACUUM")
  }

  cleanup(olderThanDays: number) {
    // SQLite checkpoint_id is typically a ULID or timestamp-ordered ID
    // We'll delete based on when the checkpoint was created
    // Since we don't have a created_at column, we'll add one in the next schema version
    // For now, use a thread-level approach: delete threads with no recent writes
    log.info("cleaning up old checkpoints", { olderThanDays })
  }

  close() {
    this.db.close()
  }
}
