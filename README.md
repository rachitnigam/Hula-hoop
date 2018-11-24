# HULA hoop

Implementation of the [HULA](https://conferences.sigcomm.org/sosr/2016/papers/sosr_paper67.pdf) algorithm.

## Implementation details

### Topology Generation

Since Fat tree topologies are commonly used in datacenters, the paper uses them
for evaluation. However, HULA doesn't require any specific topology to work
correctly. For this project, any topology with a notion of upstream and downstream
links will be sufficient.

The project assumes the following naming scheme to distinguish upstream and
downstream links: A switch in the `n`th tier has the form `sm` where `100 * n < m
< 100 * (n + 1)`.

### Multicast Implementation

The paper implements a smart form of multicast for probe replication that uses
a notion of upstream and downstream links. The smart multicast implementation
uses the aforementioned naming convention.

At the p4 level, the implementation uses `simple_switch_CLI` to program each
switch by generating configuration commands for each switch in `config/`.

**Note**: There is also code in `util` to send the correct messages to the
software switch, however, bmv doesn't completely implement message to the
Packet Replication Engine (PRE) (see [this](https://github.com/p4lang/PI/blob/d4e5aff15b3f77af578704fe03b82a15814da8f0/proto/frontend/src/device_mgr.cpp#L1772)).

### Probe packets

## Experience with P4

- The semantics of what variables are shared between the controls is not always
  clear from the program. For example, if I define an array in the ingress control,
  will it carry state across different invocations of the ingress? What makes
  registers unique to allow them to carry the state across invocations? This is
  what Andy Fingerhut from the p4 slack had to say:

      P4_16 header stack syntax looks like an array, and in many ways is, but
      only for arrays of values of some header type, and they do not preserve
      their value after finishing processing one packet.  Like other header
      types, their value disappears after a packet is finished processing

## Code sources

- Built upon the skeleton code from homework03 for CS6114 fall 18, by Nate Foster, Cornell University.
- Fat tree topology generation code taken from the [Frenetic](https://github.com/frenetic-lang/frenetic) repository.
