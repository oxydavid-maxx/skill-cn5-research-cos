# §5 In-Band Interrupt (IBI)

In-Band Interrupt allows an I3C target to request the controller's attention
over the two-wire bus itself, without a dedicated interrupt line. The target
drives an IBI during the Start condition arbitration; the controller may ACK or
NACK the request based on its IBI policy.
