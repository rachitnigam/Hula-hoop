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

## Code sources

- Built upon the skeleton code from homework03 for CS6114 fall 18, by Nate Foster, Cornell University.
- Fat tree topology generation code taken from the [Frenetic](https://github.com/frenetic-lang/frenetic) repository.
