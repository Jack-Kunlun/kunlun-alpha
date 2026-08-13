/**
 * Repository abstraction.
 *
 * Business tables store control-plane state (providers, tasks, checkpoints,
 * data versions, quality events) — never high-frequency market data, which
 * belongs in ClickHouse (P1-N10).
 */

export interface Entity {
  id: string;
}

export interface Repository<T extends Entity> {
  findById(id: string): Promise<T | null>;
  save(entity: T): Promise<void>;
  findAll(): Promise<T[]>;
}

export class InMemoryRepository<T extends Entity> implements Repository<T> {
  private readonly store = new Map<string, T>();

  async findById(id: string): Promise<T | null> {
    return this.store.get(id) ?? null;
  }

  async save(entity: T): Promise<void> {
    this.store.set(entity.id, entity);
  }

  async findAll(): Promise<T[]> {
    return [...this.store.values()];
  }
}
