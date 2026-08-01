# Advanced Backend Day 3

## Goal

- Advance from basic distributed-systems vocabulary into the mechanics of replication, sharding, and consistency.
- Understand how systems behave when a node fails, a leader changes, or a read races a write.

## Focus Areas

- Replication topologies and leader election
- Sharding keys, rebalancing, and hot partitions
- Consistency models and tradeoffs
- Failover behavior and recovery
- Read-your-writes, monotonic reads, and stale data scenarios

## Replication

- Replication improves availability and read capacity by keeping multiple copies of the same data.
- Primary-replica systems route writes to one leader and copy changes to followers.
- Multi-leader systems accept writes in more than one place, which can improve locality but creates conflict resolution problems.
- Replication lag is normal, so a successful write is not always immediately visible on every replica.
- If reads can go to replicas, the system must decide whether it values freshness or load distribution more.

## Sharding

- Sharding splits data into partitions so one machine does not have to hold or process everything.
- A shard key should spread traffic evenly and preserve access locality for the most common queries.
- Bad shard keys create hot partitions, where one shard becomes the bottleneck even though the cluster looks healthy overall.
- Rebalancing is operationally expensive because data has to move while the system stays online.
- Cross-shard queries are slower and more complex because the system has to fan out work and merge results.

## Consistency

- Strong consistency means a read reflects the latest acknowledged write, but it often costs latency and coordination.
- Eventual consistency accepts temporary disagreement between replicas in exchange for better availability and locality.
- Read-after-write consistency is the minimum many user-facing systems need for a sane experience.
- Monotonic reads prevent a user from seeing data move backward in time across requests.
- Consistency is not binary; many systems choose different guarantees for different operations.

## Failover

- Failover is the process of moving traffic to a different node when the current one stops working or stops being trusted.
- A clean failover needs failure detection, leader promotion, client rerouting, and a way to avoid split brain.
- During failover, the most important question is not whether the system is up, but whether it is serving the right version of the data.
- Fast failover is only useful if the new leader has the data needed to continue safely.
- Automatic recovery should be designed to fail safely, not just quickly.

## Tradeoffs Recap

- Replication: higher availability and read throughput, plus lag and conflict risk.
- Sharding: higher total capacity, plus rebalancing complexity and cross-shard cost.
- Strong consistency: simpler correctness, plus coordination overhead and lower availability under failure.
- Eventual consistency: better availability and latency, plus temporary anomalies that the product must tolerate.

## Checklist

- Explain the difference between replication and sharding without mixing them together.
- Predict what a user sees when a write lands on one node and the next read hits a lagging replica.
- Choose a shard key for a workload and identify the hot-key risk.
- Describe how failover can create stale reads, duplicate writes, or brief unavailability.
- State which consistency guarantee the product actually requires, not which one sounds ideal.

## Reflection

Distributed systems are rarely broken in obvious ways. They usually fail in the gaps between replicas, during promotion, or at the boundaries where an assumption about freshness stops being true.

## Next Step

- Create Day 4 notes on distributed coordination, leader election, consensus, and practical failure handling patterns.
