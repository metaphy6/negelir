"""Echo agent — the canonical Phase 3 example.

Consumes `echo.in` and publishes `echo.out` with the same payload plus
an `echoed_by` marker. Runs against `InMemoryBus` (default) or
`RedisStreamsBus` (with `--bus redis`).

Usage (in-process smoke):

    python -m swarm.sdk.examples.echo --count 5
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable

from ..agent import FunctionAgent
from ..bus import Bus, InMemoryBus, RedisStreamsBus
from ..registry import AgentRegistry
from ..runner import AgentRunner
from ..types import Message, Topic

ECHO_IN = Topic("echo.in")
ECHO_OUT = Topic("echo.out")


def echo_handler(msg: Message) -> Iterable[Message]:
    yield Message.new(
        topic=ECHO_OUT,
        payload={**msg.payload, "echoed_by": "echo.v1"},
        producer="echo.v1",
        trace_id=msg.envelope.trace_id,
    )


def build_agent() -> FunctionAgent:
    return FunctionAgent(
        name="echo.v1",
        subscribes=[ECHO_IN],
        publishes=[ECHO_OUT],
        fn=echo_handler,
    )


def _build_bus(kind: str, host: str, port: int) -> Bus:
    if kind == "memory":
        return InMemoryBus()
    if kind == "redis":
        return RedisStreamsBus(host=host, port=port)
    raise ValueError(f"unknown bus kind {kind!r}; choose 'memory' or 'redis'")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Echo swarm agent")
    parser.add_argument("--bus", choices=("memory", "redis"), default="memory")
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument(
        "--count", type=int, default=1,
        help="In smoke mode (memory bus): publish N messages, drain, exit."
    )
    args = parser.parse_args(argv)

    bus = _build_bus(args.bus, args.redis_host, args.redis_port)
    registry = AgentRegistry()
    agent = build_agent()
    runner = AgentRunner(
        agent=agent,
        bus=bus,
        registry=registry,
        max_in_flight=8,
        retry_budget=3,
    )

    if args.bus == "memory":
        runner.register()
        try:
            for i in range(args.count):
                bus.publish(Message.new(ECHO_IN, {"i": i}, producer="example"))
            for _ in range(args.count):
                if not runner.step():
                    break
            outs = bus.drain_topic(ECHO_OUT)
            for out in outs:
                print(out.payload)
        finally:
            runner.deregister()
        return 0

    # Redis: long-running loop until SIGTERM.
    runner.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
