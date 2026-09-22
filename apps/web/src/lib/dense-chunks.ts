export interface DenseChunkBounds {
  readonly fromNs: bigint;
  readonly toNs: bigint;
  readonly id: string;
}

export interface DenseChunkPlan {
  readonly active: DenseChunkBounds;
  readonly previous: DenseChunkBounds | null;
  readonly next: DenseChunkBounds | null;
}

export interface DenseChunkConfig {
  readonly canonicalMinNs: bigint;
  readonly canonicalMaxNs: bigint;
  readonly anchorNs: bigint | null;
  readonly chunkSpanNs: bigint;
}

export function denseChunkId(fromNs: bigint, toNs: bigint): string {
  return `${fromNs.toString()}..${toNs.toString()}`;
}

export function planDenseChunks(config: DenseChunkConfig): DenseChunkPlan | null {
  if (config.chunkSpanNs <= 0n || config.canonicalMaxNs < config.canonicalMinNs) return null;
  const span = config.canonicalMaxNs - config.canonicalMinNs;
  const chunkSpan = config.chunkSpanNs > span ? span + 1n : config.chunkSpanNs;
  const anchor = clamp(config.anchorNs ?? config.canonicalMinNs, config.canonicalMinNs, config.canonicalMaxNs);
  const index = (anchor - config.canonicalMinNs) / chunkSpan;
  const start = config.canonicalMinNs + index * chunkSpan;
  const active = makeBounds(start, min(config.canonicalMaxNs, start + chunkSpan - 1n));
  const previous = active.fromNs > config.canonicalMinNs
    ? makeBounds(max(config.canonicalMinNs, active.fromNs - chunkSpan), active.fromNs - 1n)
    : null;
  const next = active.toNs < config.canonicalMaxNs
    ? makeBounds(active.toNs + 1n, min(config.canonicalMaxNs, active.toNs + chunkSpan))
    : null;
  return { active, previous, next };
}

export function isExactChunk(meta: { readonly reduction: unknown }): boolean {
  return meta.reduction === null;
}

function makeBounds(fromNs: bigint, toNs: bigint): DenseChunkBounds {
  return { fromNs, toNs, id: denseChunkId(fromNs, toNs) };
}

function clamp(value: bigint, lower: bigint, upper: bigint): bigint {
  return value < lower ? lower : value > upper ? upper : value;
}

function min(left: bigint, right: bigint): bigint {
  return left < right ? left : right;
}

function max(left: bigint, right: bigint): bigint {
  return left > right ? left : right;
}
