# Advanced Backend Day 2

## Goal

- Go deeper on the four areas flagged at the end of Day 1: API design, database indexing, caching, and queue-based workflows.
- Move from naming concepts to knowing when each one is the right tool and what it costs.

## Focus Areas

- API contracts, versioning, and pagination
- Index design and query planning
- Cache placement, invalidation, and failure modes
- Queue semantics, delivery guarantees, and worker design

## API Design

- The contract is the hardest part to change later, so treat request and response shapes as long-lived commitments.
- Version at the boundary, not inside business logic, so old and new clients can be served by the same core code.
- Additive changes are safe; removing or renaming a field is a breaking change even if no client seems to use it.
- Prefer cursor-based pagination over offset-based for large or frequently changing collections, because offsets drift and get slower as they grow.
- Return errors in a consistent, machine-readable shape so clients can branch on a code instead of parsing prose.
- Make write endpoints idempotent with a client-supplied key so a retried request cannot create duplicate work.
- Validate at the edge and fail fast, so bad input never reaches the database or the queue.

## Database Indexing

- An index is a separate ordered structure that trades write throughput and storage for read speed.
- Composite index column order matters: it can serve queries that filter on a leading prefix, not on a trailing column alone.
- A covering index answers a query entirely from the index and avoids the extra lookup back into the table.
- Low-cardinality columns rarely make good standalone indexes because the planner may prefer a full scan anyway.
- Read the query plan before and after adding an index; assume nothing about which index the planner chooses.
- Watch for redundant indexes, since every one of them is paid for on each insert, update, and delete.
- Indexes cannot fix a query shape that does not match the access pattern; sometimes the schema is the problem.

## Caching

- Cache what is expensive to compute and frequently read, and only when a slightly stale answer is acceptable.
- Cache-aside is the common default: read the cache, fall through to the database on a miss, then populate.
- Write-through keeps the cache fresh at the cost of write latency; write-behind is faster but risks losing writes.
- Invalidation is the hard part. Prefer short TTLs plus explicit invalidation on write over trying to be perfectly correct.
- A stampede happens when a popular key expires and every request hits the database at once; mitigate with locking, jittered TTLs, or serving stale data while refreshing.
- Cache the negative result too, so repeated lookups for missing data do not keep reaching the database.
- The cache is not a source of truth. The system must still function, if more slowly, when it is empty or unavailable.

## Queues and Asynchronous Workflows

- Move work off the request path when the caller does not need the result to respond.
- Most brokers give at-least-once delivery, which means consumers must be idempotent because duplicates will happen.
- Ordering guarantees are usually per-partition or per-key, not global; design keys so related events land together.
- Use a dead letter queue so a permanently failing message stops blocking the rest of the work.
- Retry with exponential backoff and a cap, and treat a message that has failed many times as a signal, not a transient blip.
- Queue depth and consumer lag are the health metrics that matter; growing lag means consumers are under-provisioned or stuck.
- A queue absorbs bursts, but it does not increase total capacity. If arrival rate exceeds processing rate for long, the backlog only grows.

## Tradeoffs Recap

- Index: faster reads, slower writes, more storage.
- Cache: lower latency, weaker freshness, another failure mode to reason about.
- Queue: better burst tolerance and isolation, at the cost of eventual consistency and harder debugging.
- API versioning: client stability, at the cost of maintaining more than one path.

## Checklist

- Explain when cursor pagination beats offset pagination.
- Given a query, predict which index it uses and confirm with the plan.
- Describe a cache invalidation strategy for a read-heavy endpoint and its staleness window.
- Trace one write through an asynchronous path and identify where duplicates could occur.
- For each mechanism above, state the cost, not just the benefit.

## Reflection

Each of these tools solves a real bottleneck and introduces a new failure mode in exchange. The skill is not knowing that caches and queues exist, it is knowing which bottleneck is actually present and accepting the specific cost that comes with fixing it.

## Next Step

- Create Day 3 notes on replication, sharding, and consistency models, including how reads and writes behave during failover.
