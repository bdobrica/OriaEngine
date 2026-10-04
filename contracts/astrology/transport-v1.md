# Astrology MCP transport limits v1

The [natal JSON schema](v1.json) and [transit JSON schema](transits-v1.json) retain
their existing fields and calculation semantics. Oria's HTTP MCP consumer imposes a
20-second whole-operation deadline and a 256-KiB limit per HTTP response, including
JSON or SSE protocol framing, checked before SDK parsing. Uncompressed responses
are required; the consumer requests `Accept-Encoding: identity` and rejects other
content encodings. The owned calculation service already satisfies these limits.

Oversized, malformed, failed or mismatched results yield generic calculation
unavailability. No partial facts may activate a profile or be passed to interpretation.
Cancellation propagates. Consumer errors and logs never include request/response
values. These local resource bounds introduce no tool, schema field or calculation
change. Future larger results or compressed transport require an explicit compatible
transport update and corresponding consumer tests.
